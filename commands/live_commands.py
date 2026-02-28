import discord
from discord import app_commands


# ==================================================
# PERMISSIONS
# ==================================================

def has_permission(interaction: discord.Interaction):
    if not interaction.guild:
        return False
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild


# ==================================================
# REGISTER COMMANDS
# ==================================================

def register_live_commands(bot: discord.Client):

    group = app_commands.Group(
        name="live",
        description="Manage followed Twitch channels 💻"
    )

    # --------------------------------------------------
    # ADD
    # --------------------------------------------------

    @group.command(
        name="add",
        description="👩‍💻 Begin following a Twitch channel’s live sessions"
    )
    async def add(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message(
                "Admin or Manage Server permission required.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        twitch_api = bot.app_state.twitch_api
        eventsub_manager = bot.app_state.eventsub_manager
        db = bot.app_state.db

        user = await twitch_api.resolve_user(login)

        if not user:
            await interaction.followup.send(
                "Twitch channel not found."
            )
            return

        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        twitch_id = user["id"]

        pool = db.get_pool()

        async with pool.acquire() as conn:

            # 🔥 GLOBAL HARD CAP (100)
            total = await conn.fetchval(
                "SELECT COUNT(DISTINCT broadcaster_id) FROM streamers;"
            )

            if total >= 100:
                await interaction.followup.send(
                    "🚫 Global streamer limit (100) reached.\n"
                    "No more Twitch channels can be tracked.",
                )
                return

            # Duplicate check (same guild)
            exists = await conn.fetchval("""
                SELECT 1 FROM streamers
                WHERE guild_id = $1
                AND broadcaster_id = $2;
            """, guild_id, twitch_id)

            if exists:
                await interaction.followup.send(
                    "This Twitch channel is already being tracked in this server."
                )
                return

            # Insert
            await conn.execute("""
                INSERT INTO streamers
                (guild_id, broadcaster_id, channel_id, is_live)
                VALUES ($1, $2, $3, FALSE);
            """, guild_id, twitch_id, channel_id)

        # Ensure EventSub subscription
        try:
            await eventsub_manager.ensure_stream_subscriptions(twitch_id)
        except Exception as e:
            bot.logger.error("Subscription error: %s", e)

        await interaction.followup.send(
            f"""👩‍💻 **Live Tracking Enabled**

Now tracking **{user['display_name']}**.

You will automatically receive a notification when they go live."""
        )

    # --------------------------------------------------
    # REMOVE
    # --------------------------------------------------

    @group.command(
        name="remove",
        description="🧑‍💻 Stop following a Twitch channel’s live sessions"
    )
    async def remove(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message(
                "Admin or Manage Server permission required.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        twitch_api = bot.app_state.twitch_api
        db = bot.app_state.db

        user = await twitch_api.resolve_user(login)

        if not user:
            await interaction.followup.send(
                "Twitch channel not found."
            )
            return

        guild_id = str(interaction.guild_id)
        twitch_id = user["id"]

        pool = db.get_pool()

        async with pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM streamers
                WHERE guild_id = $1
                AND broadcaster_id = $2;
            """, guild_id, twitch_id)

        await interaction.followup.send(
            f"""🧑‍💻 **Live Tracking Disabled**

Stopped following **{user['display_name']}**.

You will no longer receive live notifications."""
        )

    # --------------------------------------------------
    # LIST
    # --------------------------------------------------

    @group.command(
        name="list",
        description="💻 View followed Twitch channels"
    )
    async def list_cmd(interaction: discord.Interaction):

        guild_id = str(interaction.guild_id)
        db = bot.app_state.db
        pool = db.get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT broadcaster_id
                FROM streamers
                WHERE guild_id = $1;
            """, guild_id)

        if not rows:
            await interaction.response.send_message(
                "No Twitch channels are currently being followed.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="💻 Followed Twitch Channels",
            color=0x9146FF
        )

        lines = [
            f"• ID: {r['broadcaster_id']}"
            for r in rows
        ]

        embed.description = "\n".join(lines)
        embed.set_footer(text="Find a Curie • Live Monitoring")

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    bot.tree.add_command(group)
