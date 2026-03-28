# services/http_client.py

import asyncio
import logging
import random

import aiohttp

logger = logging.getLogger("http")

MAX_ATTEMPTS = 5
BACKOFF_MAX  = 30


class HTTPClientManager:

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if not self._session:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)
            )
            logger.info("HTTP session başlatıldı")

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
            logger.info("HTTP session kapatıldı")

    @property
    def session(self) -> aiohttp.ClientSession | None:
        return self._session

    async def request(self, method: str, url: str, **kwargs):
        if not self._session:
            raise RuntimeError("HTTP session başlatılmamış — önce start() çağır")

        backoff = 1

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with self._session.request(method, url, **kwargs) as r:
                    if r.status == 429 or 500 <= r.status < 600:
                        wait = min(backoff + random.random(), BACKOFF_MAX)
                        logger.warning(
                            f"HTTP {r.status} — deneme {attempt}/{MAX_ATTEMPTS} "
                            f"— {wait:.1f}s — {url}"
                        )
                        await asyncio.sleep(wait)
                        backoff = min(backoff * 2, BACKOFF_MAX)
                        continue
                    try:
                        return await r.json()
                    except aiohttp.ContentTypeError:
                        return await r.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                wait = min(backoff + random.random(), BACKOFF_MAX)
                logger.warning(f"HTTP {e.__class__.__name__} — deneme {attempt} — {url}")
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, BACKOFF_MAX)

        raise RuntimeError(f"HTTP {MAX_ATTEMPTS} denemeden sonra başarısız: {url}")

    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self.request("POST", url, **kwargs)


http_client = HTTPClientManager()
