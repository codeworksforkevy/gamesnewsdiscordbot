import asyncio
import time
import logging

logger = logging.getLogger("fetch.engine")


# ==================================================
# RATE LIMITER (token bucket)
# ==================================================
class RateLimiter:
    def __init__(self, rate_per_sec: float):
        self.rate = rate_per_sec
        self.tokens = rate_per_sec
        self.last = time.monotonic()

    async def acquire(self):
        while True:
            now = time.monotonic()
            elapsed = now - self.last
            self.last = now

            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)

            if self.tokens >= 1:
                self.tokens -= 1
                return

            await asyncio.sleep(0.1)


# ==================================================
# CIRCUIT BREAKER
# ==================================================
class CircuitBreaker:
    def __init__(self, failure_threshold=5, cooldown=30):
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.failures = 0
        self.open_until = 0

    def is_open(self):
        return time.time() < self.open_until

    def success(self):
        self.failures = 0

    def failure(self):
        self.failures += 1

        if self.failures >= self.failure_threshold:
            self.open_until = time.time() + self.cooldown
            logger.warning("Circuit breaker OPEN")


# ==================================================
# SAFE FETCH WRAPPER
# ==================================================
async def safe_fetch(name, fetch_func, rate_limiter, breaker, retries=3):

    if breaker.is_open():
        logger.warning(f"{name} skipped (circuit open)")
        return []

    for attempt in range(retries):
        try:
            await rate_limiter.acquire()

            result = await fetch_func()

            breaker.success()
            return result

        except Exception as e:
            breaker.failure()

            logger.warning(
                f"{name} failed (attempt {attempt+1})",
                extra={"extra_data": {"error": str(e)}}
            )

            await asyncio.sleep(2 ** attempt)

    return []
