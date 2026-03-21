import os
import aiohttp
import logging

logger = logging.getLogger("eventsub")

TWITCH_EVENTSUB_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"


class EventSubManager:

    def __init__(self, twitch_api, session: aiohttp.ClientSession, db):
        self.twitch_api = twitch_api
        self.session = session
        self.db = db

    async def subscribe_stream_online(self, broadcaster_user_id: str, callback_url: str):

        headers = {
            "Client-ID": os.getenv("TWITCH_CLIENT_ID"),
            "Authorization": f"Bearer {os.getenv('TWITCH_APP_TOKEN')}",
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

        async with self.session.post(
            TWITCH_EVENTSUB_URL,
            headers=headers,
            json=payload
        ) as resp:

            data = await resp.text()

            if resp.status >= 300:
                logger.error(f"EventSub subscribe failed: {data}")
            else:
                logger.info(f"Subscribed to {broadcaster_user_id}")

                # optional DB kayıt (ileride unsubscribe için)
                try:
                    pool = self.db.get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO twitch_eventsub (broadcaster_id)
                            VALUES ($1)
                            ON CONFLICT DO NOTHING
                            """,
                            broadcaster_user_id
                        )
                except Exception as e:
                    logger.warning(f"DB write failed: {e}")


# 🔥 BACKWARD COMPAT
async def subscribe_stream_online(broadcaster_user_id: str, callback_url: str):
    async with aiohttp.ClientSession() as session:
        manager = EventSubManager(None, session, None)
        await manager.subscribe_stream_online(broadcaster_user_id, callback_url)
