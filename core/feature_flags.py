class FeatureFlags:
    def __init__(self, config: dict):
        self._flags = config

    def is_enabled(self, flag: str) -> bool:
        return self._flags.get(flag, False)

    def enable(self, flag: str):
        self._flags[flag] = True

    def disable(self, flag: str):
        self._flags[flag] = False
