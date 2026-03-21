from aiohttp import web


async def handle_webhook(request):
    data = await request.json()

    bot = request.app["bot"]

    event = data.get("event")

    if event == "free_game":
        await bot.app_state.trigger_queue.put("free_game")

    return web.json_response({"status": "ok"})


async def create_webhook_app(bot, app_state):

    app = web.Application()
    app["bot"] = bot
    app["state"] = app_state

    app.router.add_post("/webhook", handle_webhook)

    return app
