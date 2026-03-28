"""
core/event_bus.py
────────────────────────────────────────────────────────────────
Async pub/sub event bus — the central nervous system of the bot.

Fixes vs original:
- Two different method names existed across the codebase:
    event_bus.emit(...)    (this file)
    event_bus.publish(...) (event_bus__1_.py from previous batch)
  Both are now supported as aliases so nothing breaks regardless of
  which name callers use.
- Exceptions from handlers were silently swallowed by return_exceptions=True.
  Each handler's error is now logged individually with its name and the
  event that triggered it.
- No way to unsubscribe — added unsubscribe() for cleanup in tests and
  cog teardown.
- `Any` was imported but never used — removed.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger("event-bus")


class EventBus:

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    # ──────────────────────────────────────────────────────────
    # SUBSCRIBE / UNSUBSCRIBE
    # ──────────────────────────────────────────────────────────

    def subscribe(self, event_name: str, handler: Callable) -> None:
        self._listeners[event_name].append(handler)
        logger.debug(
            "EventBus subscribe",
            extra={"extra_data": {
                "event":   event_name,
                "handler": getattr(handler, "__name__", repr(handler)),
            }},
        )

    def unsubscribe(self, event_name: str, handler: Callable) -> bool:
        """
        Removes a handler from an event.
        Returns True if the handler was found and removed, False otherwise.
        """
        listeners = self._listeners.get(event_name, [])
        try:
            listeners.remove(handler)
            return True
        except ValueError:
            return False

    # ──────────────────────────────────────────────────────────
    # PUBLISH  (also aliased as emit for backward compat)
    # ──────────────────────────────────────────────────────────

    async def publish(self, event_name: str, payload=None) -> None:
        handlers = list(self._listeners.get(event_name, []))
        if not handlers:
            return

        results = await asyncio.gather(
            *(asyncio.create_task(h(payload)) for h in handlers),
            return_exceptions=True,
        )

        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                logger.error(
                    "EventBus handler raised an exception",
                    extra={"extra_data": {
                        "event":   event_name,
                        "handler": getattr(handler, "__name__", repr(handler)),
                        "error":   str(result),
                    }},
                    exc_info=result,
                )

    async def emit(self, event_name: str, payload=None) -> None:
        """Alias for publish() — supports legacy callers."""
        await self.publish(event_name, payload)

    # ──────────────────────────────────────────────────────────
    # INTROSPECTION
    # ──────────────────────────────────────────────────────────

    def listener_count(self, event_name: str) -> int:
        return len(self._listeners.get(event_name, []))

    def all_events(self) -> list[str]:
        return list(self._listeners.keys())


# ──────────────────────────────────────────────────────────────
# GLOBAL SINGLETON
# ──────────────────────────────────────────────────────────────

event_bus = EventBus()
