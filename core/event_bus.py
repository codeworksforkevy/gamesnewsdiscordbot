# core/event_bus.py

import asyncio
from collections import defaultdict
from typing import Callable, Any


class EventBus:
    def __init__(self):
        self._listeners = defaultdict(list)

    def subscribe(self, event_name: str, handler: Callable):
        self._listeners[event_name].append(handler)

    async def emit(self, event_name: str, *args, **kwargs):
        handlers = self._listeners.get(event_name, [])

        tasks = []
        for handler in handlers:
            tasks.append(asyncio.create_task(handler(*args, **kwargs)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# global bus
event_bus = EventBus()
