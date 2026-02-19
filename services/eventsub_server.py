from aiohttp import web
import json
import os
import hmac
import hashlib
import logging

from services.live_notifier import notify_live

logger = logging.getLogger("eventsub")

TWITCH_EVENTSUB_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET")

def verify_signature(request, body: bytes) -> bool:
    if not TWITCH_EVENTSUB_SECRET:
        logger.warning("TWITCH_EVENTSUB_SECRET missing")
        return False

    message_id = request.headers.get("Twitch-Eventsub-Message-Id", "")
    timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp", "")
    signature = request.headers.get("Twitch-Eventsub-Message-Signature", "")

    if not message_id or not timestamp or not signature:
        return False

    message = message_id + timestamp
    expected = hmac.new(
        TWITCH_EVENTSUB_SECRET.encode(),
        msg=message.encode() + body,
        digestmod=hashlib.sha256
    ).hexdigest()

    expected_signature = f"sha256={expected}"

    return hmac.compare_digest(expected_signature, signature)


async def create_eventsub_app(bot, channel_id):

    app = web.Application()

    async def webhook(request: web.Request):
        try:
            body = await request.read()

            # 🔐 Signature verify
            if not verify_signature(request, body):
                return web.Response(status=403)

            msg_type = request.headers.get("Twitch-Eventsub-Message-Type")

            data = json.loads(body.decode())

            # 🟣 Challenge verification
            if msg_type == "webhook_callback_verification":
                challenge = data.get("challenge")
                return web.Response(text=challenge)

            # 🟢 Live event
            if msg_type == "notification":
                event = data.get("event")
                if event:
                    await notify_live(bot, channel_id, event)

            return web.Response(text="ok")

        except Exception as e:
            logger.exception("EventSub error: %s", e)
            return web.Response(status=500)

    app.router.add_post("/twitch/eventsub", webhook)

    return app
