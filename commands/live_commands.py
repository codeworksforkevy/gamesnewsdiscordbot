# commands/live_commands.py

import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
import time
from datetime import datetime, timezone

# Ensure you have 'google-generativeai' installed (pip install google-generativeai)
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
    """Generates a short, AI-assisted offline message."""
    fallback_msg = f"{streamer_name} had a great stream today, thanks to everyone who tuned in! 💻"
    
    if not HAS_AI:
        return fallback_msg

    # Note: Make sure to configure your API key securely (e.g., in main.py or via env vars).
    # genai.configure(api_key="YOUR_API_KEY") 
    
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        # English prompt tailored for the desired Emoji UX and tone
        prompt = (
            f"Twitch streamer {streamer_name} was live for {duration_mins} minutes and "
            f"just went offline. Write a very short (1-2 sentences) farewell message for their Discord community "
            f"that is friendly, appreciative, and uses computer/tech-related emojis (💻, 🧑‍💻). "
            f"Provide only the text, no quotes."
        )
        
        # Run the synchronous AI call in an executor to avoid blocking the bot's event loop
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
    login      = stream.get("user_login") or user.get("login", "unknown")
    name       = stream.get("user_name")  or user.get("display_name", login)
    title      = stream.get("title", "") or ""
    game       = stream.get("game_name", "") or "Just Chatting"
    started_at = stream.get("started_at", "")
    stream_url = f"https://www.twitch.tv/{login}"

    if not game or game.lower() in ("unknown", "unknown game", ""):
        game = "Just Chatting"

    ts_str = "now"
    if started_at:
        try:
            dt     = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
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

    # Convert the dynamic thumbnail URL to a fixed resolution
    raw_thumb = stream.get("thumbnail_url", "")
    thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
    if thumbnail:
        # Appending time prevents Discord from caching an old thumbnail
        embed.set_image(url=f"{thumbnail}?v={int(time.time())}")

    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed

async def build_offline_embed(
    login:        str,
    display_name: str,
    duration_mins: int,
    stream_info:  dict | None = None,
    vod_url:      str  | None = None,
    user_info:    dict | None = None,
) -> discord.Embed:
    """Constructs the offline embed using AI-generated text and Emoji UX."""
    
    # Generate the dynamic farewell message
    ai_text = await generate_offline_message(display_name, duration_mins)

    # Darker color palette (Navy) combined with the tech emoji UX
    embed = discord.Embed(
        title=f"🧑‍💻 {display_name} has stepped away from the keyboard!",
        description=ai_text,
        color=0x1C1C2E, 
    )

    icon_url = user_info.get("profile_image_url") if user_info else None
    if icon_url:
        embed.set_thumbnail(url=icon_url)

    # Attach the VOD (Video on Demand) link if available
    if vod_url:
        embed.add_field(
            name="📼 Missed it?",
            value=f"💿 [Watch the past broadcast (VOD) here]({vod_url})",
            inline=False
        )
    else:
        embed.add_field(
            name="📼 VOD",
            value=f"💿 [All Videos](https://www.twitch.tv/{login}/videos)",
            inline=False
        )

    embed.set_footer(text=f"Stream ended • twitch.tv/{login}")
    embed.timestamp = datetime.now(timezone.utc)
    return embed

# ==================================================
# COGS & COMMANDS
# ==================================================

class LiveCommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="live_stats", description="Scans for active streams and posts any missed announcements.")
    async def live_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        
        try:
            # 1. Fetch currently live streamers from the database
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                live_streamers = await conn.fetch("SELECT * FROM streamers WHERE is_live = TRUE")

            recovered_count = 0
            
            for streamer in live_streamers:
                login = streamer["twitch_login"]
                
                # 2. Check Redis to see if an announcement message ID already exists for this guild
                msg_key = f"stream:msg:{login}:{interaction.guild_id}"
                has_posted = await self.bot.app_state.redis.get(msg_key)
                
                # 3. If they are live but no announcement was posted, force it
                if not has_posted:
                    # Fetch fresh data from Twitch API to build the embed
                    stream_data = await self.bot.app_state.twitch_api.get_stream(login)
                    user_data = await self.bot.app_state.twitch_api.get_user(login)
                    
                    if stream_data and user_data:
                        embed = build_live_embed(stream_data, user_data)
                        
                        # Find the designated announcement channel from guild configurations
                        from db.guild_settings import get_guild_config
                        config = await get_guild_config(interaction.guild_id)
                        announce_channel_id = config.get("announce_channel_id")
                        
                        if announce_channel_id:
                            channel = self.bot.get_channel(announce_channel_id)
                            if channel:
                                sent_msg = await channel.send(embed=embed)
                                # Update Redis state to prevent duplicate posts
                                await self.bot.app_state.redis.set(msg_key, str(sent_msg.id))
                                recovered_count += 1
            
            # Final report to the user invoking the command
            if recovered_count > 0:
                await interaction.followup.send(f"📡 Scan complete. Sent AI-supported announcements for **{recovered_count}** missed stream(s)!")
            else:
                await interaction.followup.send("✅ All active streams are already announced. No missed streams found.")

        except Exception as e:
            logger.error(f"live_stats failed: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred during the scan. Please check the logs.")


async def setup(bot):
    await bot.add_cog(LiveCommandsCog(bot))
    logger.info("LiveCommandsCog loaded successfully.")
