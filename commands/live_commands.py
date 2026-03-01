import json
import os
import discord
from discord import app_commands


DATA_FILE = "data/streamers.json"
MAX_STREAMERS = 100


# ==================================================
# STORAGE
# ==================================================

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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

def register_live_commands(bot):

    group = app_commands.Group(
        name="live",
        description="Manage followed Twitch channels"
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
                "Administrator or Manage Server permission required.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        twitch_api = bot.app_state.twitch_api
        user = await twitch_api.resolve_user(login)

        if not user:
            await interaction.followup.send(
                "Twitch channel not found."
            )
            return

        data = load_streamers()

        # HARD CAP
        if len(data) >= MAX_STREAMERS:
            await interaction.followup.send(
                f"Maximum capacity reached ({MAX_STREAMERS} channels). "
                "Remove a channel before adding a new one."
            )
            return

        if user["id"] in data:
            await interaction.followup.send(
                "This channel is already being followed."
            )
            return

        data[user["id"]] = {
            "id": user["id"],
            "login": user["login"],
            "display_name": user["display_name"]
        }

        save_streamers(data)

        embed = discord.Embed(
            color=0x9146FF
        )

        embed.description = (
            "👩‍💻 **Begin following a Twitch channel’s live sessions.**\n"
            f"You will receive automatic notifications when they go live.\n\n"
            "👩‍💻 **Begin met het volgen van de live sessies van "
            f"**{user['display_name']}**.\n"
            "Je ontvangt automatisch een melding wanneer het kanaal live gaat.\n\n"
            "Need help? Ask Sim for guidance."
        )

        await interaction.followup.send(embed=embed)

    # --------------------------------------------------
    # REMOVE
    # --------------------------------------------------

    @group.command(
        name="remove",
        description="🛑 Stop following a Twitch channel’s live sessions"
    )
    async def remove(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message(
                "Administrator or Manage Server permission required.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        data = load_streamers()

        for sid, info in list(data.items()):
            if info["login"].lower() == login.lower():

                del data[sid]
                save_streamers(data)

                embed = discord.Embed(color=0x9146FF)

                embed.description = (
                    "🛑 **Stop following a Twitch channel’s live sessions.**\n"
                    "Live notifications have been disabled.\n\n"
                    "🛑 **Stop met het volgen van de live sessies van "
                    f"**{info['display_name']}**.\n"
                    "Live meldingen zijn uitgeschakeld.\n\n"
                    "Need help? Ask Sim for guidance."
                )

                await interaction.followup.send(embed=embed)
                return

        await interaction.followup.send(
            "Twitch channel not found."
        )

    # --------------------------------------------------
    # LIST
    # --------------------------------------------------

    @group.command(
        name="list",
        description="📡 View followed Twitch channels"
    )
    async def list_cmd(interaction: discord.Interaction):

        data = load_streamers()

        if not data:
            await interaction.response.send_message(
                "No Twitch channels are currently being followed.",
                ephemeral=True
            )
            return

        names = [v["display_name"] for v in data.values()]

        embed = discord.Embed(
            title="📡 Live Monitoring",
            color=0x9146FF
        )

        embed.description = (
            "📡 **Here are the Twitch channels we are currently following.**\n"
            "You will receive notifications whenever they go live.\n\n"
            "📡 **Dit zijn de Twitch-kanalen die we momenteel volgen.**\n"
            "Je ontvangt een melding wanneer ze live gaan.\n\n"
        )

        embed.add_field(
            name="Channels",
            value="\n".join(f"• {n}" for n in names),
            inline=False
        )

        embed.set_footer(text="Need help? Ask Sim for guidance.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --------------------------------------------------
    # HELP (LIVE ONLY)
    # --------------------------------------------------

    @group.command(
        name="help",
        description="📘 View help information for live tracking"
    )
    async def help_cmd(interaction: discord.Interaction):

        embed = discord.Embed(
            title="📡 Live Tracking Guide",
            color=0x9146FF
        )

        embed.add_field(
            name="/live add <login>",
            value="Begin following a Twitch channel’s live sessions.",
            inline=False
        )

        embed.add_field(
            name="/live remove <login>",
            value="Stop following a Twitch channel’s live sessions.",
            inline=False
        )

        embed.add_field(
            name="/live list",
            value="View all followed Twitch channels.",
            inline=False
        )

        embed.add_field(
            name="Permissions",
            value=(
                "Administrator or Manage Server permission required "
                "to modify the list."
            ),
            inline=False
        )

        embed.set_footer(text="Need help? Ask Sim for guidance.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(group)
