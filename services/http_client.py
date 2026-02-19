
import aiohttp
import asyncio
import random
import logging

logger = logging.getLogger("http")

class HTTPClientManager:
    def __init__(self):
        self._session = None

    async def start(self):
        if not self._session:
            timeout = aiohttp.ClientTimeout(total=20)
            self._session = aiohttp.ClientSession(timeout=timeout)
            logger.info("HTTP session started")

    async def close(self):
        if self._session:
            await self._session.close()

    @property
    def session(self):
        return self._session

    async def request(self, method, url, **kwargs):
        backoff = 1
        for _ in range(5):
            async with self._session.request(method, url, **kwargs) as r:
                if r.status == 429 or 500 <= r.status < 600:
                    await asyncio.sleep(backoff + random.random())
                    backoff *= 2
                    continue
                return await r.json()
        raise RuntimeError("HTTP retries exhausted")

http_client = HTTPClientManager()
