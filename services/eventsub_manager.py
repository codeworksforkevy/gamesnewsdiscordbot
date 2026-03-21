import asyncio
import logging
import json

logger = logging.getLogger("eventsub")


class EventSubManager:

    def __init__(self, twitch_api, session, db):
        self.twitch_api = twitch_api
        self.session = session
        self.db = db

        self.subscriptions = {}

    # ==================================================
    # SUBSCRIBE STREAM ONLINE
    # ==================================================

    async def subscribe_stream_online(self, broadcaster_id: str):

        payload = {
            "type": "stream.online",
            "version": "1",
            "condition": {
                "broadcaster_user_id": broadcaster_id
            }
        }

        # call twitch API (pseudo)
        response = await self.twitch_api.create_eventsub(payload)

        sub_id = response.get("id")

        self.subscriptions[sub_id] = payload

        logger.info("Subscribed stream.online", extra={"extra_data": {"id": sub_id}})

        return sub_id

    # ==================================================
    # STREAM OFFLINE
    # ==================================================

    async def subscribe_stream_offline(self, broadcaster_id: str):

        payload = {
            "type": "stream.offline",
            "version": "1",
            "condition": {
                "broadcaster_user_id": broadcaster_id
            }
        }

        response = await self.twitch_api.create_eventsub(payload)

        sub_id = response.get("id")

        self.subscriptions[sub_id] = payload

        return sub_id

    # ==================================================
    # CACHE (Redis / DB)
    # ==================================================

    async def get_cached_stream(self, user_id: str):
        return await self.db.get_stream_cache(user_id)

    async def set_cached_stream(self, user_id: str, data: dict):
        await self.db.set_stream_cache(user_id, data)
