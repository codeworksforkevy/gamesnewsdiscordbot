from services.event_router import (
    handle_stream_online,
    handle_stream_offline
)


async def route_event(bot, sub_type, event):

    if sub_type == "stream.online":
        await handle_stream_online(bot, event)

    elif sub_type == "stream.offline":
        await handle_stream_offline(bot, event)
