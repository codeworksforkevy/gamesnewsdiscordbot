import discord
from discord import app_commands
from services.eventsub_manager import subscribe_stream_online
import asyncpg
import os

async def get_conn():
    return await asyncpg.connect(os.getenv("DATABASE_URL"))

def setup(bot):

    @bot.tree.command(name="add_streamer")
    async def add_streamer(
        interaction: discord.Interaction,
        twitch_login: str
    ):
        await interaction.response.defer(ephemeral=True)

        conn = await get_conn()

        # Twitch → user_id fetch
        import aiohttp

        headers = {
            "Client-ID": os.getenv("TWITCH_CLIENT_ID"),
            "Authorization": f"Bearer {os.getenv('TWITCH_APP_TOKEN')}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.twitch.tv/helix/users?login={twitch_login}",
                headers=headers
            ) as resp:
                data = await resp.json()

        if not data["data"]:
            return await interaction.followup.send("❌ Twitch user not found")

        user = data["data"][0]

        twitch_user_id = user["id"]

        # DB insert
        await conn.execute(
            """
            INSERT INTO streamers (twitch_user_id, twitch_login, guild_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (twitch_user_id) DO NOTHING
            """,
            twitch_user_id,
            twitch_login,
            interaction.guild.id
        )

        await conn.close()

        # EventSub subscribe
        await subscribe_stream_online(
            twitch_user_id,
            os.getenv("WEBHOOK_URL")
        )

        await interaction.followup.send(f"✅ Streamer added: {twitch_login}")
