from aiohttp import web


async def create_eventsub_app(bot, app_state):
    app = web.Application()

    # health check
    async def health(request):
        return web.json_response({"status": "ok"})

    # Twitch EventSub webhook endpoint
    async def eventsub_handler(request):
        payload = await request.json()

        # Twitch verification challenge
        if "challenge" in payload:
            return web.Response(text=payload["challenge"])

        # Burada eventleri işle
        # (stream.online, stream.offline vs.)
        bot.logger.info(
            "EventSub event received",
            extra={"extra_data": payload}
        )

        return web.Response(text="OK")

    app.router.add_post("/eventsub", eventsub_handler)
    app.router.add_get("/", health)

    return app
