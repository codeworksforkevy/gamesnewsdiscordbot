import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
import time
from datetime import datetime, timezone

# Ensure you have 'google-generativeai' installed (pip install google-generativeai)
# NOTE: This library is deprecated. Please migrate to 'google-genai' as per your logs.
try:
    import google.generativeai as genai
    HAS_AI = True
except ImportError:
    HAS_AI = False

logger = logging.getLogger("live-commands")

# ==================================================
# AI MESSAGE GENERATOR
# ==================================================

async def generate_offline_message(streamer_name: str, duration_mins: int) -> str:
    """Generates a short, AI-assisted offline message using Gemini."""
    fallback_msg = f"{streamer_name} had a great stream today, thanks to everyone who tuned in! 💻"
    
    if not HAS_AI:
        return fallback_msg
    
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"Twitch streamer {streamer_name} was live for {duration_mins} minutes and "
            f"just went offline. Write a very short (1-2 sentences) farewell message for their Discord community "
            f"that is friendly, appreciative, and uses computer/tech-related emojis (💻, 🧑‍💻). "
            f"Provide only the text, no quotes."
        )
        
        # Execute synchronous AI call in an executor thread to avoid event loop blocking
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, model.generate_content, prompt)
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
            announce_channel_id = config.get("announce_channel_id")
            if announce_channel_id:
                channel = self.bot.get_channel(announce_channel_id)
                if channel:
                    await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send offline message for {login}: {e}")

        msg_key = f"stream:msg:{login}:{guild_id}"
        try:
            await self.bot.app_state.redis.delete(msg_key)
            logger.info(f"Cleared Redis cache for {login} in guild {guild_id}.")
        except Exception as e:
            logger.error(f"Failed to delete Redis key {msg_key}: {e}")

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

            display_name = user_data.get("display_name", username_clean)
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO streamers (twitch_login, is_live) VALUES ($1, FALSE) "
                    "ON CONFLICT (twitch_login) DO NOTHING",
                    username_clean
                )
            
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
            from db.guild_settings import get_guild_config
            config = await get_guild_config(interaction.guild_id)
            announce_channel_id = config.get("announce_channel_id")
            
            if announce_channel_id:
                channel = self.bot.get_channel(announce_channel_id)
                if channel:
                    sent_msg = await channel.send(embed=embed)
                    msg_key = f"stream:msg:{username_clean}:{interaction.guild_id}"
                    await self.bot.app_state.redis.set(msg_key, str(sent_msg.id))
                    await interaction.followup.send(f"🚀 Live feed bypass executed for **{username_clean}** in <#{announce_channel_id}>.")
                    return
            
            await interaction.followup.send("❌ Target destination communication pipeline channel context missing for this server.")
        except Exception as e:
            logger.error(f"Bypass injection sequence failed for {username_clean}: {e}", exc_info=True)
            await interaction.followup.send("❌ Error forcing stream validation context processing.")

    @app_commands.command(name="live_stats", description="Scans for active streams and posts any missed announcements.")
    @app_commands.default_permissions(administrator=True)
    async def live_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                live_streamers = await conn.fetch("SELECT * FROM streamers WHERE is_live = TRUE")

            recovered_count = 0
            for streamer in live_streamers:
                login = streamer["twitch_login"]
                msg_key = f"stream:msg:{login}:{interaction.guild_id}"
                has_posted = await self.bot.app_state.redis.get(msg_key)
                
                if not has_posted:
                    stream_data = await self.bot.app_state.twitch_api.get_stream_metadata(login)
                    
                    if hasattr(self.bot.app_state.twitch_api, "get_user"):
                        user_data = await self.bot.app_state.twitch_api.get_user(login)
                    else:
                        users = await self.bot.app_state.twitch_api.get_users_by_logins([login])
                        user_data = users.get(login)

                    if stream_data and user_data:
                        embed = build_live_embed(stream_data, user_data)
                        from db.guild_settings import get_guild_config
                        config = await get_guild_config(interaction.guild_id)
                        announce_channel_id = config.get("announce_channel_id")
                        if announce_channel_id:
                            channel = self.bot.get_channel(announce_channel_id)
                            if channel:
                                sent_msg = await channel.send(embed=embed)
                                await self.bot.app_state.redis.set(msg_key, str(sent_msg.id))
                                recovered_count += 1
            
            if recovered_count > 0:
                await interaction.followup.send(f"📡 Scan complete. Sent AI-supported announcements for **{recovered_count}** missed stream(s)!")
            else:
                await interaction.followup.send("✅ All active streams are already announced. No missed streams found.")

        except Exception as e:
            logger.error(f"live_stats failed: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred during the scan.")

# Required entry point for the injection framework loader
async def register(bot, app_state, session):
    # Only register if the cog isn't already loaded
    if bot.get_cog("LiveCommandsCog") is None:
        await bot.add_cog(LiveCommandsCog(bot))
        logger.info("commands.live_commands group pipeline loaded successfully.")
    else:
        logger.info("LiveCommandsCog already loaded, skipping registration.")

# FIXED: Required setup function for discord.py extension loading
async def setup(bot):
    await bot.add_cog(LiveCommandsCog(bot))
    logger.info("commands.live_commands extension setup complete.")
