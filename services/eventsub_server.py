from aiohttp import web
import json
import os
import hmac
import hashlib
import logging

from services.live_notifier import notify_live
from commands.live_commands import load_streamers

logger = logging.getLogger("eventsub")

TWITCH_EVENTSUB_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET")


# ==================================================
# SIGNATURE VERIFY
# ==================================================

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


# ==================================================
# CREATE APP
# ==================================================

async def create_eventsub_app(bot):

    app = web.Application()

    async def webhook(request: web.Request):
        try:
            body = await request.read()

            if not verify_signature(request, body):
                return web.Response(status=403)

            msg_type = request.headers.get("Twitch-Eventsub-Message-Type")
            data = json.loads(body.decode())

            # 🟣 Challenge
            if msg_type == "webhook_callback_verification":
                challenge = data.get("challenge")
                return web.Response(text=challenge)

            # 🟢 Notification
            if msg_type == "notification":

                event = data.get("event")
                if not event:
                    return web.Response(text="no event")

                twitch_user_id = event.get("broadcaster_user_id")

                if not twitch_user_id:
                    return web.Response(text="no broadcaster id")

                registry = load_streamers()

                # 🔥 Multi guild tarama
                for guild_id, guild_data in registry.get("guilds", {}).items():

                    streamers = guild_data.get("streamers", {})

                    if twitch_user_id in streamers:

                        info = streamers[twitch_user_id]
                        channel_id = info.get("channel_id")

                        if channel_id:
                            await notify_live(bot, channel_id, event)

                return web.Response(text="ok")

            return web.Response(text="ignored")

        except Exception as e:
            logger.exception("EventSub error: %s", e)
            return web.Response(status=500)

    app.router.add_post("/twitch/eventsub", webhook)

    return app
