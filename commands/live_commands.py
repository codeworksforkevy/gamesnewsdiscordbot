import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
import time
import os
from datetime import datetime, timezone

# Migration to 'google-genai'
try:
    from google import genai
    HAS_AI = True
except ImportError:
    HAS_AI = False

logger = logging.getLogger("live-commands")

# ──────────────────────────────────────────────────────────────
# KNOWN STREAMERS — source of truth for KevKevvy's Plaza
# Pulled from the `streamers` DB table on 2026-07-13.
# Add new streamers here AND run /live add so EventSub subscribes.
# ──────────────────────────────────────────────────────────────
GUILD_ID = 1446560723122520207
ANNOUNCE_CHANNEL_ID = 1446562626695074006

KNOWN_STREAMERS: dict[str, str] = {
    # login               twitch_user_id
    "pancitplease":      "766528698",
    "mkaybecca":         "233809759",
    "frasedisplays":     "54088839",
    "mirellemistlight":  "786543297",
    "eziverse":          "617198890",
    "bigbootykennyx":    "481101604",
    "ellefyi":           "639451042",
    "niiaaah":           "1041575461",
    "mousey2975":        "231954099",
    "amble_may2002":     "623178384",
    "r1sky_90":          "84534136",
    "cxrrinajxyne":      "535859139",
    "realgirlsdontgame": "535406506",
    "keats___":          "256599363",
    "neledraaa":         "555678290",   # was missing from DB — seeded at startup
}


async def seed_known_streamers(db_pool) -> None:
    """
    Ensures every entry in KNOWN_STREAMERS exists in the DB.
    Idempotent — safe to call on every startup.
    """
    inserted = 0
    async with db_pool.acquire() as conn:
        for login, user_id in KNOWN_STREAMERS.items():
            result = await conn.execute(
                """
                INSERT INTO streamers (guild_id, twitch_user_id, twitch_login)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, twitch_login) DO NOTHING
                """,
                GUILD_ID, user_id, login,
            )
            if result == "INSERT 0 1":
                inserted += 1
    if inserted:
        logger.info(f"seed_known_streamers: inserted {inserted} missing streamer(s) into DB.")
    else:
        logger.info("seed_known_streamers: all known streamers already in DB.")

# ==================================================
# AI MESSAGE GENERATOR
# ==================================================

async def generate_offline_message(streamer_name: str, duration_mins: int) -> str:
    """Generates a short, AI-assisted offline message using the new Gemini client."""
    fallback_msg = f"{streamer_name} had a great stream today, thanks to everyone who tuned in! 💻"
    
    if not HAS_AI:
        return fallback_msg
    
    try:
        # Initialize client - requires GEMINI_API_KEY env var
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        
        prompt = (
            f"Twitch streamer {streamer_name} was live for {duration_mins} minutes and "
            f"just went offline. Write a very short (1-2 sentences) farewell message for their Discord community "
            f"that is friendly, appreciative, and uses computer/tech-related emojis (💻, 🧑‍💻). "
            f"Provide only the text, no quotes."
        )
        
        # Execute synchronous AI call in an executor thread to avoid event loop blocking
        loop = asyncio.get_running_loop()
        
        # Wrapped in a lambda to handle the new client method signature
        response = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt
            )
        )
        
        return response.text.strip()
    except Exception as e:
        logger.error(f"AI text generation failed: {e}")
        return fallback_msg

# ==================================================
# EMBED BUILDERS
# ==================================================

def build_live_embed(stream: dict, user: dict) -> discord.Embed:
    """Constructs the embed sent when a streamer goes live."""
    login    = stream.get("user_login") or user.get("login", "unknown")
    name     = stream.get("user_name")  or user.get("display_name", login)
    title    = stream.get("title", "") or ""
    game     = stream.get("game_name", "") or "Just Chatting"
    started_at = stream.get("started_at", "")
    stream_url = f"https://www.twitch.tv/{login}"

    if not game or game.lower() in ("unknown", "unknown game", ""):
        game = "Just Chatting"

    ts_str = "now"
    if started_at:
        try:
            dt   = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts_str = f"<t:{int(dt.timestamp())}:R>"
        except Exception:
            pass

    embed = discord.Embed(
        url=stream_url,
        description=title if title else None,
        color=0xFFB6C1, # Baby pink
    )

    embed.set_author(
        name=f"🔴 {name} is live!",
        url=stream_url,
        icon_url=user.get("profile_image_url"),
    )

    profile_url = user.get("profile_image_url")
    if profile_url:
        embed.set_thumbnail(url=profile_url)

    embed.add_field(name="🕹️ Game",   value=game,   inline=True)
    embed.add_field(name="☕ Started", value=ts_str, inline=True)

    raw_thumb = stream.get("thumbnail_url", "")
    thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
    if thumbnail:
        embed.set_image(url=f"{thumbnail}?v={int(time.time())}")

    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed

