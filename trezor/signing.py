import ecdsa
import binascii
from hashlib import sha256, sha512
from ecdsa import curves, numbertheory, ellipticcurve, util
import pyaes
import hmac
from pbkdf2 import PBKDF2

import messages_pb2 as proto
import types_pb2 as proto_types
import tools

def message_magic(message):
    magic = chr(24) + "Bitcoin Signed Message:\n" + tools.ser_length(len(message)) + message
    return magic

###### sign/verify ######

def sign_message(bip32, coin, addr_n, message):
    signer = bip32.get_signer(addr_n)
    address = bip32.get_address(coin, addr_n)

    magic = message_magic(message)
    signature = signer.sign_deterministic(sha256(magic).digest(), hashfunc=sha256)

    for i in range(4):
        sig = chr(27 + i + 4) + signature
        try:
            verify_message(address, sig, message)
            return (address, sig)
        except:
            pass

    raise Exception("Cannot sign message")

def verify_message(address, signature, message):
    """ See http://www.secg.org/download/aid-780/sec1-v2.pdf for the math """
    curve = ecdsa.curves.SECP256k1.curve  # curve_secp256k1
    G = ecdsa.curves.SECP256k1.generator
    order = G.order()
    # extract r,s from signature
    if len(signature) != 65: raise BaseException("Wrong signature")
    r, s = util.sigdecode_string(signature[1:], order)
    nV = ord(signature[0])
    if nV < 27 or nV >= 35:
        raise BaseException("Bad encoding")
    if nV >= 31:
        compressed = True
        nV -= 4
    else:
        compressed = False

    recid = nV - 27
    # 1.1
    x = r + (recid / 2) * order
    # 1.3
    y = tools.point_y_from_x(x, recid % 2 > 0)
    # 1.4 the constructor checks that nR is at infinity
    R = ellipticcurve.Point(curve, x, y, order)
    # 1.5 compute e from message:
    h = sha256(sha256(message_magic(message)).digest()).digest()
    e = util.string_to_number(h)
    minus_e = -e % order
    # 1.6 compute Q = r^-1 (sR - eG)
    inv_r = numbertheory.inverse_mod(r, order)
    Q = inv_r * (s * R + minus_e * G)
    public_key = ecdsa.VerifyingKey.from_public_point(Q, curve=ecdsa.curves.SECP256k1)
    # check that Q is the public key
    public_key.verify_digest(signature[1:], h, sigdecode=ecdsa.util.sigdecode_string)

    if address:
        address_type = int(binascii.hexlify(tools.b58decode(address, None)[0]), 16)
        addr = tools.public_key_to_bc_address('\x04' + public_key.to_string(), address_type, compress=compressed)
        if address != addr:
            raise Exception("Invalid signature")

###### ECIES : http://memwallet.info/btcmssgs.html ######

def encrypt_message(pubkey, message, display_only, bip32, coin, address_n):

    if len(address_n) > 0:
        priv_node = bip32.get_private_node(address_n)
        priv_key = tools.EcKey(priv_node.private_key)
        signing = True
    else:
        signing = False

    if signing:
        if display_only:
            msg = chr(0x80 + 1)
        else:
            msg = chr(1)
        address, signature = sign_message(bip32, coin, address_n, message)
        address_bin = tools.bc_address_decode(address)[:21]
        msg += tools.ser_length(len(message)) + message + address_bin + signature
    else:
        if display_only:
            msg = chr(0x80)
        else:
            msg = chr(0)
        msg += tools.ser_length(len(message)) + message

    nonce = tools.get_local_entropy()
    nonce_key = tools.EcKey(nonce)
    nonce_pub = binascii.unhexlify(nonce_key.get_public_key(True))
    dest_pub = tools.public_key_to_point(pubkey)
    shared_secret_point = dest_pub * nonce_key.privkey.secret_multiplier
    shared_secret = tools.point_to_public_key(shared_secret_point, True)
    keying_bytes = PBKDF2(shared_secret, "Bitcoin Secure Message" + nonce_pub, iterations=2048, macmodule=hmac, digestmodule=sha256).read(80)
    aes_key = keying_bytes[:32]
    hmac_key = keying_bytes[32:64]
    aes_iv = keying_bytes[64:80]
    aes = pyaes.AESModeOfOperationCFB(key=aes_key, iv=aes_iv)
    payload = aes.encrypt(msg)
    msg_hmac = hmac.HMAC(key=hmac_key, msg=payload, digestmod=sha256).digest()[:8]
    return nonce_pub + payload + msg_hmac

