import asyncio


class Worker:
    def __init__(self, app_state):
        self.app_state = app_state
        self.running = False

    async def start(self):
        self.running = True

        while self.running:
            try:
                event = await self.app_state.next_event()

                await self.handle_event(event)

            except Exception as e:
                self.app_state.inc_metric("errors")

    async def handle_event(self, event: dict):
        event_name = event.get("event")
        payload = event.get("payload")

        if event_name == "free_game":
            await self.app_state.event_bus.publish("free_game", payload)

    def stop(self):
        self.running = False
