# services/http_utils.py

import asyncio
import logging

logger = logging.getLogger("http-utils")


async def fetch_with_retry(
    session,
    url,
    *,
    retries=3,
    timeout=10,
    backoff=2
):
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=timeout) as resp:
                resp.raise_for_status()
                return await resp.text()

        except Exception as e:
            if attempt == retries - 1:
                logger.warning(
                    "HTTP request failed",
                    extra={"url": url, "error": str(e)}
                )
                raise

            await asyncio.sleep(backoff ** attempt)
