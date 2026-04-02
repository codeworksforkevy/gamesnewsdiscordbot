import asyncio
import hashlib
import hmac
import json
import logging
import os

from aiohttp import web
from services.event_router import handle_stream_online, handle_stream_offline, handle_stream_update

logger = logging.getLogger("eventsub_server")

_bot_instance = None  # set in create_app

SECRET = os.getenv("TWITCH_EVENTSUB_SECRET", "supersecret")


async def handle_eventsub(request: web.Request):
    raw_body  = await request.read()
    signature = request.headers.get("Twitch-Eventsub-Message-Signature", "")
    msg_id    = request.headers.get("Twitch-Eventsub-Message-Id", "")
    msg_ts    = request.headers.get("Twitch-Eventsub-Message-Timestamp", "")
    msg_type  = request.headers.get("Twitch-Eventsub-Message-Type", "")

    logger.info(f"🔔 EventSub received — type={msg_type} size={len(raw_body)}b")

    # ── Signature verification ─────────────────────────────────
    hmac_message = msg_id.encode() + msg_ts.encode() + raw_body
    expected     = "sha256=" + hmac.new(
        SECRET.encode(), hmac_message, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        logger.error(
            f"🔴 Signature mismatch — check TWITCH_EVENTSUB_SECRET. "
            f"Expected prefix: {expected[:20]}..."
        )
        return web.Response(status=403)

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Failed to parse EventSub JSON body")
        return web.Response(status=400)

    # ── Challenge handshake ────────────────────────────────────
    if msg_type == "webhook_callback_verification":
        challenge = data.get("challenge", "")
        logger.info("✅ EventSub subscription verified by Twitch!")
        return web.Response(text=challenge, content_type="text/plain")

    # ── Revocation ─────────────────────────────────────────────
    if msg_type == "revocation":
        sub_type = data.get("subscription", {}).get("type", "unknown")
        logger.warning(f"⚠️ EventSub subscription revoked: {sub_type}")
        return web.Response(status=200)

    # ── Notification dispatch ──────────────────────────────────
    if msg_type == "notification":
        event    = data.get("event", {})
        sub_type = data.get("subscription", {}).get("type", "")
        login    = event.get("broadcaster_user_login", "unknown")

        logger.info(f"🟢 EventSub notification — type={sub_type} streamer={login}")

        # Get bot from module-level instance (set in create_app, always available)
        # Falls back to state_manager if somehow not set
        bot = _bot_instance
        if bot is None:
            try:
                from core.state_manager import state
                bot = state.get_bot()
            except Exception:
                pass

        if bot is None:
            logger.error(
                f"🔴 Bot not available — event for {login} dropped! "
                f"This happens if a webhook arrives before on_ready fires."
            )
            return web.Response(status=200)

        try:
            loop = asyncio.get_event_loop()

            if sub_type == "stream.online":
                logger.info(f"🚀 Stream ONLINE: {login}")
                loop.create_task(handle_stream_online(bot, event))
                logger.info(f"✅ Task created for handle_stream_online({login})")

            elif sub_type == "stream.offline":
                logger.info(f"⚫ Stream OFFLINE: {login}")
                loop.create_task(handle_stream_offline(bot, event))
                logger.info(f"✅ Task created for handle_stream_offline({login})")

            elif sub_type == "channel.update":
                logger.info(f"📡 Channel UPDATE: {login}")
                loop.create_task(handle_stream_update(bot, event))

            else:
                logger.warning(f"Unhandled EventSub type: {sub_type}")

        except Exception as e:
            logger.error(f"🔴 Dispatch error for {login}: {e}", exc_info=True)

        return web.Response(status=200)

    logger.warning(f"Unknown EventSub message type: {msg_type}")
    return web.Response(status=400)


async def create_app(bot, app_state):
    global _bot_instance
    _bot_instance = bot  # set immediately so webhooks arriving before on_ready work

    app = web.Application()
    app["bot"]       = bot
    app["app_state"] = app_state

    # Register BOTH paths — subscriptions may use either
    app.router.add_post("/eventsub",        handle_eventsub)
    app.router.add_post("/twitch/eventsub", handle_eventsub)

    logger.info("📡 EventSub server listening on /twitch/eventsub and /eventsub")
    return app
