# commands/schedule_command.py
#
# 📅 Stream Schedule — Suggestion #12
#
# /schedule <streamer>  → shows upcoming scheduled streams with Discord timestamps
# /schedule             → shows schedule for ALL tracked streamers in this server

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands

logger = logging.getLogger("schedule-command")


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

async def _fetch_schedule(api, user_login: str) -> list[dict]:
    """
    Fetches upcoming stream schedule segments for a broadcaster.
    Returns a list of schedule entries (up to 5 next streams).
    """
    try:
        user = await api.get_user_by_login(user_login)
        if not user:
            return []

        data = await api.request(
            "schedule",
            params={
                "broadcaster_id": user["id"],
                "first":          5,
            },
        )

        if not data:
            return []

        segments = data.get("data", {}).get("segments", [])
        broadcaster_name = data.get("data", {}).get("broadcaster_name", user_login)
        profile_image    = user.get("profile_image_url", "")

        results = []
        now     = datetime.now(timezone.utc)

        for seg in segments:
            start_str = seg.get("start_time", "")
            end_str   = seg.get("end_time", "")

            try:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if start < now:
                    continue  # skip past entries
            except Exception:
                continue

            end_ts = None
            if end_str:
                try:
                    end    = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    end_ts = int(end.timestamp())
                except Exception:
                    pass

            results.append({
                "title":          seg.get("title") or "Untitled stream",
                "category":       seg.get("category", {}).get("name") if seg.get("category") else "TBA",
                "start_ts":       int(start.timestamp()),
                "end_ts":         end_ts,
                "canceled":       seg.get("canceled_until") is not None,
                "recurring":      seg.get("is_recurring", False),
                "broadcaster":    broadcaster_name,
                "user_login":     user_login,
                "profile_image":  profile_image,
            })

        return results

    except Exception as e:
        logger.warning(f"Schedule fetch failed for {user_login}: {e}")
        return []


def _build_schedule_embed(
    segments:   list[dict],
    user_login: str,
    user_name:  str,
    profile_image: str = "",
) -> discord.Embed:

    embed = discord.Embed(
        title=f"📅 Stream Schedule — {user_name}",
        url=f"https://twitch.tv/{user_login}/schedule",
        color=0x9146FF,
    )

    if profile_image:
        embed.set_author(
            name=user_name,
            url=f"https://twitch.tv/{user_login}",
            icon_url=profile_image,
        )

    if not segments:
        embed.description = (
            "😔 No upcoming streams scheduled.\n"
            f"Check [their channel]( https://twitch.tv/{user_login}/schedule) for updates."
        )
        embed.set_footer(text="📅 Schedule • Find a Curie")
        return embed

    for seg in segments[:5]:
        name_parts = []
        if seg["canceled"]:
            name_parts.append("~~")
        name_parts.append(f"<t:{seg['start_ts']}:F>")
        if seg["canceled"]:
            name_parts.append("~~ ❌ Cancelled")

        field_name = "".join(name_parts)

        value_lines = [
            f"🎮 {seg['category']}",
            f"📝 {seg['title']}",
        ]

        if seg["end_ts"]:
            value_lines.append(f"⏰ Until <t:{seg['end_ts']}:t>")

        if seg["recurring"]:
            value_lines.append("🔁 Recurring")

        value_lines.append(f"⏱️ <t:{seg['start_ts']}:R>")

        embed.add_field(
            name=field_name,
            value="\n".join(value_lines),
            inline=False,
        )

    embed.set_footer(text="📅 Schedule • Find a Curie")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _build_multi_schedule_embed(
    all_segments: list[tuple[str, str, list[dict]]],
) -> discord.Embed:
    """Build a combined schedule embed for all tracked streamers."""
    embed = discord.Embed(
        title="📅 Upcoming Streams",
        color=0x9146FF,
        description="Scheduled streams from all tracked streamers in this server.",
    )

    found_any = False

    for user_login, user_name, segments in all_segments:
        if not segments:
            continue

        found_any = True
        next_stream = segments[0]
        cancelled   = " ❌" if next_stream["canceled"] else ""

        value = (
            f"<t:{next_stream['start_ts']}:F> (<t:{next_stream['start_ts']}:R>){cancelled}\n"
            f"🎮 {next_stream['category']} • 📝 {next_stream['title']}"
        )

        embed.add_field(
            name=f"[{user_name}](https://twitch.tv/{user_login})",
            value=value,
            inline=False,
        )

    if not found_any:
        embed.description = "😔 No upcoming streams scheduled for any tracked streamers."

    embed.set_footer(text="📅 Schedule • Find a Curie")
    embed.timestamp = discord.utils.utcnow()
    return embed


# ──────────────────────────────────────────────────────────────
# REGISTER
# ──────────────────────────────────────────────────────────────

async def register(bot, app_state, session):

    @bot.tree.command(
        name="schedule",
        description="📅 Show upcoming scheduled streams",
    )
    @app_commands.describe(
        streamer="Twitch username — leave empty to see all tracked streamers",
    )
    async def schedule_command(
        interaction: discord.Interaction,
        streamer: str | None = None,
    ):
        await interaction.response.defer()

        api = app_state.twitch_api
        if not api:
            await interaction.followup.send("❌ Twitch API not available.", ephemeral=True)
            return

        # ── Single streamer ──────────────────────────────────────
        if streamer:
            login = streamer.strip().lower()

            # Must be in tracked list for this server
            try:
                row = await app_state.db.fetchrow(
                    "SELECT 1 FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                    login, interaction.guild_id,
                )
                if not row:
                    rows = await app_state.db.fetch(
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
                logger.warning(f"/schedule DB check failed: {e}")

            user     = await api.get_user_by_login(login)
            segments = await _fetch_schedule(api, login)

            if user is None:
                await interaction.followup.send(
                    f"❌ Twitch user **{login}** not found.", ephemeral=True
                )
                return

            embed = _build_schedule_embed(
                segments,
                login,
                user.get("display_name", login),
                user.get("profile_image_url", ""),
            )
            await interaction.followup.send(embed=embed)
            return

        # ── All tracked streamers ────────────────────────────────
        try:
            rows = await app_state.db.fetch(
                """
                SELECT DISTINCT twitch_user_id, twitch_login
                FROM streamers
                WHERE guild_id = $1
                """,
                interaction.guild_id,
            )
        except Exception as e:
            await interaction.followup.send("❌ Database error.", ephemeral=True)
            return

        if not rows:
            await interaction.followup.send(
                "📭 No streamers tracked yet. Use `/live add` to add one!",
                ephemeral=True,
            )
            return

        all_segments = []
        for row in rows:
            login    = row["twitch_login"]
            user     = await api.get_user_by_login(login)
            segments = await _fetch_schedule(api, login)
            name     = user.get("display_name", login) if user else login
            all_segments.append((login, name, segments))

        # Sort by next stream time
        def next_start(entry):
            segs = entry[2]
            return segs[0]["start_ts"] if segs else float("inf")

        all_segments.sort(key=next_start)

        embed = _build_multi_schedule_embed(all_segments)
        await interaction.followup.send(embed=embed)
        logger.info(
            f"/schedule (all) in {interaction.guild.name} — "
            f"{len(all_segments)} streamers checked"
        )
