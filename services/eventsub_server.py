from fastapi import FastAPI, Request, Header, HTTPException
import hmac
import hashlib
import os
import time
import asyncio
import logging
from datetime import datetime, timezone

from services.twitch_event_router import route_event

logger = logging.getLogger("eventsub-server")

app = FastAPI()

# ✅ FIX: correct env name
TWITCH_SECRET = os.getenv("TWITCH_WEBHOOK_SECRET")

bot_instance = None  # set in main.py

# Replay protection (seconds)
MAX_REQUEST_AGE = 600

# Simple in-memory deduplication (production: Redis önerilir)
seen_message_ids = set()


# ==================================================
# SIGNATURE VERIFICATION
# ==================================================

def verify_signature(message_id, timestamp, body, signature):

    if not TWITCH_SECRET:
        raise RuntimeError("TWITCH_WEBHOOK_SECRET missing")

    msg = message_id + timestamp + body

    expected = "sha256=" + hmac.new(
        TWITCH_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ==================================================
# TIMESTAMP VALIDATION (IMPROVED)
# ==================================================

def is_valid_timestamp(timestamp: str):

    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
    except Exception:
        return False

    delta = abs((now - ts).total_seconds())

    return delta < MAX_REQUEST_AGE


# ==================================================
# EVENTSUB ENDPOINT
# ==================================================

@app.post("/eventsub")
async def twitch_eventsub(
    request: Request,
    twitch_eventsub_message_type: str = Header(...),
    twitch_eventsub_message_id: str = Header(...),
    twitch_eventsub_message_timestamp: str = Header(...),
    twitch_eventsub_message_signature: str = Header(...),
):

    # ⚠️ Duplicate protection
    if twitch_eventsub_message_id in seen_message_ids:
        return {"status": "duplicate_ignored"}

    seen_message_ids.add(twitch_eventsub_message_id)

    # Keep memory bounded
    if len(seen_message_ids) > 10000:
        seen_message_ids.clear()

    body_bytes = await request.body()
    body_str = body_bytes.decode()

    # 🔐 Timestamp validation
    if not is_valid_timestamp(twitch_eventsub_message_timestamp):
        raise HTTPException(status_code=403, detail="Stale request")

    # 🔐 Signature validation
    if not verify_signature(
        twitch_eventsub_message_id,
        twitch_eventsub_message_timestamp,
        body_str,
        twitch_eventsub_message_signature
    ):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse JSON (safe)
    data = await request.json()

    # ==================================================
    # CHALLENGE (Webhook verification)
    # ==================================================

    if twitch_eventsub_message_type == "webhook_callback_verification":
        return data["challenge"]

    # ==================================================
    # NOTIFICATION
    # ==================================================

    if twitch_eventsub_message_type == "notification":

        if not bot_instance:
            logger.error("Bot instance not set")
            return {"status": "bot_not_ready"}

        event = data.get("event", {})
        sub_type = data.get("subscription", {}).get("type")

        # Fire-and-forget
        asyncio.create_task(
            route_event(bot_instance, sub_type, event)
        )

    return {"status": "ok"}
