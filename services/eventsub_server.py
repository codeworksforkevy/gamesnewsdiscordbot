from aiohttp import web
import json
import os
import hmac
import hashlib
import logging
from datetime import datetime, timezone

from services.live_notifier import notify_live, mark_offline

logger = logging.getLogger("eventsub")

TWITCH_EVENTSUB_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET")


# ==================================================
# SIGNATURE VERIFICATION
# ==================================================

def verify_signature(request: web.Request, body: bytes) -> bool:
    """
    Verifies Twitch EventSub HMAC signature.
    """

    if not TWITCH_EVENTSUB_SECRET:
        logger.error("TWITCH_EVENTSUB_SECRET is not set.")
        return False

    message_id = request.headers.get("Twitch-Eventsub-Message-Id")
    timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp")
    signature = request.headers.get("Twitch-Eventsub-Message-Signature")

    if not message_id or not timestamp or not signature:
        logger.warning("Missing Twitch signature headers.")
        return False

    # Optional: prevent replay attacks (10 min window)
    try:
        msg_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        if abs((now - msg_time).total_seconds()) > 600:
            logger.warning("Twitch message timestamp too old (possible replay).")
            return False

    except Exception:
        logger.warning("Invalid Twitch timestamp format.")
        return False

    message = message_id + timestamp
    computed_hash = hmac.new(
        TWITCH_EVENTSUB_SECRET.encode(),
        msg=message.encode() + body,
        digestmod=hashlib.sha256
    ).hexdigest()

    expected_signature = f"sha256={computed_hash}"

    return hmac.compare_digest(expected_signature, signature)


# ==================================================
# EVENTSUB APP FACTORY
# ==================================================

async def create_eventsub_app(bot):

    app = web.Application()

    async def webhook(request: web.Request):

        try:
            body = await request.read()

            # Verify HMAC
            if not verify_signature(request, body):
                logger.warning("Signature verification failed.")
                return web.Response(status=403)

            msg_type = request.headers.get("Twitch-Eventsub-Message-Type")
            data = json.loads(body.decode())

            # ----------------------------------------
            # CHALLENGE (Initial verification)
            # ----------------------------------------
            if msg_type == "webhook_callback_verification":
                challenge = data.get("challenge")
                logger.info("EventSub challenge verified.")
                return web.Response(text=challenge)

            # ----------------------------------------
            # NOTIFICATION
            # ----------------------------------------
            if msg_type == "notification":

                event = data.get("event", {})
                subscription = data.get("subscription", {})
                sub_type = subscription.get("type")

                if sub_type == "stream.online":
                    logger.info("Received stream.online for %s",
                                event.get("broadcaster_user_name"))

                    await notify_live(bot, None, event)

                elif sub_type == "stream.offline":
                    logger.info("Received stream.offline for %s",
                                event.get("broadcaster_user_name"))

                    await mark_offline(event)

                return web.Response(text="ok")

            # ----------------------------------------
            # REVOCATION / UNKNOWN
            # ----------------------------------------
            if msg_type == "revocation":
                logger.warning("EventSub subscription revoked.")
                return web.Response(text="revoked")

            return web.Response(text="ignored")

        except Exception as e:
            logger.exception("EventSub error: %s", e)
            return web.Response(status=500)

    app.router.add_post("/twitch/eventsub", webhook)

    return app
