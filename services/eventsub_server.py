import hashlib
import hmac
import json
import logging
import os

from aiohttp import web

from services.event_router import handle_stream_online, handle_stream_offline

logger = logging.getLogger("eventsub_server")

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────

EVENTSUB_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET", "supersecret")

MSG_ID_HEADER        = "Twitch-Eventsub-Message-Id"
MSG_TIMESTAMP_HEADER = "Twitch-Eventsub-Message-Timestamp"
MSG_SIGNATURE_HEADER = "Twitch-Eventsub-Message-Signature"
MSG_TYPE_HEADER      = "Twitch-Eventsub-Message-Type"

MSG_TYPE_VERIFICATION = "webhook_callback_verification"
MSG_TYPE_NOTIFICATION = "notification"
MSG_TYPE_REVOCATION   = "revocation"

_bot_instance = None


# ──────────────────────────────────────────────────────────────
# SIGNATURE VERIFICATION
# ──────────────────────────────────────────────────────────────

def _verify_signature(request: web.Request, raw_body: bytes) -> bool:
    """
    Verifies the Twitch HMAC-SHA256 signature.
    Returns True only when the request is genuine.
    """
    msg_id        = request.headers.get(MSG_ID_HEADER, "")
    msg_timestamp = request.headers.get(MSG_TIMESTAMP_HEADER, "")
    msg_signature = request.headers.get(MSG_SIGNATURE_HEADER, "")

    hmac_message = (msg_id + msg_timestamp).encode() + raw_body
    digest = hmac.new(
        EVENTSUB_SECRET.encode(),
        hmac_message,
        hashlib.sha256
    ).hexdigest()

    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, msg_signature)


# ──────────────────────────────────────────────────────────────
# REQUEST HANDLER
# ──────────────────────────────────────────────────────────────

async def handle_eventsub(request: web.Request):

    raw_body = await request.read()

    logger.info(
        f"🔔 EventSub request received — "
        f"type={request.headers.get(MSG_TYPE_HEADER, 'MISSING')} "
        f"size={len(raw_body)}b "
        f"from={request.remote}"
    )

    # ── Signature check ────────────────────────────────────────
    if not _verify_signature(request, raw_body):
        logger.warning(
            f"🔴 Rejected EventSub request — bad signature. "
            f"Check TWITCH_EVENTSUB_SECRET matches what was used during subscription."
        )
        return web.Response(status=403, text="Forbidden")

    msg_type = request.headers.get(MSG_TYPE_HEADER, "")

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Failed to parse EventSub JSON body")
        return web.Response(status=400, text="Bad Request")

    # ── Challenge handshake ────────────────────────────────────
    if msg_type == MSG_TYPE_VERIFICATION:
        challenge = data.get("challenge", "")
        logger.info("EventSub challenge verified")
        return web.Response(text=challenge, content_type="text/plain")

    # ── Revocation notice ──────────────────────────────────────
    if msg_type == MSG_TYPE_REVOCATION:
        sub_type = data.get("subscription", {}).get("type", "unknown")
        logger.warning(f"EventSub subscription revoked: {sub_type}")
        return web.Response(status=200)

    # ── Live event dispatch ────────────────────────────────────
    if msg_type == MSG_TYPE_NOTIFICATION:
        event    = data.get("event", {})
        sub_type = data.get("subscription", {}).get("type", "")
        login    = event.get("broadcaster_user_login", "unknown")

        logger.info(
            f"🟢 EventSub notification — "
            f"type={sub_type} streamer={login}"
        )

        if sub_type == "stream.online":
            if _bot_instance is None:
                logger.error("🔴 _bot_instance is None — event dropped!")
            else:
                logger.info(f"🚀 Dispatching handle_stream_online for {login}")
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    loop.create_task(handle_stream_online(_bot_instance, event))
                    logger.info(f"✅ Task created for handle_stream_online({login})")
                except Exception as e:
                    logger.error(f"🔴 Failed to create task for {login}: {e}")

        elif sub_type == "stream.offline":
            if _bot_instance is None:
                logger.error("🔴 _bot_instance is None — event dropped!")
            else:
                logger.info(f"⚫ Dispatching handle_stream_offline for {login}")
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    loop.create_task(handle_stream_offline(_bot_instance, event))
                    logger.info(f"✅ Task created for handle_stream_offline({login})")
                except Exception as e:
                    logger.error(f"🔴 Failed to create task for {login}: {e}")

        else:
            logger.warning(f"Unhandled EventSub type: {sub_type}")

        return web.Response(status=200)

    logger.warning(f"Unknown EventSub message type: {msg_type}")
    return web.Response(status=400)


# ──────────────────────────────────────────────────────────────
# APP FACTORY
# ──────────────────────────────────────────────────────────────

async def create_app(bot, app_state):
    global _bot_instance
    _bot_instance = bot

    app = web.Application()
    app["bot"] = bot
    app["app_state"] = app_state

    app.router.add_post("/eventsub", handle_eventsub)
    app.router.add_post("/twitch/eventsub", handle_eventsub)  # alternate path

    logger.info("EventSub server ready")
    return app
