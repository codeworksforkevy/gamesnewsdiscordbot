import json
import logging

logger = logging.getLogger("stream-tracker")


async def check_stream_changes(redis, meta, login: str):

    key = f"stream:last_notified:{login}"

    last = await redis.get(key)

    if not last:
        # ilk kez → kaydet ama notify etme
        await redis.set(key, json.dumps(meta))
        return None

    last_data = json.loads(last)

    changes = {}

    if last_data.get("title") != meta.get("title"):
        changes["title"] = (last_data.get("title"), meta.get("title"))

    if last_data.get("game") != meta.get("game"):
        changes["game"] = (last_data.get("game"), meta.get("game"))

    # değişiklik yok
    if not changes:
        return None

    # yeni state kaydet
    await redis.set(key, json.dumps(meta))

    return changes
