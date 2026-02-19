import asyncio
import json
import os
from services.twitch_api import check_stream_live
from services.live_notifier import notify_live

DATA_FILE = "data/streamers.json"
live_state = {}

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

async def start_polling(bot, channel_id):

    await bot.wait_until_ready()

    while not bot.is_closed():

        streamers = load_streamers()

        for user_id, user_data in streamers.items():

            stream = await check_stream_live(user_id)

            was_live = live_state.get(user_id, False)
            is_live = stream is not None

            if is_live and not was_live:
                await notify_live(bot, channel_id, stream, user_data)

            live_state[user_id] = is_live

        await asyncio.sleep(60)
