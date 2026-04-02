# commands/curie_status.py
#
# /curie_status — Admin-only laboratoriumstatus van Find a Curie
# Toont: database, Redis, Twitch API, EventSub, StreamMonitor,
#        uptime, latency, guilds, tracked streamers.

import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands

logger = logging.getLogger("curie-status")

KEVY_PINK = 0xFFB6C1


def _fmt_uptime(start: datetime) -> str:
    """Converts a start datetime to a human-readable uptime string."""
    delta = datetime.now(timezone.utc) - start
    days  = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes          = remainder // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


async def register(bot, app_state, session):

    @bot.tree.command(
        name="curie_status",
        description="⚠️ (Admin) Check Curie's laboratory vitals",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def curie_status(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # ── Core services ──────────────────────────────────────────────────
        db_ok      = bool(app_state.db)
        redis_ok   = bool(getattr(app_state, "redis", None))
        twitch_ok  = bool(getattr(app_state, "twitch_api", None))
        eventsub   = getattr(app_state, "eventsub_manager", None)
        monitor    = getattr(app_state, "stream_monitor", None)

        db_status     = "🟢 Connected"   if db_ok    else "🔴 Offline"
        redis_status  = "🟢 Active"      if redis_ok  else "🟡 In-Memory"
        twitch_status = "🟢 Ready"       if twitch_ok else "🔴 Error"

        eventsub_status = (
            "🟢 Active"    if eventsub and eventsub.callback_url else
            "🟡 No callback URL" if eventsub else
            "🔴 Not configured"
        )

        monitor_status = "🟢 Polling" if monitor and monitor._running else "🔴 Stopped"

        # ── Uptime ─────────────────────────────────────────────────────────
        start_time = getattr(bot, "start_time", None)
        uptime_str = _fmt_uptime(start_time) if start_time else "Unknown"

        # ── Tracked streamers ──────────────────────────────────────────────
        streamer_count = 0
        live_count     = 0
        try:
            rows = await app_state.db.fetch("SELECT COUNT(*) AS n FROM streamers")
            streamer_count = rows[0]["n"] if rows else 0
        except Exception:
            pass

        if monitor and hasattr(monitor, "_state"):
            live_count = sum(1 for st in monitor._state.values() if st.get("live"))

        # ── EventSub callback URL ──────────────────────────────────────────
        callback_url = getattr(eventsub, "callback_url", None) or "—"

        # ── Build embed ────────────────────────────────────────────────────
        all_ok = db_ok and redis_ok and twitch_ok and bool(eventsub)
        embed = discord.Embed(
            title="🧪 Curie Laboratory Status",
            description=(
                "All systems nominal. Vibes: Very Cool." if all_ok
                else "⚠️ One or more systems need attention."
            ),
            color=KEVY_PINK if all_ok else 0xF5A623,
        )

        # Row 1: core services
        embed.add_field(name="📊 Database",   value=db_status,      inline=True)
        embed.add_field(name="🧠 Redis",      value=redis_status,   inline=True)
        embed.add_field(name="📺 Twitch API", value=twitch_status,  inline=True)

        # Row 2: stream systems
        embed.add_field(name="📡 EventSub",   value=eventsub_status, inline=True)
        embed.add_field(name="🔄 Monitor",    value=monitor_status,  inline=True)
        embed.add_field(name="\u200b",        value="\u200b",         inline=True)

        # Row 3: stats
        embed.add_field(name="⏱️ Uptime",     value=uptime_str,                   inline=True)
        embed.add_field(name="📶 Latency",    value=f"{round(bot.latency*1000)}ms", inline=True)
        embed.add_field(name="🏘️ Guilds",     value=str(len(bot.guilds)),           inline=True)

        # Row 4: streamer info
        embed.add_field(
            name="👥 Tracked streamers",
            value=f"{streamer_count} total · {live_count} live now",
            inline=True,
        )
        embed.add_field(
            name="🔗 EventSub callback",
            value=f"`{callback_url}`" if callback_url != "—" else "—",
            inline=False,
        )

        embed.set_footer(text="Find a Curie • Restricted Access")
        embed.timestamp = discord.utils.utcnow()

        await interaction.followup.send(embed=embed, ephemeral=True)

    logger.info("/curie_status registered")
