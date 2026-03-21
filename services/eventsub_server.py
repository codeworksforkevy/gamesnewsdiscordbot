from aiohttp import web
import logging

logger = logging.getLogger("eventsub_server")

bot_instance = None


async def handle_eventsub(request: web.Request):

    body = await request.text()

    # Twitch challenge doğrulama
    if "challenge" in body:
        data = await request.json()
        return web.Response(text=data["challenge"])

    logger.info("Event received")

    # burada ileride stream online event işlenir
    return web.Response(status=200)


# 🔥 MAIN'İN BEKLEDİĞİ FONKSİYON
async def create_app(bot, app_state):

    global bot_instance
    bot_instance = bot

    app = web.Application()

    app.router.add_post("/eventsub", handle_eventsub)

    return app
