
import json
import time
import asyncio
from pathlib import Path

class CacheManager:

    def __init__(self, file_path):
        self.file = Path(file_path)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.cache = self._load()
        self.locks = {}

    def _load(self):
        if self.file.exists():
            return json.loads(self.file.read_text())
        return {}

    def save(self):
        self.file.write_text(json.dumps(self.cache, indent=2))

    def is_valid(self, key):
        entry = self.cache.get(key)
        return entry and entry["expires_at"] > time.time()

    def get(self, key):
        return self.cache.get(key, {}).get("data")

    def set(self, key, data, ttl):
        self.cache[key] = {
            "data": data,
            "expires_at": time.time() + ttl
        }
        self.save()

    def get_lock(self, key):
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        return self.locks[key]
