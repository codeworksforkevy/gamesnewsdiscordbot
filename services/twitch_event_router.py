import logging

from services.live_notifier import notify_live, mark_offline
from services.live_notifier import handle_stream_update

logger = logging.getLogger("twitch-router")


async def route_event(bot, event_type: str, event: dict):
    """
    Routes Twitch EventSub events to handlers.
    """

    try:
        if event_type == "stream.online":
            await notify_live(bot, None, event)

        elif event_type == "stream.offline":
            await mark_offline(bot, event)

        elif event_type == "channel.update":
            await handle_stream_update(bot, event)

        else:
            logger.info(
                "Unhandled Twitch event",
                extra={"extra_data": {"type": event_type}}
            )

    except Exception as e:
        logger.error(
            "Event routing failed",
            extra={"extra_data": {"error": str(e)}}
        )
