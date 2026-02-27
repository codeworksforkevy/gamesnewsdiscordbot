import discord
from discord import app_commands

from services.twitch_api import resolve_user
from services.eventsub_manager import ensure_stream_subscriptions
from services.streamer_registry import (
    add_streamer,
    remove_streamer,
    get_guilds_for_streamer
)


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
                "Admin or mod only.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        user = await resolve_user(login)
        if not user:
            await interaction.followup.send("Twitch channel not found.")
            return

        guild_id = interaction.guild_id
        channel_id = interaction.channel_id
        twitch_id = user["id"]

        # Save to PostgreSQL
        await add_streamer(guild_id, twitch_id, channel_id)

        # Ensure EventSub subscription
        try:
            await ensure_stream_subscriptions(twitch_id)
        except Exception as e:
            print(f"Subscription error: {e}")

        await interaction.followup.send(
            f"""👩‍💻 **Live Tracking Enabled**

Now tracking **{user['display_name']}** in this channel.

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
                "Admin or mod only.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        user = await resolve_user(login)
        if not user:
            await interaction.followup.send("Twitch channel not found.")
            return

        await remove_streamer(interaction.guild_id, user["id"])

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

        guild_id = interaction.guild_id

        embed = discord.Embed(
            title="💻 Followed Twitch Channels",
            color=0x9146FF
        )

        # DB’den tüm kayıtları çek
        # broadcaster_id bazlı değil, guild bazlı liste lazım
        # küçük ek query yapacağız

        from services.db import get_pool
        pool = await get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT broadcaster_id
                FROM streamers
                WHERE guild_id = $1;
            """, str(guild_id))

        if not rows:
            await interaction.response.send_message(
                "No Twitch channels are currently being followed.",
                ephemeral=True
            )
            return

        lines = []
        for r in rows:
            lines.append(f"• ID: {r['broadcaster_id']}")

        embed.description = "\n".join(lines)
        embed.set_footer(text="Find a Curie • Live Monitoring")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(group)
