import asyncio
import time


class CircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.failure_count = 0
        self.last_failure_time = None
        self.open = False

    async def call(self, func, *args, **kwargs):
        if self.open:
            if time.time() - self.last_failure_time < self.recovery_timeout:
                raise Exception("Circuit breaker open")
            else:
                self.open = False
                self.failure_count = 0

        try:
            result = await func(*args, **kwargs)

            self.failure_count = 0
            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.open = True

            raise e


async def retry(func, retries=3, delay=1):
    for attempt in range(retries):
        try:
            return await func()
        except Exception:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(delay * (2 ** attempt))
