import discord
from discord import app_commands
import asyncpg
import os
import aiohttp
import traceback


async def register_live_commands(bot, app_state):

    # -------------------------------------------------
    # DATABASE
    # -------------------------------------------------
    async def get_conn():
        return await asyncpg.connect(os.getenv("DATABASE_URL"))

    # -------------------------------------------------
    # ADD STREAMER
    # -------------------------------------------------
    @bot.tree.command(name="add_streamer")
    async def add_streamer(
        interaction: discord.Interaction,
        twitch_login: str
    ):
        await interaction.response.defer(ephemeral=True)

        # Guild kontrolü
        if interaction.guild is None:
            return await interaction.followup.send(
                "❌ This command can only be used in a server.",
                ephemeral=True
            )

        conn = None

        try:
            conn = await get_conn()

            headers = {
                "Client-ID": os.getenv("TWITCH_CLIENT_ID"),
                "Authorization": f"Bearer {os.getenv('TWITCH_APP_TOKEN')}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.twitch.tv/helix/users?login={twitch_login}",
                    headers=headers
                ) as resp:

                    # HTTP kontrol
                    if resp.status != 200:
                        return await interaction.followup.send(
                            f"❌ Twitch API error: {resp.status}",
                            ephemeral=True
                        )

                    data = await resp.json()

            if not data.get("data"):
                return await interaction.followup.send(
                    "❌ Twitch user not found",
                    ephemeral=True
                )

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

            # EventSub subscription (SAFE)
            if hasattr(app_state, "eventsub_manager"):
                await app_state.eventsub_manager.subscribe_stream_online(
                    twitch_user_id,
                    os.getenv("WEBHOOK_URL")
                )

            await interaction.followup.send(
                f"✅ Streamer added: {twitch_login}",
                ephemeral=True
            )

        except Exception as e:
            print("ADD_STREAMER ERROR:", e)
            traceback.print_exc()

            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ Unexpected error occurred.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ Unexpected error occurred.",
                    ephemeral=True
                )

        finally:
            if conn:
                await conn.close()
