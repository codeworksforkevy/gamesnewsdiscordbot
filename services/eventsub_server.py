
import os
import json
import hmac
import hashlib
from aiohttp import web
import discord

EVENTSUB_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET", "")

def verify_signature(msg_id, msg_ts, body, signature):
    expected = hmac.new(
        EVENTSUB_SECRET.encode(),
        (msg_id + msg_ts).encode() + body,
        hashlib.sha256
    ).hexdigest()
    return signature == f"sha256={expected}"

def create_eventsub_app(bot: discord.Client):

    async def handler(request):
        body = await request.read()
        msg_id = request.headers.get("Twitch-Eventsub-Message-Id", "")
        msg_ts = request.headers.get("Twitch-Eventsub-Message-Timestamp", "")
        signature = request.headers.get("Twitch-Eventsub-Message-Signature", "")
        msg_type = request.headers.get("Twitch-Eventsub-Message-Type", "")

        if not verify_signature(msg_id, msg_ts, body, signature):
            return web.Response(status=403)

        payload = json.loads(body.decode())

        if msg_type == "webhook_callback_verification":
            return web.Response(text=payload.get("challenge", ""))

        if msg_type == "notification":
            event = payload.get("event", {})
            login = event.get("broadcaster_user_login")
            title = event.get("title")
            game = event.get("category_name")

            channel_id = int(os.getenv("CHANNEL_ID"))
            channel = bot.get_channel(channel_id)

            if channel:
                embed = discord.Embed(
                    title=f"🔴 {login} is Live!",
                    description=title,
                    color=0x9146FF
                )
                if game:
                    embed.add_field(name="Game", value=game, inline=True)
                embed.add_field(
                    name="Watch",
                    value=f"https://twitch.tv/{login}",
                    inline=False
                )
                await channel.send(embed=embed)

        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post("/twitch/eventsub", handler)
    return app
