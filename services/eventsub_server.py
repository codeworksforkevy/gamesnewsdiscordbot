import asyncio
import hashlib
import hmac
import json
import logging
import os

from aiohttp import web
# DÜZELTME: import yolu güncellendi ve fonksiyon isimleri eşlendi
from events.stream_events import handle_stream_online, handle_stream_offline, handle_channel_update

logger = logging.getLogger("eventsub_server")

_bot_instance = None
SECRET = os.getenv("TWITCH_EVENTSUB_SECRET", "supersecret")

async def handle_eventsub(request: web.Request):
    raw_body  = await request.read()
    signature = request.headers.get("Twitch-Eventsub-Message-Signature", "")
    msg_id    = request.headers.get("Twitch-Eventsub-Message-Id", "")
    msg_ts    = request.headers.get("Twitch-Eventsub-Message-Timestamp", "")
    msg_type  = request.headers.get("Twitch-Eventsub-Message-Type", "")

    # Signature verification
    hmac_message = msg_id.encode() + msg_ts.encode() + raw_body
    expected     = "sha256=" + hmac.new(SECRET.encode(), hmac_message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature):
        return web.Response(status=403)

    data = json.loads(raw_body)
    
    # Twitch Challenge doğrulama
    if msg_type == "webhook_callback_verification":
        return web.Response(text=data["challenge"], content_type="text/plain")

    if msg_type == "notification":
        event    = data["event"]
        sub_type = data["subscription"]["type"]
        login    = event.get("broadcaster_user_login", "unknown")
        bot      = request.app["bot"]
        loop     = asyncio.get_event_loop()

        try:
            if sub_type == "stream.online":
                loop.create_task(handle_stream_online(bot, event))
            elif sub_type == "stream.offline":
                loop.create_task(handle_stream_offline(bot, event))
            elif sub_type == "channel.update":
                loop.create_task(handle_channel_update(bot, event)) # Fonksiyon ismi güncellendi
        except Exception as e:
            logger.error(f"Dispatch error for {login}: {e}")

    return web.Response(status=200)

async def create_app(bot, app_state):
    app = web.Application()
    app["bot"] = bot
    app["app_state"] = app_state
    app.router.add_post("/twitch/eventsub", handle_eventsub)
    return app
