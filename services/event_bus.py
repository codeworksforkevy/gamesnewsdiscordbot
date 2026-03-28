"""
event_bus.py
────────────────────────────────────────────────────────────────
Simple async pub/sub event bus.

Improvement over original:
- Exceptions from subscriber callbacks are now logged individually
  instead of being silently swallowed by return_exceptions=True
"""

import asyncio
import logging
from collections import defaultdict
from typing import Callable, Any

logger = logging.getLogger("event_bus")


class EventBus:

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_name: str, callback: Callable) -> None:
        self._subscribers[event_name].append(callback)
        logger.debug(f"Subscribed to '{event_name}': {callback.__name__}")

    async def publish(self, event_name: str, payload: Any = None) -> None:
        callbacks = self._subscribers.get(event_name)
        if not callbacks:
            return

        results = await asyncio.gather(
            *(asyncio.create_task(cb(payload)) for cb in callbacks),
            return_exceptions=True,
        )

        for cb, result in zip(callbacks, results):
            if isinstance(result, Exception):
                logger.error(
                    f"EventBus subscriber error on '{event_name}'",
                    extra={"extra_data": {
                        "callback": cb.__name__,
                        "error":    str(result),
                    }},
                    exc_info=result,
                )
