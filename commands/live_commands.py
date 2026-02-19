import json
import os
import discord
from discord import app_commands
from services.twitch_api import resolve_user

DATA_FILE = "data/streamers.json"


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

        if user["id"] in data:
            await interaction.followup.send("This channel is already being followed.")
            return

        data[user["id"]] = user
        save_streamers(data)

        await interaction.followup.send(
            f"""👩‍💻 **Begin following a Twitch channel’s live sessions**

**{user['display_name']}** is now being followed.
You will receive automatic notifications when they go live.

🇳🇱 **Dutch**
👩‍💻 Begin met het volgen van de live sessies van **{user['display_name']}**.
Je ontvangt automatisch een melding wanneer het kanaal live gaat.

Need help? Ask Sim for guidance."""
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

        for sid, info in list(data.items()):
            if info["login"].lower() == login.lower():

                del data[sid]
                save_streamers(data)

                await interaction.followup.send(
                    f"""🧑‍💻 **Stop following a Twitch channel’s live sessions**

**{info['display_name']}** is no longer being followed.
Live notifications have been disabled.

🇳🇱 **Dutch**
🧑‍💻 Stop met het volgen van de live sessies van **{info['display_name']}**.
Live meldingen zijn uitgeschakeld.

Need help? Ask Sim for guidance."""
                )
                return

        await interaction.followup.send("Twitch channel not found.")

    # --------------------------------------------------
    # LIST
    # --------------------------------------------------

    @group.command(
        name="list",
        description="💻 View followed Twitch channels"
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
            title="💻 Followed Twitch Channels",
            description="\n".join(f"• {n}" for n in names),
            color=0x9146FF  # Twitch purple
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
                "This feature allows the bot to automatically notify this server "
                "whenever selected Twitch channels go live."
            ),
            color=0x9146FF
        )

        embed.add_field(
            name="👩‍💻 /live add <login>",
            value="Begin following a Twitch channel’s live sessions.",
            inline=False
        )

        embed.add_field(
            name="🧑‍💻 /live remove <login>",
            value="Stop following a Twitch channel’s live sessions.",
            inline=False
        )

        embed.add_field(
            name="💻 /live list",
            value="View all followed Twitch channels.",
            inline=False
        )

        embed.add_field(
            name="🇳🇱 Dutch",
            value=(
                "Deze functie stuurt automatisch meldingen wanneer geselecteerde "
                "Twitch-kanalen live gaan.\n\n"
                "Alleen beheerders of moderators mogen de lijst aanpassen."
            ),
            inline=False
        )

        embed.set_footer(text="Need help? Ask Sim for guidance.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(group)
