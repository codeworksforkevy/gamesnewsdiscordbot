import asyncio
import logging
import random
import time

logger = logging.getLogger("http-utils")


# ==================================================
# CIRCUIT BREAKER STATE
# ==================================================
class CircuitBreaker:
    def __init__(self, failure_threshold=5, cooldown=30):
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown

        self.failures = 0
        self.last_failure_time = None
        self.open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()

        if self.failures >= self.failure_threshold:
            self.open = True

    def record_success(self):
        self.failures = 0
        self.open = False

    def can_execute(self):
        if not self.open:
            return True

        # cooldown check
        if self.last_failure_time and (time.time() - self.last_failure_time) > self.cooldown:
            self.open = False
            self.failures = 0
            return True

        return False


# global breakers per host
_circuit_breakers = {}


def get_breaker(host):
    if host not in _circuit_breakers:
        _circuit_breakers[host] = CircuitBreaker()
    return _circuit_breakers[host]


# ==================================================
# FETCH WITH RETRY (PRODUCTION GRADE)
# ==================================================
async def fetch_with_retry(
    session,
    url,
    *,
    retries=3,
    timeout=10,
    total_timeout=30,
    backoff_base=1.5
):
    """
    Robust HTTP fetch with:
    - retry
    - exponential backoff + jitter
    - circuit breaker
    - total timeout protection
    """

    host = url.split("/")[2] if "://" in url else url
    breaker = get_breaker(host)

    if not breaker.can_execute():
        raise Exception(f"Circuit breaker open for {host}")

    start_time = time.time()

    for attempt in range(retries):
        try:
            # global timeout guard
            if (time.time() - start_time) > total_timeout:
                raise TimeoutError("Total request timeout exceeded")

            async with session.get(url, timeout=timeout) as resp:

                # handle HTTP status codes
                if resp.status >= 400:
                    # retry only on server errors
                    if resp.status >= 500:
                        raise Exception(f"Server error: {resp.status}")

                    # client error → no retry
                    text = await resp.text()
                    logger.warning(
                        "Client error",
                        extra={"url": url, "status": resp.status, "body": text[:200]}
                    )
                    raise Exception(f"Client error: {resp.status}")

                breaker.record_success()
                return await resp.text()

        except Exception as e:
            breaker.record_failure()

            is_last = attempt == retries - 1

            logger.warning(
                "HTTP attempt failed",
                extra={
                    "url": url,
                    "attempt": attempt + 1,
                    "error": str(e)
                }
            )

            if is_last:
                logger.error(
                    "HTTP request failed permanently",
                    extra={"url": url, "error": str(e)}
                )
                raise

            # exponential backoff + jitter
            delay = (backoff_base ** attempt) + random.uniform(0, 0.5)

            await asyncio.sleep(delay)


# ==================================================
# OPTIONAL: JSON FETCH HELPER
# ==================================================
async def fetch_json(session, url, **kwargs):
    """
    Convenience wrapper for JSON APIs
    """

    text = await fetch_with_retry(session, url, **kwargs)

    try:
        return text, None
    except Exception as e:
        return None, e
