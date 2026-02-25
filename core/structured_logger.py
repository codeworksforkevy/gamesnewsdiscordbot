
import logging
import json

class StructuredLogger:

    def __init__(self, name="twitch_intelligence"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def log(self, event_type, payload):
        entry = {
            "event": event_type,
            "payload": payload
        }
        self.logger.info(json.dumps(entry))
