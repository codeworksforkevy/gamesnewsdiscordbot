import logging

logger = logging.getLogger("streamer")


class StreamerService:

    def __init__(self, eventsub_manager, cache):
        self.eventsub = eventsub_manager
        self.cache = cache

    # ==================================================
    # TITLE / GAME TRACKING
    # ==================================================

    async def handle_stream_update(self, user_id: str, new_data: dict):

        old_data = await self.cache.get(user_id)

        if not old_data:
            await self.cache.set(user_id, new_data)
            return None

        changes = {}

        if old_data.get("title") != new_data.get("title"):
            changes["title"] = {
                "old": old_data.get("title"),
                "new": new_data.get("title")
            }

        if old_data.get("game") != new_data.get("game"):
            changes["game"] = {
                "old": old_data.get("game"),
                "new": new_data.get("game")
            }

        if changes:
            await self.cache.set(user_id, new_data)
            return changes

        return None

    # ==================================================
    # SMART NOTIFICATION
    # ==================================================

    async def notify_changes(self, bot, user_id: str, changes: dict):

        channel = await self.get_notification_channel(bot, user_id)

        if not channel:
            return

        message = "🔔 Stream güncellendi:\n"

        if "title" in changes:
            message += f"🎯 Title: {changes['title']['old']} → {changes['title']['new']}\n"

        if "game" in changes:
            message += f"🎮 Game: {changes['game']['old']} → {changes['game']['new']}\n"

        await channel.send(message)

    async def get_notification_channel(self, bot, user_id):
        # DB'den al
        return None
