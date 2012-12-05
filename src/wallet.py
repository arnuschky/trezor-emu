import json

import bitkey_pb2 as proto
from algo import AlgoFactory
import tools
 
class Wallet(object):
    def __init__(self):
        self.vendor = 'slush'
        self.major_version = 0
        self.minor_version = 1
        
        self.seed = ''
        self.otp = False
        self.spv = False
        self.pin = ''
        self.algo = [proto.ELECTRUM,]
        self.maxfee_kb = 100000 # == 0.001 BTC/kB
        
    @classmethod    
    def load(cls, filename):
        data = json.load(open(filename, 'r'))
        dev = cls()
        dev.seed = str(data['seed'])
        dev.otp = data['otp']
        dev.spv = data['spv']
        dev.pin = data['pin']
        dev.maxfee_kb = data['maxfee_kb']
        return dev
        
    def save(self, filename):
        data = {}
        data['seed'] = self.seed
        data['otp'] = self.otp
        data['spv'] = self.spv
        data['pin'] = self.pin
        data['maxfee_kb'] = self.maxfee_kb
        
        json.dump(data, open(filename, 'w'))
        
    def get_UUID(self):
        # FIXME
        return 'uuid-should-be-hw-dependent'
    
    def get_seed(self):
        if self.seed == '':
            raise Exception("Device not initialized")
        return self.seed
    
    def get_master_public_key(self, algo):    
        af = AlgoFactory(algo)
        master_public_key = af.init_master_public_key(self.get_seed())
        #af.get_new_address(master_public_key, [0])
        return master_public_key
    
    def get_mnemonic(self):
        
        return tools.get_mnemonic(self.seed)
                    
    def load_seed(self, seed_words):
        self.seed = tools.get_seed(seed_words)
        print 'seed', self.seed
        print self.get_mnemonic()
        
    def reset_seed(self, random):
        seed = tools.generate_seed(random)
        seed_words = tools.get_mnemonic(seed)
        self.load_seed(seed_words)
        
    '''
    def set_otp(self, is_otp):
        self.otp = is_otp
    
    def set_pin(self, pin):
        self.pin = pin
    
    def set_spv(self, spv):
        self.spv = spv
     
    def sign_tx(self, algo, inputs, outputs):
        # TODO
        pass
    '''