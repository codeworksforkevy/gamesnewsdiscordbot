import logging
from aiohttp import web

logger = logging.getLogger("eventsub")

def create_eventsub_app(bot):

    app = web.Application()

    async def handle_eventsub(request):
        headers = request.headers
        body = await request.json()

        msg_type = headers.get("Twitch-Eventsub-Message-Type")

        if msg_type == "webhook_callback_verification":
            logger.info("Webhook verified.")
            return web.Response(text=body["challenge"])

        if msg_type == "notification":
            logger.info("Live event received: %s", body)

        return web.Response(status=200)

    app.router.add_post("/twitch/eventsub", handle_eventsub)

    return app

