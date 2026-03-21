import os
import aiohttp
import logging

logger = logging.getLogger("eventsub")

TWITCH_EVENTSUB_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"


class EventSubManager:

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def subscribe_stream_online(self, broadcaster_user_id: str, callback_url: str):

        client_id = os.getenv("TWITCH_CLIENT_ID")
        token = os.getenv("TWITCH_APP_TOKEN")

        if not client_id or not token:
            logger.error("Missing Twitch credentials")
            return

        headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "type": "stream.online",
            "version": "1",
            "condition": {
                "broadcaster_user_id": broadcaster_user_id
            },
            "transport": {
                "method": "webhook",
                "callback": callback_url,
                "secret": os.getenv("TWITCH_EVENTSUB_SECRET", "supersecret")
            }
        }

        try:
            async with self.session.post(
                TWITCH_EVENTSUB_URL,
                headers=headers,
                json=payload
            ) as resp:

                text = await resp.text()

                if resp.status >= 300:
                    logger.error(
                        "EventSub subscribe failed",
                        extra={"extra_data": {
                            "status": resp.status,
                            "response": text
                        }}
                    )
                else:
                    logger.info(
                        "EventSub subscribed",
                        extra={"extra_data": {
                            "broadcaster": broadcaster_user_id
                        }}
                    )

        except Exception as e:
            logger.exception(f"EventSub request error: {e}")


# backward compat
async def subscribe_stream_online(broadcaster_user_id: str, callback_url: str):
    async with aiohttp.ClientSession() as session:
        manager = EventSubManager(session)
        await manager.subscribe_stream_online(broadcaster_user_id, callback_url)
