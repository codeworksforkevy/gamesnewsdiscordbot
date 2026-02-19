from aiohttp import web
import json
from services.live_notifier import notify_live
from services.twitch_api import get_app_token

async def create_eventsub_app(bot, channel_id):

    app = web.Application()

    async def webhook(request):
        body = await request.text()
        data = json.loads(body)

        # Twitch verification challenge
        if data.get("challenge"):
            return web.Response(text=data["challenge"])

        event = data.get("event")
        if event:
            await notify_live(bot, channel_id, event)

        return web.Response(text="ok")

    app.router.add_post("/twitch/eventsub", webhook)

    return app
