import time


class CooldownManager:

    def __init__(self):
        self.last_sent = {}

    def should_send(self, key, cooldown=300):

        now = time.time()

        last = self.last_sent.get(key, 0)

        if now - last < cooldown:
            return False

        self.last_sent[key] = now
        return True
