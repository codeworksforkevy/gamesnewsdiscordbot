import discord
from discord import app_commands
import aiohttp
import logging

logger = logging.getLogger("live")

TWITCH_URL = "https://api.twitch.tv/helix/users"


async def register(bot, app_state):

    # ==================================================
    # ADD STREAMER
    # ==================================================
    @bot.tree.command(name="live_add", description="Add a streamer")
    async def add_streamer(
        interaction: discord.Interaction,
        twitch_login: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            headers = {
                "Client-ID": app_state.config["TWITCH_CLIENT_ID"],
                "Authorization": f"Bearer {app_state.config['TWITCH_APP_TOKEN']}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{TWITCH_URL}?login={twitch_login}",
                    headers=headers
                ) as resp:

                    if resp.status != 200:
                        return await interaction.followup.send(
                            "❌ Twitch API error",
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

            await app_state.db.execute(
                """
                INSERT INTO streamers (twitch_user_id, twitch_login, guild_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                twitch_user_id,
                twitch_login,
                interaction.guild.id
            )

            await interaction.followup.send(
                f"✅ Added: {twitch_login}",
                ephemeral=True
            )

        except Exception as e:
            logger.exception("add_streamer failed")

            await interaction.followup.send(
                "❌ Internal error",
                ephemeral=True
            )

    # ==================================================
    # LIST STREAMERS
    # ==================================================
    @bot.tree.command(name="live_list", description="List streamers")
    async def list_streamers(interaction: discord.Interaction):

        try:
            rows = await app_state.db.fetch(
                """
                SELECT twitch_login
                FROM streamers
                WHERE guild_id=$1
                """,
                interaction.guild.id
            )

            if not rows:
                return await interaction.response.send_message(
                    "No streamers added.",
                    ephemeral=True
                )

            text = "\n".join([f"• {r['twitch_login']}" for r in rows])

            embed = discord.Embed(
                title="📡 Tracked Streamers",
                description=text,
                color=0x9146FF
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

        except Exception:
            logger.exception("list_streamers failed")

            await interaction.response.send_message(
                "❌ Failed to fetch streamers",
                ephemeral=True
            )
