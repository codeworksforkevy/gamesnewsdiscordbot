import discord
from discord import app_commands
import asyncpg
import os
import aiohttp


# -------------------------------------------------
# DB CONNECTION
# -------------------------------------------------

async def get_conn():
    return await asyncpg.connect(os.getenv("DATABASE_URL"))


# -------------------------------------------------
# REGISTER
# -------------------------------------------------

def register_live_commands(bot):

    @bot.tree.command(name="add_streamer", description="Add a Twitch streamer to tracking")
    async def add_streamer(
        interaction: discord.Interaction,
        twitch_login: str
    ):
        await interaction.response.defer(ephemeral=True)

        conn = None

        try:
            conn = await get_conn()

            # -------------------------------------------------
            # TWITCH USER FETCH
            # -------------------------------------------------

            headers = {
                "Client-ID": os.getenv("TWITCH_CLIENT_ID"),
                "Authorization": f"Bearer {os.getenv('TWITCH_APP_TOKEN')}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.twitch.tv/helix/users",
                    params={"login": twitch_login},
                    headers=headers
                ) as resp:

                    if resp.status != 200:
                        return await interaction.followup.send(
                            "❌ Twitch API error"
                        )

                    data = await resp.json()

            if not data.get("data"):
                return await interaction.followup.send(
                    "❌ Twitch user not found"
                )

            user = data["data"][0]
            twitch_user_id = user["id"]

            # -------------------------------------------------
            # DB INSERT
            # -------------------------------------------------

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

            # -------------------------------------------------
            # EVENTSUB (🔥 FIXED PART)
            # -------------------------------------------------

            eventsub = interaction.client.app_state.eventsub_manager

            success = await eventsub.subscribe_stream_online(
                twitch_user_id
            )

            if not success:
                return await interaction.followup.send(
                    "⚠️ Streamer added but EventSub subscription failed"
                )

            # -------------------------------------------------
            # SUCCESS
            # -------------------------------------------------

            await interaction.followup.send(
                f"✅ Streamer added: {twitch_login}"
            )

        except Exception as e:
            await interaction.followup.send(
                f"❌ Error: {str(e)}"
            )

        finally:
            if conn:
                await conn.close()
