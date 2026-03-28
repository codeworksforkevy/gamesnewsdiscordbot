# services/twitch_event_router.py
#
# EventSub webhook'larından gelen olayları doğru handler'a yönlendirir.

import logging

from services.event_router import handle_stream_online, handle_stream_offline

logger = logging.getLogger("twitch-event-router")


async def route_event(bot, sub_type: str, event: dict) -> None:
    if sub_type == "stream.online":
        await handle_stream_online(bot, event)
    elif sub_type == "stream.offline":
        await handle_stream_offline(bot, event)
    else:
        logger.warning(f"Bilinmeyen EventSub tipi: {sub_type}")
