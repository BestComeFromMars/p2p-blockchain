# block.py
import hashlib
import time

DIFFICULTY = 3


class Block:
    def __init__(self, index, timestamp, data, previous_hash, nonce=0):
        self.index = index
        self.timestamp = timestamp
        self.data = data
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        raw = f"{self.index}{self.timestamp}{self.data}{self.previous_hash}{self.nonce}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def mine(self, difficulty=DIFFICULTY):
        prefix = "0" * difficulty
        while True:
            self.hash = self.calculate_hash()
            if self.hash.startswith(prefix):
                break
            self.nonce += 1

    def to_dict(self):
        return self.__dict__

    @staticmethod
    def from_dict(d):
        return Block(
            index=d["index"],
            timestamp=d["timestamp"],
            data=d["data"],
            previous_hash=d["previous_hash"],
            nonce=d["nonce"]
        )

    @staticmethod
    def create_block(previous_block, data, index):
        """
        CHỈ CÓ 1 HÀM TẠO BLOCK DUY NHẤT
        KHÔNG KHÁI NIỆM BLOCK ĐẦU
        block sinh ra từ TX & đào luôn
        """
        prev_hash = previous_block.hash if previous_block else None

        b = Block(
            index=index,
            timestamp=time.time(),
            data=data,
            previous_hash=prev_hash,
            nonce=0
        )
        b.mine()
        return b
