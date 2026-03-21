import asyncio
import logging

logger = logging.getLogger("state-manager")


class StateManager:
    """
    Central in-memory state store
    Thread-safe and async-safe
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._state = {
            "guilds": {},  # guild_id -> config/state
            "last_fetch": {},
            "running_tasks": set(),
        }

    # =========================
    # GUILD MANAGEMENT
    # =========================
    async def set_guild_state(self, guild_id: int, data: dict):
        async with self._lock:
            self._state["guilds"][guild_id] = data

    async def get_guild_state(self, guild_id: int):
        async with self._lock:
            return self._state["guilds"].get(guild_id)

    async def get_all_guilds(self):
        async with self._lock:
            return list(self._state["guilds"].keys())

    # =========================
    # FETCH TRACKING
    # =========================
    async def set_last_fetch(self, source: str, timestamp: float):
        async with self._lock:
            self._state["last_fetch"][source] = timestamp

    async def get_last_fetch(self, source: str):
        async with self._lock:
            return self._state["last_fetch"].get(source)

    # =========================
    # TASK TRACKING
    # =========================
    async def add_task(self, task_id: str):
        async with self._lock:
            self._state["running_tasks"].add(task_id)

    async def remove_task(self, task_id: str):
        async with self._lock:
            self._state["running_tasks"].discard(task_id)

    async def is_running(self, task_id: str):
        async with self._lock:
            return task_id in self._state["running_tasks"]

    # =========================
    # DEBUG
    # =========================
    async def snapshot(self):
        async with self._lock:
            return dict(self._state)


# Singleton instance (global usage)
state_manager = StateManager()
