import time

class CommandRegistry:
    def __init__(self):
        self.commands = {}
        self.errors = {}

    def register(self, name: str, module: str):
        self.commands[name] = {
            "module": module,
            "loaded_at": time.time(),
        }

    def register_error(self, module: str, error: Exception):
        self.errors[module] = str(error)

    def get_all(self):
        return self.commands

    def get_errors(self):
        return self.errors
