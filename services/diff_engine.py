# services/diff_engine.py

import logging
import json

logger = logging.getLogger("diff-engine")


async def get_new_items(redis, key, items):
    """
    Compare current items with previous cache.
    Return ONLY new ones.
    """

    if not items:
        return []

    current_ids = {item["id"] for item in items if item.get("id")}

    old_ids = set()

    # -------------------------
    # LOAD OLD
    # -------------------------
    if redis:
        try:
            data = await redis.get(key)
            if data:
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                old_ids = set(json.loads(data))
        except Exception:
            logger.warning("Diff load failed")

    # -------------------------
    # DIFF
    # -------------------------
    new_ids = current_ids - old_ids

    new_items = [item for item in items if item["id"] in new_ids]

    # -------------------------
    # SAVE NEW STATE
    # -------------------------
    if redis:
        try:
            await redis.set(key, json.dumps(list(current_ids)), ex=3600)
        except Exception:
            logger.warning("Diff save failed")

    return new_items
