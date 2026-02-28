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

# In-memory idempotency cache (simple, per-instance)
_recent_messages = set()
_MAX_CACHE_SIZE = 1000


# ==================================================
# SIGNATURE VERIFICATION
# ==================================================

def verify_signature(request: web.Request, body: bytes) -> bool:

    if not TWITCH_EVENTSUB_SECRET:
        logger.error("TWITCH_EVENTSUB_SECRET missing.")
        return False

    message_id = request.headers.get("Twitch-Eventsub-Message-Id")
    timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp")
    signature = request.headers.get("Twitch-Eventsub-Message-Signature")

    if not message_id or not timestamp or not signature:
        logger.warning("Missing Twitch signature headers.")
        return False

    # Replay window (10 min)
    try:
        msg_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        if abs((now - msg_time).total_seconds()) > 600:
            logger.warning("Message outside allowed time window.")
            return False

    except Exception:
        logger.warning("Invalid timestamp format.")
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

async def create_eventsub_app(bot, app_state):

    app = web.Application()

    async def webhook(request: web.Request):

        try:
            body = await request.read()

            # 1️⃣ Signature verify
            if not verify_signature(request, body):
                return web.Response(status=403)

            message_id = request.headers.get("Twitch-Eventsub-Message-Id")

            # 2️⃣ Idempotency protection
            if message_id in _recent_messages:
                logger.info("Duplicate EventSub message ignored.")
                return web.Response(text="duplicate")

            _recent_messages.add(message_id)

            if len(_recent_messages) > _MAX_CACHE_SIZE:
                _recent_messages.pop()

            msg_type = request.headers.get("Twitch-Eventsub-Message-Type")

            try:
                data = json.loads(body.decode())
            except json.JSONDecodeError:
                logger.warning("Invalid JSON payload.")
                return web.Response(text="invalid-json")

            # ----------------------------------------
            # CHALLENGE
            # ----------------------------------------
            if msg_type == "webhook_callback_verification":
                challenge = data.get("challenge")
                logger.info("EventSub challenge verified.")
                return web.Response(text=challenge)

            # ----------------------------------------
            # NOTIFICATION
            # ----------------------------------------
            if msg_type == "notification":

                # DB readiness check
                if not app_state.db:
                    logger.error("DB not ready.")
                    return web.Response(text="db-not-ready")

                event = data.get("event", {})
                subscription = data.get("subscription", {})
                sub_type = subscription.get("type")

                if sub_type == "stream.online":

                    logger.info(
                        "stream.online: %s",
                        event.get("broadcaster_user_name")
                    )

                    await notify_live(bot, app_state, event)

                elif sub_type == "stream.offline":

                    logger.info(
                        "stream.offline: %s",
                        event.get("broadcaster_user_name")
                    )

                    await mark_offline(app_state, event)

                return web.Response(text="ok")

            # ----------------------------------------
            # REVOCATION
            # ----------------------------------------
            if msg_type == "revocation":

                sub = data.get("subscription", {})
                logger.warning(
                    "Subscription revoked: %s (%s)",
                    sub.get("type"),
                    sub.get("condition", {}).get("broadcaster_user_id")
                )

                return web.Response(text="revoked")

            return web.Response(text="ignored")

        except Exception as e:
            # 🔥 Never let Twitch retry storm
            logger.exception("Unhandled EventSub error: %s", e)
            return web.Response(text="error-handled")

    app.router.add_post("/twitch/eventsub", webhook)

    return app
