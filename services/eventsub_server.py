from fastapi import FastAPI, Request, Header, HTTPException
import hmac
import hashlib
import os

from services.twitch_event_router import route_event

app = FastAPI()

TWITCH_SECRET = os.getenv("TWITCH_SECRET")
bot_instance = None  # main.py'de set edilecek


# ==================================================
# SIGNATURE VERIFICATION
# ==================================================

def verify_signature(message_id, timestamp, body, signature):
    msg = message_id + timestamp + body

    expected = 'sha256=' + hmac.new(
        TWITCH_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ==================================================
# EVENTSUB ENDPOINT
# ==================================================

@app.post("/twitch/eventsub")
async def twitch_eventsub(
    request: Request,
    twitch_eventsub_message_type: str = Header(None),
    twitch_eventsub_message_id: str = Header(None),
    twitch_eventsub_message_timestamp: str = Header(None),
    twitch_eventsub_message_signature: str = Header(None),
):
    body = await request.body()
    body_str = body.decode()

    # 🔐 signature check
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
        event = data["event"]
        sub_type = data["subscription"]["type"]

        await route_event(bot_instance, sub_type, event)

    return {"status": "ok"}
