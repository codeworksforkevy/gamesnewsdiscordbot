from fastapi import FastAPI, Request, Header, HTTPException
import hmac
import hashlib
import os
import time
import asyncio
import logging

from services.twitch_event_router import route_event

logger = logging.getLogger("eventsub-server")

app = FastAPI()

TWITCH_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET")
bot_instance = None  # main.py set eder

# Replay attack koruması (10 dakika)
MAX_REQUEST_AGE = 600


# ==================================================
# SIGNATURE VERIFICATION
# ==================================================

def verify_signature(message_id, timestamp, body, signature):

    if not TWITCH_SECRET:
        raise RuntimeError("TWITCH_EVENTSUB_SECRET missing")

    msg = message_id + timestamp + body

    expected = "sha256=" + hmac.new(
        TWITCH_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ==================================================
# TIMESTAMP VALIDATION (ANTI-REPLAY)
# ==================================================

def is_valid_timestamp(timestamp: str):

    try:
        ts = int(time.mktime(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return False

    return abs(time.time() - ts) < MAX_REQUEST_AGE


# ==================================================
# EVENTSUB ENDPOINT
# ==================================================

@app.post("/twitch/eventsub")
async def twitch_eventsub(
    request: Request,
    twitch_eventsub_message_type: str = Header(...),
    twitch_eventsub_message_id: str = Header(...),
    twitch_eventsub_message_timestamp: str = Header(...),
    twitch_eventsub_message_signature: str = Header(...),
):

    body = await request.body()
    body_str = body.decode()

    # 🔐 Timestamp check
    if not is_valid_timestamp(twitch_eventsub_message_timestamp):
        raise HTTPException(status_code=403, detail="Stale request")

    # 🔐 Signature check
    if not verify_signature(
        twitch_eventsub_message_id,
        twitch_eventsub_message_timestamp,
        body_str,
        twitch_eventsub_message_signature
    ):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()

    # 🔁 Webhook verification
    if twitch_eventsub_message_type == "webhook_callback_verification":
        return data["challenge"]

    # 🔔 Notification
    if twitch_eventsub_message_type == "notification":

        if not bot_instance:
            logger.error("Bot instance not set")
            return {"status": "bot_not_ready"}

        event = data.get("event", {})
        sub_type = data.get("subscription", {}).get("type")

        # ⚡ Fire and forget (Twitch retry önlemek için)
        asyncio.create_task(
            route_event(bot_instance, sub_type, event)
        )

    return {"status": "ok"}