async def build_offline_embed(
    login: str,
    display_name: str,
    duration_mins: int,
    vod_url: str | None = None,
    user_info: dict | None = None,
) -> discord.Embed:
    """Constructs the offline embed using AI-generated text and VOD routing."""
    ai_text = await generate_offline_message(display_name, duration_mins)

    embed = discord.Embed(
        title=f"🧑‍💻 {display_name} has stepped away from the keyboard!",
        description=ai_text,
        color=0x1C1C2E, 
    )

    icon_url = user_info.get("profile_image_url") if user_info else None
    if icon_url:
        embed.set_thumbnail(url=icon_url)

    # VOD Routing: Directs users to the specific VOD if available, or the general videos page
    if vod_url:
        embed.add_field(name="📼 Missed it?", value=f"💿 [Watch the past broadcast (VOD) here]({vod_url})", inline=False)
    else:
        embed.add_field(name="📼 Missed it?", value=f"💿 [Check out their recent broadcasts here](https://www.twitch.tv/{login}/videos)", inline=False)

    embed.set_footer(text=f"Stream ended • twitch.tv/{login}")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

# ==================================================
# COGS & COMMANDS
# ==================================================

class LiveCommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Base application command group for /live, strictly locked to Administrators
    live_group = app_commands.Group(
        name="live", 
        description="Twitch stream subscription and management tools",
        default_permissions=discord.Permissions(administrator=True)
    )

    @commands.Cog.listener()
    async def on_stream_offline(self, user_id: str, login: str, display_name: str, duration_mins: int, guild_id: int):
        """Handles the stream offline event, fetches VOD, and clears cache."""
        await asyncio.sleep(15) 
        
        vod_url = None
        try:
            if hasattr(self.bot.app_state.twitch_api, "get_videos"):
                videos = await self.bot.app_state.twitch_api.get_videos(user_id=user_id, video_type="archive", first=1)
                if videos:
                    vod_url = videos[0].get("url")
        except Exception as e:
            logger.error(f"Failed to fetch VOD for {login}: {e}")

        embed = await build_offline_embed(login=login, display_name=display_name, duration_mins=duration_mins, vod_url=vod_url)

        try:
            from db.guild_settings import get_guild_config
            config = await get_guild_config(guild_id)
            announce_channel_id = (
                config.get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            )
            channel = self.bot.get_channel(announce_channel_id)
            if channel:
                await channel.send(embed=embed)
            else:
                logger.warning(f"Announce channel {announce_channel_id} not found for {login}")
        except Exception as e:
            logger.error(f"Failed to send offline message for {login}: {e}")

        # ── Update DB: mark streamer as offline ──────────────────
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE streamers
                    SET is_live = FALSE, last_updated = NOW()
                    WHERE twitch_login = $1 AND guild_id = $2
                    """,
                    login, guild_id,
                )
        except Exception as e:
            logger.error(f"Failed to update is_live=FALSE for {login}: {e}")

        # ── Clear Redis keys ─────────────────────────────────────
        msg_key    = f"stream:msg:{login}:{guild_id}"
        status_key = f"stream:status:{login}"
        try:
            await self.bot.app_state.redis.delete(msg_key)
            await self.bot.app_state.redis.delete(status_key)
            logger.info(f"Cleared Redis cache for {login} in guild {guild_id}.")
        except Exception as e:
            logger.error(f"Failed to delete Redis keys for {login}: {e}")

    # ──────────────────────────────────────────────────────────
    # SUBCOMMANDS
    # ──────────────────────────────────────────────────────────

    @live_group.command(name="add", description="Add a Twitch streamer to the system tracking list.")
    @app_commands.describe(username="The Twitch login username of the streamer to add")
    async def live_add(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        username_clean = username.lower().strip()
        try:
            twitch_api = self.bot.app_state.twitch_api
            if hasattr(twitch_api, "get_user"):
                user_data = await twitch_api.get_user(username_clean)
            else:
                users = await twitch_api.get_users_by_logins([username_clean])
                user_data = users.get(username_clean)

            if not user_data:
                await interaction.followup.send(f"❌ Twitch user `{username_clean}` could not be verified or found.")
                return

            display_name   = user_data.get("display_name", username_clean)
            twitch_user_id = user_data.get("id", KNOWN_STREAMERS.get(username_clean, ""))
            guild_id       = interaction.guild_id or GUILD_ID

            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO streamers (guild_id, twitch_user_id, twitch_login)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (guild_id, twitch_login) DO NOTHING
                    """,
                    guild_id, twitch_user_id, username_clean,
                )

            # Trigger EventSub subscription for the new streamer
            from core.event_bus import event_bus
            await event_bus.publish("streamer_added", {
                "twitch_user_id": twitch_user_id,
                "twitch_login":   username_clean,
                "guild_id":       guild_id,
            })

            await interaction.followup.send(f"✅ Successfully added **{display_name}** (`{username_clean}`) to the tracking list!")
        except Exception as e:
            logger.error(f"Failed to add streamer {username_clean}: {e}", exc_info=True)
            await interaction.followup.send("❌ An unexpected database error occurred while adding the record.")

    @live_group.command(name="remove", description="Remove a Twitch streamer from the system tracking list.")
    @app_commands.describe(username="The Twitch login username of the streamer to remove")
    async def live_remove(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        username_clean = username.lower().strip()
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM streamers WHERE twitch_login = $1", username_clean)
            
            msg_key = f"stream:msg:{username_clean}:{interaction.guild_id}"
            status_key = f"stream:status:{username_clean}"
            await self.bot.app_state.redis.delete(msg_key)
            await self.bot.app_state.redis.delete(status_key)

            await interaction.followup.send(f"🗑️ Removed `{username_clean}` from tracked profiles and cleared related server caches.")
        except Exception as e:
            logger.error(f"Failed to remove streamer {username_clean}: {e}", exc_info=True)
            await interaction.followup.send("❌ An operational error occurred during deletion.")

    @live_group.command(name="list", description="List all Twitch streamers currently registered in the database.")
    async def live_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT twitch_login, is_live FROM streamers ORDER BY twitch_login ASC")
            
            if not rows:
                await interaction.followup.send("💤 The subscription database is completely empty.")
                return

            embed = discord.Embed(
                title="📡 Monitored Twitch Channels",
                color=0xFFB6C1,
                timestamp=discord.utils.utcnow()
            )
            
            lines = [
                f"• [{row['twitch_login']}](https://www.twitch.tv/{row['twitch_login']}) — "
                f"{'🔴 **LIVE**' if row['is_live'] else '💤 Offline'}"
                for row in rows
            ]
            
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"Total Registrations: {len(rows)}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to build tracking overview array list: {e}", exc_info=True)
            await interaction.followup.send("❌ Internal tracking compilation query failed.")

    @live_group.command(name="force", description="Force an immediate live announcement card bypass for an active channel.")
    @app_commands.describe(username="The target Twitch login name to pull and execute an announcement for")
    async def live_force(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        username_clean = username.lower().strip()
        try:
            twitch_api = self.bot.app_state.twitch_api
            stream_data = await twitch_api.get_stream_metadata(username_clean)
            
            if hasattr(twitch_api, "get_user"):
                user_data = await twitch_api.get_user(username_clean)
            else:
                users = await twitch_api.get_users_by_logins([username_clean])
                user_data = users.get(username_clean)

            if not stream_data or not user_data:
                await interaction.followup.send(f"❌ `{username_clean}` is either offline or failed api evaluation lookup.")
                return

            embed = build_live_embed(stream_data, user_data)

            # Channel lookup with hardcoded fallback
            from db.guild_settings import get_guild_config
            try:
                cfg = await get_guild_config(interaction.guild_id)
                announce_channel_id = cfg.get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            except Exception:
                announce_channel_id = ANNOUNCE_CHANNEL_ID

            channel = self.bot.get_channel(announce_channel_id)
            if not channel:
                await interaction.followup.send(f"❌ Could not find announce channel ({announce_channel_id}).")
                return

            sent_msg = await channel.send(embed=embed)

            # Update Redis: message id + live status
            guild_id   = interaction.guild_id or GUILD_ID
            msg_key    = f"stream:msg:{username_clean}:{guild_id}"
            status_key = f"stream:status:{username_clean}"
            stream_id  = stream_data.get("id", "live")
            await self.bot.app_state.redis.set(msg_key, str(sent_msg.id))
            await self.bot.app_state.redis.set(status_key, stream_id, ttl=21600)

            # Update DB: mark streamer as live
            try:
                pool = self.bot.app_state.db.pool
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE streamers
                        SET is_live = TRUE,
                            title        = $2,
                            game_name    = $3,
                            viewer_count = $4,
                            last_updated = NOW()
                        WHERE twitch_login = $1 AND guild_id = $5
                        """,
                        username_clean,
                        stream_data.get("title", ""),
                        stream_data.get("game_name", ""),
                        stream_data.get("viewer_count", 0),
                        guild_id,
                    )
            except Exception as e:
                logger.error(f"live_force: DB update failed for {username_clean}: {e}")

            await interaction.followup.send(
                f"🚀 Live notification sent for **{username_clean}** in <#{announce_channel_id}>."
            )
        except Exception as e:
            logger.error(f"Bypass injection sequence failed for {username_clean}: {e}", exc_info=True)
            await interaction.followup.send("❌ Error forcing stream validation context processing.")

    @live_group.command(name="stats", description="Scans Twitch right now and posts any missed live announcements.")
    async def live_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id = interaction.guild_id or GUILD_ID

            # Pull all tracked logins from DB (fallback: KNOWN_STREAMERS)
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT twitch_login FROM streamers WHERE guild_id = $1", guild_id
                )
            db_logins = {r["twitch_login"] for r in rows}
            all_logins = list(db_logins | set(KNOWN_STREAMERS.keys()))

            if not all_logins:
                await interaction.followup.send("📭 No streamers tracked yet.")
                return

            # Ask Twitch who is actually live right now
            twitch_api   = self.bot.app_state.twitch_api
            live_streams = await twitch_api.get_streams_by_logins(all_logins)
            live_map     = {s["user_login"].lower(): s for s in live_streams}

            # Channel lookup with fallback
            from db.guild_settings import get_guild_config
            try:
                cfg = await get_guild_config(guild_id)
                announce_channel_id = cfg.get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            except Exception:
                announce_channel_id = ANNOUNCE_CHANNEL_ID

            channel = self.bot.get_channel(announce_channel_id)

            recovered = 0
            for login, stream in live_map.items():
                msg_key    = f"stream:msg:{login}:{guild_id}"
                status_key = f"stream:status:{login}"

                already_posted = await self.bot.app_state.redis.get(msg_key)
                if already_posted:
                    continue  # notification already sent this session

                # Missed EventSub — recover
                if hasattr(twitch_api, "get_user_by_login"):
                    user_data = await twitch_api.get_user_by_login(login) or {}
                elif hasattr(twitch_api, "get_user"):
                    user_data = await twitch_api.get_user(login) or {}
                else:
                    users     = await twitch_api.get_users_by_logins([login])
                    user_data = users.get(login, {})

                embed = build_live_embed(stream, user_data)
                if channel:
                    sent_msg = await channel.send(embed=embed)
                    await self.bot.app_state.redis.set(msg_key, str(sent_msg.id))
                    await self.bot.app_state.redis.set(status_key, stream.get("id", "live"), ttl=21600)

                # Persist live state to DB
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE streamers
                        SET is_live = TRUE, title = $2, game_name = $3,
                            viewer_count = $4, last_updated = NOW()
                        WHERE twitch_login = $1 AND guild_id = $5
                        """,
                        login,
                        stream.get("title", ""),
                        stream.get("game_name", ""),
                        stream.get("viewer_count", 0),
                        guild_id,
                    )
                recovered += 1

            if recovered:
                await interaction.followup.send(
                    f"📡 Scan complete — recovered **{recovered}** missed stream notification(s)!"
                )
            else:
                await interaction.followup.send(
                    f"✅ All {len(live_map)} live stream(s) are already announced. "
                    f"({len(all_logins) - len(live_map)} streamer(s) offline.)"
                )

# Required entry point for the injection framework loader
async def register(bot, app_state, session):
    # Only register if the cog isn't already loaded
    if bot.get_cog("LiveCommandsCog") is None:
        await bot.add_cog(LiveCommandsCog(bot))
        logger.info("commands.live_commands group pipeline loaded successfully.")
    else:
        logger.info("LiveCommandsCog already loaded, skipping registration.")

# Fixed: Required setup function for discord.py extension loading
async def setup(bot):
    await bot.add_cog(LiveCommandsCog(bot))
    logger.info("commands.live_commands extension setup complete.")
