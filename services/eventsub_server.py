import hashlib
import hmac
import json
import logging
import os
from aiohttp import web
from services.event_router import handle_stream_online, handle_stream_offline

logger = logging.getLogger("eventsub_server")

# Railway'deki TWITCH_EVENTSUB_SECRET ile birebir aynı olmalı
SECRET = os.getenv("TWITCH_EVENTSUB_SECRET", "supersecret")

async def handle_eventsub(request: web.Request):
    raw_body = await request.read()
    signature = request.headers.get("Twitch-Eventsub-Message-Signature")
    msg_id = request.headers.get("Twitch-Eventsub-Message-Id")
    msg_timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp")
    
    # 🕵️ Detaylı İmza Doğrulama
    hmac_message = msg_id.encode() + msg_timestamp.encode() + raw_body
    expected_signature = "sha256=" + hmac.new(
        SECRET.encode(), hmac_message, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature or ""):
        # Hata olduğunda gövdeden kullanıcıyı çekmeye çalışalım
        try:
            body = json.loads(raw_body)
            user = body.get("event", {}).get("broadcaster_user_name", "Unknown")
            logger.error(f"🔴 Signature mismatch for {user}! Check your SECRET. Expected: {expected_signature[:15]}...")
        except:
            logger.error("🔴 Bad signature on an unreadable payload.")
        return web.Response(status=403)

    data = json.loads(raw_body)

    # Webhook Doğrulama (Twitch kurulum anı)
    if request.headers.get("Twitch-Eventsub-Message-Type") == "webhook_callback_verification":
        logger.info("✅ EventSub subscription verified by Twitch!")
        return web.Response(text=data["challenge"])

    # Bildirim İşleme
    event = data.get("event", {})
    sub_type = data.get("subscription", {}).get("type")
    user_name = event.get("broadcaster_user_name", "Unknown")

    if sub_type == "stream.online":
        logger.info(f"🚀 Stream ONLINE: {user_name}")
        from core.state_manager import state
        bot = state.get_bot()
        if bot: bot.loop.create_task(handle_stream_online(bot, event))
        
    elif sub_type == "stream.offline":
        logger.info(f"💤 Stream OFFLINE: {user_name}")
        from core.state_manager import state
        bot = state.get_bot()
        if bot: bot.loop.create_task(handle_stream_offline(bot, event))

    return web.Response(status=204)

async def create_app(bot, app_state):
    app = web.Application()
    app.router.add_post("/twitch/eventsub", handle_eventsub)
    logger.info("📡 EventSub Server is listening for Twitch signals...")
    return app
