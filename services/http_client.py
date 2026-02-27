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
            self._session = None
            logger.info("HTTP session closed")

    @property
    def session(self):
        return self._session

    async def request(self, method, url, **kwargs):

        if not self._session:
            raise RuntimeError("HTTP session not started")

        backoff = 1

        for attempt in range(5):

            try:
                async with self._session.request(method, url, **kwargs) as r:

                    if r.status == 429 or 500 <= r.status < 600:
                        logger.warning(
                            "HTTP %s retry (%s) for %s",
                            r.status,
                            attempt + 1,
                            url
                        )
                        await asyncio.sleep(backoff + random.random())
                        backoff *= 2
                        continue

                    # Try JSON first
                    try:
                        return await r.json()
                    except aiohttp.ContentTypeError:
                        text = await r.text()
                        logger.warning("Non-JSON response from %s", url)
                        return text

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    "HTTP exception (%s) retry (%s) for %s",
                    e,
                    attempt + 1,
                    url
                )
                await asyncio.sleep(backoff + random.random())
                backoff *= 2

        raise RuntimeError(f"HTTP retries exhausted for {url}")


http_client = HTTPClientManager()
