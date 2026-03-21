import aiohttp


class EventSubManager:

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def subscribe_stream_online(self, twitch_user_id: str, callback_url: str):
        url = "https://api.twitch.tv/helix/eventsub/subscriptions"

        headers = {
            "Client-ID": self.session.headers.get("Client-ID"),
            "Authorization": self.session.headers.get("Authorization"),
            "Content-Type": "application/json"
        }

        payload = {
            "type": "stream.online",
            "version": "1",
            "condition": {
                "broadcaster_user_id": twitch_user_id
            },
            "transport": {
                "method": "webhook",
                "callback": callback_url,
                "secret": "YOUR_SECRET"
            }
        }

        async with self.session.post(url, json=payload, headers=headers) as resp:
            return await resp.json()

    async def subscribe_stream_offline(self, twitch_user_id: str, callback_url: str):
        url = "https://api.twitch.tv/helix/eventsub/subscriptions"

        payload = {
            "type": "stream.offline",
            "version": "1",
            "condition": {
                "broadcaster_user_id": twitch_user_id
            },
            "transport": {
                "method": "webhook",
                "callback": callback_url,
                "secret": "YOUR_SECRET"
            }
        }

        async with self.session.post(url, json=payload) as resp:
            return await resp.json()
