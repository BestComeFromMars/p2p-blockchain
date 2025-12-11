class users:
    def __init__(self):
        self.btc = 0
    def reward(self, length):
        self.btc = self.btc + length

user = users()
user.reward(12)
user.reward(4)
print(user.btc)