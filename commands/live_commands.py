import json
import os
import discord
from discord import app_commands

from services.twitch_api import resolve_user
from services.eventsub_manager import ensure_stream_subscriptions

DATA_FILE = "data/streamers.json"


# ==================================================
# STORAGE
# ==================================================

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return {"guilds": {}}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "guilds" not in data:
                return {"guilds": {}}
            return data
    except Exception:
        return {"guilds": {}}


def save_streamers(data):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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

        data = load_streamers()

        guild_id = str(interaction.guild_id)
        channel_id = interaction.channel_id
        twitch_id = user["id"]

        # Ensure guild container exists
        if guild_id not in data["guilds"]:
            data["guilds"][guild_id] = {"streamers": {}}

        guild_streamers = data["guilds"][guild_id]["streamers"]

        # Duplicate check
        if twitch_id in guild_streamers:
            await interaction.followup.send(
                "This Twitch channel is already being followed in this server."
            )
            return

        # Save streamer
        guild_streamers[twitch_id] = {
            "login": user["login"],
            "display_name": user["display_name"],
            "channel_id": channel_id,
            "is_live": False
        }

        save_streamers(data)

        # 🔥 Create EventSub subscriptions
        try:
            await ensure_stream_subscriptions(twitch_id)
        except Exception as e:
            # Subscription failure should not break command
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

        data = load_streamers()
        guild_id = str(interaction.guild_id)

        if guild_id not in data["guilds"]:
            await interaction.followup.send("No channels are being followed here.")
            return

        guild_streamers = data["guilds"][guild_id]["streamers"]

        for twitch_id, info in list(guild_streamers.items()):
            if info["login"].lower() == login.lower():

                del guild_streamers[twitch_id]
                save_streamers(data)

                await interaction.followup.send(
                    f"""🧑‍💻 **Live Tracking Disabled**

Stopped following **{info['display_name']}**.

You will no longer receive live notifications."""
                )
                return

        await interaction.followup.send(
            "Twitch channel not found in this server."
        )

    # --------------------------------------------------
    # LIST
    # --------------------------------------------------

    @group.command(
        name="list",
        description="💻 View followed Twitch channels"
    )
    async def list_cmd(interaction: discord.Interaction):

        data = load_streamers()
        guild_id = str(interaction.guild_id)

        if guild_id not in data["guilds"]:
            await interaction.response.send_message(
                "No Twitch channels are currently being followed.",
                ephemeral=True
            )
            return

        guild_streamers = data["guilds"][guild_id]["streamers"]

        if not guild_streamers:
            await interaction.response.send_message(
                "No Twitch channels are currently being followed.",
                ephemeral=True
            )
            return

        names = [v["display_name"] for v in guild_streamers.values()]

        embed = discord.Embed(
            title="💻 Followed Twitch Channels",
            description="\n".join(f"• {n}" for n in names),
            color=0x9146FF
        )

        embed.set_footer(text="Find a Curie • Live Monitoring")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --------------------------------------------------
    # HELP
    # --------------------------------------------------

    @group.command(
        name="help",
        description="📘 View help information for live tracking"
    )
    async def help_cmd(interaction: discord.Interaction):

        embed = discord.Embed(
            title="📡 Live Notification System",
            description=(
                "Automatically notifies this server when selected Twitch "
                "channels go live."
            ),
            color=0x9146FF
        )

        embed.add_field(
            name="👩‍💻 /live add <login>",
            value="Start tracking a Twitch channel.",
            inline=False
        )

        embed.add_field(
            name="🧑‍💻 /live remove <login>",
            value="Stop tracking a Twitch channel.",
            inline=False
        )

        embed.add_field(
            name="💻 /live list",
            value="View tracked Twitch channels in this server.",
            inline=False
        )

        embed.set_footer(text="Admin or Manage Server permission required.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(group)
