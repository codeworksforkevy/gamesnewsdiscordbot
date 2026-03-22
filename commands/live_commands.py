# commands/live_commands.py

import discord
from discord import app_commands
import logging

from core.event_bus import event_bus

logger = logging.getLogger("live-commands")


# ==================================================
# REGISTER
# ==================================================
async def register(bot, app_state, session):

    db = app_state.db

    group = app_commands.Group(
        name="live",
        description="Manage Twitch live stream tracking"
    )

    # ==================================================
    # ADD STREAMER
    # ==================================================
    @group.command(name="add", description="Add a Twitch streamer")
    async def add_streamer(
        interaction: discord.Interaction,
        twitch_login: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            twitch_api = app_state.twitch_api

            user = await twitch_api.get_user_by_login(twitch_login)

            if not user:
                return await interaction.followup.send(
                    "❌ Twitch user not found"
                )

            twitch_user_id = user["id"]

            # -------------------------
            # DB INSERT
            # -------------------------
            await db.execute(
                """
                INSERT INTO streamers (twitch_user_id, twitch_login, guild_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (twitch_user_id) DO NOTHING
                """,
                twitch_user_id,
                twitch_login,
                interaction.guild_id
            )

            # -------------------------
            # EVENT EMIT
            # -------------------------
            await event_bus.emit("streamer_added", {
                "twitch_user_id": twitch_user_id,
                "guild_id": interaction.guild_id
            })

            embed = discord.Embed(
                title="✅ Streamer Added",
                description=f"**{twitch_login}** is now tracked.",
                color=0x2ecc71
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception("Add streamer failed")

            await interaction.followup.send(
                "❌ Failed to add streamer"
            )

    # ==================================================
    # LIST STREAMERS
    # ==================================================
    @group.command(name="list", description="List tracked streamers")
    async def list_streamers(interaction: discord.Interaction):

        try:
            rows = await db.fetch(
                """
                SELECT twitch_login
                FROM streamers
                WHERE guild_id = $1
                ORDER BY created_at DESC
                """,
                interaction.guild_id
            )

            if not rows:
                return await interaction.response.send_message(
                    "📭 No streamers tracked.",
                    ephemeral=True
                )

            desc = "\n".join(
                [f"• {r['twitch_login']}" for r in rows]
            )

            embed = discord.Embed(
                title="📡 Tracked Streamers",
                description=desc,
                color=0x3498db
            )

            await interaction.response.send_message(embed=embed)

        except Exception:
            logger.exception("List streamer failed")

            await interaction.response.send_message(
                "❌ Failed to fetch list",
                ephemeral=True
            )

    # ==================================================
    # REMOVE STREAMER
    # ==================================================
    @group.command(name="remove", description="Remove a streamer")
    async def remove_streamer(
        interaction: discord.Interaction,
        twitch_login: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            result = await db.execute(
                """
                DELETE FROM streamers
                WHERE twitch_login = $1 AND guild_id = $2
                """,
                twitch_login,
                interaction.guild_id
            )

            if result == "DELETE 0":
                return await interaction.followup.send(
                    "❌ Streamer not found"
                )

            await event_bus.emit("streamer_removed", {
                "twitch_login": twitch_login,
                "guild_id": interaction.guild_id
            })

            embed = discord.Embed(
                title="🗑️ Streamer Removed",
                description=f"{twitch_login} removed.",
                color=0xe74c3c
            )

            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("Remove streamer failed")

            await interaction.followup.send(
                "❌ Failed to remove streamer"
            )

    # ==================================================
    # REGISTER GROUP
    # ==================================================
    bot.tree.add_command(group)
