import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger("event-bus")


class EventBus:
    """
    Simple async event bus
    """

    def __init__(self):
        self._handlers = defaultdict(list)
        self._lock = asyncio.Lock()

    # =========================
    # SUBSCRIBE
    # =========================
    async def subscribe(self, event_name: str, handler):
        async with self._lock:
            self._handlers[event_name].append(handler)

        logger.info(
            "Handler subscribed",
            extra={"event": event_name, "handler": handler.__name__}
        )

    # =========================
    # PUBLISH
    # =========================
    async def publish(self, event_name: str, data=None):
        handlers = []

        async with self._lock:
            handlers = list(self._handlers.get(event_name, []))

        if not handlers:
            logger.debug(f"No handlers for event: {event_name}")
            return

        tasks = []

        for handler in handlers:
            tasks.append(self._safe_execute(handler, event_name, data))

        await asyncio.gather(*tasks, return_exceptions=True)

    # =========================
    # SAFE EXECUTION
    # =========================
    async def _safe_execute(self, handler, event_name, data):
        try:
            await handler(data)
        except Exception as e:
            logger.error(
                "Event handler failed",
                extra={
                    "event": event_name,
                    "handler": handler.__name__,
                    "error": str(e)
                }
            )


# Singleton instance
event_bus = EventBus()
