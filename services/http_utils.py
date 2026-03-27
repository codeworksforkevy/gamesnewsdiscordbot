# services/http_utils.py
#
# FIX: session.get(url, timeout=10) passed a plain integer to aiohttp
# which expects aiohttp.ClientTimeout — this caused a TypeError on every
# HTTP request, logged as "HTTP attempt failed" 3 times then permanently.

import asyncio
import logging
import random
import time

from aiohttp import ClientTimeout

logger = logging.getLogger("http-utils")


# ==================================================
# CIRCUIT BREAKER
# ==================================================

class CircuitBreaker:
    def __init__(self, failure_threshold=5, cooldown=30):
        self.failure_threshold = failure_threshold
        self.cooldown          = cooldown
        self.failures          = 0
        self.last_failure_time = None
        self.open              = False

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.open = True

    def record_success(self):
        self.failures = 0
        self.open     = False

    def can_execute(self):
        if not self.open:
            return True
        if (self.last_failure_time and
                (time.time() - self.last_failure_time) > self.cooldown):
            self.open     = False
            self.failures = 0
            return True
        return False


_circuit_breakers: dict = {}


def get_breaker(host: str) -> CircuitBreaker:
    if host not in _circuit_breakers:
        _circuit_breakers[host] = CircuitBreaker()
    return _circuit_breakers[host]


# ==================================================
# FETCH WITH RETRY
# ==================================================

async def fetch_with_retry(
    session,
    url: str,
    *,
    retries: int       = 3,
    timeout: int       = 10,
    total_timeout: int = 30,
    backoff_base: float = 1.5,
    headers: dict      = None,
) -> str:
    """
    Robust HTTP GET with retry, exponential backoff, and circuit breaker.

    FIX: wraps timeout in aiohttp.ClientTimeout so aiohttp accepts it.
    Previously passing timeout=10 (plain int) caused TypeError on every
    single request, making Epic/GOG/Steam fetches permanently fail.
    """
    host    = url.split("/")[2] if "://" in url else url
    breaker = get_breaker(host)

    if not breaker.can_execute():
        raise Exception(f"Circuit breaker open for {host}")

    # Build proper aiohttp timeout object once
    aio_timeout = ClientTimeout(total=timeout)
    start_time  = time.time()

    for attempt in range(retries):
        try:
            if (time.time() - start_time) > total_timeout:
                raise TimeoutError("Total request timeout exceeded")

            kwargs = {"timeout": aio_timeout}
            if headers:
                kwargs["headers"] = headers

            async with session.get(url, **kwargs) as resp:

                if resp.status >= 500:
                    raise Exception(f"Server error: {resp.status}")

                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning(
                        f"Client error {resp.status} for {url}: {text[:200]}"
                    )
                    raise Exception(f"Client error: {resp.status}")

                breaker.record_success()
                return await resp.text()

        except Exception as e:
            breaker.record_failure()
            is_last = attempt == retries - 1

            logger.warning(
                f"HTTP attempt {attempt + 1}/{retries} failed for {url}: {e}"
            )

            if is_last:
                logger.error(
                    f"HTTP request failed permanently: {url} — {e}"
                )
                raise

            delay = (backoff_base ** attempt) + random.uniform(0, 0.5)
            await asyncio.sleep(delay)


# ==================================================
# JSON CONVENIENCE WRAPPER
# ==================================================

async def fetch_json(session, url: str, **kwargs):
    """Fetch URL and return (parsed_json, error)."""
    import json as _json
    try:
        text = await fetch_with_retry(session, url, **kwargs)
        return _json.loads(text), None
    except Exception as e:
        return None, e
