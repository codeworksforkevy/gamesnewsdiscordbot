# commands/notify.py
#
# 🔔 Personal live notifications — DM when a tracked streamer goes live
#
# /notify add <streamer>    → subscribe to DM notifications
# /notify remove <streamer> → unsubscribe
# /notify list              → see your active subscriptions
#
# DMs are only sent for streamers in the server's tracked list.
# Stored in: user_notifications (user_id, guild_id, twitch_login)

import logging

import discord
from discord import app_commands

logger = logging.getLogger("notify")


async def register(bot, app_state, session):

    db = app_state.db

    group = app_commands.Group(
        name="notify",
        description="🔔 Personal DM notifications when a streamer goes live",
    )

    # ── /notify add ────────────────────────────────────────────────────────
    @group.command(name="add", description="Get a DM when a tracked streamer goes live")
    @app_commands.describe(streamer="Twitch username (must be in the tracked list)")
    async def notify_add(interaction: discord.Interaction, streamer: str):
        await interaction.response.defer(ephemeral=True)

        login = streamer.strip().lower()

        # Must be in tracked list for this server
        try:
            tracked = await db.fetchrow(
                "SELECT 1 FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                login, interaction.guild_id,
            )
            if not tracked:
                rows  = await db.fetch(
                    "SELECT twitch_login FROM streamers WHERE guild_id = $1 ORDER BY twitch_login",
                    interaction.guild_id,
                )
                names = ", ".join(f"`{r['twitch_login']}`" for r in rows) or "none yet"
                await interaction.followup.send(
                    f"❌ **{login}** is not in the tracked list.\n"
                    f"Tracked streamers: {names}",
                    ephemeral=True,
                )
                return
        except Exception as e:
            logger.error(f"/notify add DB check failed: {e}")
            await interaction.followup.send("❌ Database error. Try again.", ephemeral=True)
            return

        # Already subscribed?
        try:
            existing = await db.fetchrow(
                "SELECT 1 FROM user_notifications WHERE user_id = $1 AND twitch_login = $2",
                interaction.user.id, login,
            )
            if existing:
                await interaction.followup.send(
                    f"⚠️ You're already subscribed to **{login}**.",
                    ephemeral=True,
                )
                return
        except Exception as e:
            logger.error(f"/notify add existing check failed: {e}")

        # Insert
        try:
            await db.execute(
                """
                INSERT INTO user_notifications (user_id, guild_id, twitch_login)
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING
                """,
                interaction.user.id, interaction.guild_id, login,
            )
        except Exception as e:
            logger.error(f"/notify add insert failed: {e}")
            await interaction.followup.send("❌ Could not save. Try again.", ephemeral=True)
            return

        # Fetch streamer info for the confirmation embed
        user_info = None
        try:
            user_info = await app_state.twitch_api.get_user_by_login(login)
        except Exception:
            pass

        embed = discord.Embed(
            description=(
                f"You'll get a DM the next time **{login}** goes live.\n"
                f"Use `/notify remove {login}` to unsubscribe anytime."
            ),
            color=0xFFB6C1,
        )
        embed.set_author(
            name=f"Subscribed to {login}",
            icon_url=user_info.get("profile_image_url") if user_info else None,
        )
        embed.set_footer(text="Notifications go to your DMs — no server ping.")

        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"/notify add: {interaction.user} → {login}")

    # ── /notify remove ─────────────────────────────────────────────────────
    @group.command(name="remove", description="Stop DM notifications for a streamer")
    @app_commands.describe(streamer="Twitch username to unsubscribe from")
    async def notify_remove(interaction: discord.Interaction, streamer: str):
        await interaction.response.defer(ephemeral=True)

        login = streamer.strip().lower()

        try:
            result = await db.execute(
                "DELETE FROM user_notifications WHERE user_id = $1 AND twitch_login = $2",
                interaction.user.id, login,
            )
        except Exception as e:
            logger.error(f"/notify remove failed: {e}")
            await interaction.followup.send("❌ Database error. Try again.", ephemeral=True)
            return

        if result == "DELETE 0":
            await interaction.followup.send(
                f"❌ You weren't subscribed to **{login}**.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Unsubscribed from **{login}**. You won't receive DMs for this streamer anymore.",
            ephemeral=True,
        )
        logger.info(f"/notify remove: {interaction.user} → {login}")

    # ── /notify list ───────────────────────────────────────────────────────
    @group.command(name="list", description="See all your active DM subscriptions")
    async def notify_list(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            rows = await db.fetch(
                "SELECT twitch_login FROM user_notifications WHERE user_id = $1 ORDER BY twitch_login",
                interaction.user.id,
            )
        except Exception as e:
            logger.error(f"/notify list failed: {e}")
            await interaction.followup.send("❌ Database error. Try again.", ephemeral=True)
            return

        if not rows:
            await interaction.followup.send(
                "📭 You have no active subscriptions.\n"
                "Use `/notify add <streamer>` to subscribe.",
                ephemeral=True,
            )
            return

        lines = [
            f"• [{r['twitch_login']}](https://twitch.tv/{r['twitch_login']})"
            for r in rows
        ]

        embed = discord.Embed(
            title="🔔 Your DM subscriptions",
            description="\n".join(lines),
            color=0xFFB6C1,
        )
        embed.set_footer(text=f"{len(rows)} active • /notify remove <name> to unsubscribe")
        await interaction.followup.send(embed=embed, ephemeral=True)

    bot.tree.add_command(group)
    logger.info("notify commands registered")
