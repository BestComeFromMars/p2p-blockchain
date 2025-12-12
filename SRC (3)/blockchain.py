# blockchain.py
from block import Block


class Blockchain:
    def __init__(self):
        self.chains = []   

    def appendBlock(self, block):
        self.chains.append(block)

    def to_list(self):
        return [b.to_dict() for b in self.chains]

    def replace_chain(self, block_dicts):
        new_chain = []
        prev_hash = None

        for i, bd in enumerate(block_dicts):
            b = Block.from_dict(bd)

            # kiểm tra nối chuỗi
            if i > 0 and b.previous_hash != prev_hash:
                return False

            prev_hash = b.hash
            new_chain.append(b)

        if len(new_chain) > len(self.chains):
            self.chains = new_chain
            return True
        return False
