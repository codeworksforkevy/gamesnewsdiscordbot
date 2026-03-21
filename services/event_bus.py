import asyncio
from collections import defaultdict


class EventBus:
    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_name: str, callback):
        self._subscribers[event_name].append(callback)

    async def publish(self, event_name: str, payload=None):
        if event_name not in self._subscribers:
            return

        tasks = []

        for callback in self._subscribers[event_name]:
            tasks.append(asyncio.create_task(callback(payload)))

        await asyncio.gather(*tasks, return_exceptions=True)