def decrypt_message(bip32, address_n, encrypted):

    priv_node = bip32.get_private_node(address_n)
    priv_key = tools.EcKey(priv_node.private_key)

    nonce_pub = encrypted[:33]
    payload = encrypted[33:-8]
    msg_hmac = encrypted[-8:]
    shared_secret_point = tools.public_key_to_point(nonce_pub) * priv_key.privkey.secret_multiplier
    shared_secret = tools.point_to_public_key(shared_secret_point, True)
    keying_bytes = PBKDF2(shared_secret, "Bitcoin Secure Message" + nonce_pub, iterations=2048, macmodule=hmac, digestmodule=sha256).read(80)
    aes_key = keying_bytes[:32]
    hmac_key = keying_bytes[32:64]
    aes_iv = keying_bytes[64:80]
    msg_hmac_new = hmac.HMAC(key=hmac_key, msg=payload, digestmod=sha256).digest()[:8]
    if msg_hmac_new != msg_hmac:
        raise Exception('Message_HMAC does not match')
    aes = pyaes.AESModeOfOperationCFB(key=aes_key, iv=aes_iv)
    msg = aes.decrypt(payload)
    display_only = (ord(msg[0]) & 0x80) > 0
    if (ord(msg[0]) & 0x01) > 0:
        signature = msg[-65:]
        address_bin = msg[-(21+65):-65]
        address = tools.hash_160_to_bc_address(address_bin[1:], ord(address_bin[0]))
        message = msg[1:-(21+65)]
        message = tools.deser_length_string(message)
        verify_message(address, signature, message)
        decrypted = message
    else:
        decrypted = tools.deser_length_string(msg[1:])
        address = None
    return (decrypted, display_only, address)

'''
def raw_tx_header(inputs_count):
    s = ''
    s += '\x01\x00\x00\x00'  # version
    s += tools.var_int(inputs_count)  # number of inputs
    return s


def raw_tx_input(inp, script_sig):
    s = ''
    s += inp.prev_hash[::-1]  # prev hash
    s += struct.pack('<L', inp.prev_index)  # prev index
    if script_sig != '':
        s += tools.var_int(len(script_sig))  # script length
        s += script_sig  # script sig
    s += "\xff\xff\xff\xff"  # sequence
    return s


def raw_tx_middle(outputs_count):
    s = ''
    s += tools.var_int(outputs_count)  # number of outputs
    return s


def raw_tx_output(out):
    s = ''
    s += struct.pack('<Q', out.amount)  # amount

    if out.script_type == proto.PAYTOADDRESS:
        script = '\x76\xa9'  # op_dup, op_hash_160
        script += '\x14'  # push 0x14 bytes
        script += tools.bc_address_to_hash_160(out.address)
        script += '\x88\xac'  # op_equalverify, op_checksig

    elif out.script_type == proto.PAYTOSCRIPTHASH:
        raise Exception("P2SH not implemented yet!")

    else:
        raise Exception("Unknown script type!")

    s += tools.var_int(len(script))  # script length
    s += script  # script
    return s


def raw_tx_footer(for_sign):
    s = ''
    s += '\x00\x00\x00\x00'  # lock time
    if for_sign:
        s += '\x01\x00\x00\x00'  # hash type
    return s

# https://en.bitcoin.it/wiki/Protocol_specification#Variable_length_integer
def raw_tx(inputs, outputs, for_sig):
    s = ''
    s += raw_tx_header(len(inputs))

    for i in range(len(inputs)):
        inp = inputs[i]

        if for_sig == i:
            script_sig = inp.script_sig
        else:
            script_sig = ''

        s += raw_tx_input(inp, script_sig)

    s += raw_tx_middle(len(outputs))

    for output in outputs:
        s += raw_tx_output(output)

    s += raw_tx_footer()
    return s
'''

def sign_input(bip32, addr_n, tx_hash):
    pk = bip32.get_private_key(addr_n)
    private_key = ecdsa.SigningKey.from_string(pk, curve=curves.SECP256k1)
    sig = private_key.sign_digest_deterministic(tx_hash, hashfunc=sha256, sigencode=ecdsa.util.sigencode_der_canonize)
    pubkey = private_key.get_verifying_key().to_string()
    return (pubkey, sig)

'''
def sign_inputs(algo, secexp, inputs, outputs):
    # This is reworked but backward compatible (non-streaming) method from Electrum
    signatures = []
    for i in range(len(inputs)):
        addr_n = inputs[i].address_n
        print addr_n

        tx = raw_tx(inputs, outputs, for_sig=i)
        tx_hash = tools.Hash(tx)
        signatures.append(sign_input(algo, secexp, addr_n, tx_hash))
    return signatures
'''
