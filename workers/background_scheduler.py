
import asyncio

class BackgroundScheduler:

    def __init__(self, monitor, interval=300):
        self.monitor = monitor
        self.interval = interval
        self.task = None

    async def start(self):
        while True:
            await self.monitor.run_cycle()
            await asyncio.sleep(self.interval)
