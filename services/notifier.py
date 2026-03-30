import logging
import asyncio
import json
import hashlib
from typing import List, Dict, Any, Optional
 
import discord
 
from core.event_bus import event_bus
from db.guild_settings import get_guild_config
 
logger = logging.getLogger("notifier")
 
 
# ==================================================
# UTILS
# ==================================================
 
def hash_games(games: List[Dict[str, Any]]) -> str:
    """
    Deterministic SHA-256 hash for deduplication.
    Sorted keys ensure the same games always produce the same hash
    regardless of dict ordering.
    """
    payload = json.dumps(games, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
 
 
async def retry_async(func, retries: int = 3, delay: int = 2):
    """
    Exponential backoff retry wrapper.
    Raises the last exception if all attempts fail.
    """
    last_error = None
    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            wait = delay * (2 ** attempt)
            logger.warning(f"Retry {attempt + 1}/{retries} failed: {e} — waiting {wait}s")
            await asyncio.sleep(wait)
    raise RuntimeError(f"Max retries exceeded after {retries} attempts: {last_error}")
 
 
def build_embed(game: Dict[str, Any]) -> discord.Embed:
    """
    Build a Discord embed from a normalised game object.
    Handles missing fields gracefully.
    """
    title = game.get("title") or game.get("name") or "Unknown Game"
    platform = game.get("platform") or "Unknown Platform"
    url = game.get("url")
    thumbnail = game.get("thumbnail") or game.get("image")
 
    embed = discord.Embed(
        title=title,
        url=url,
        description=f"🎮 Free on **{platform}**",
        color=0x2ECC71,
    )
 
    if thumbnail:
        embed.set_image(url=thumbnail)
 
    return embed
 
 
# ==================================================
# NOTIFIER STATE
# ==================================================
 
class NotifierState:
    """
    Lightweight runtime state for deduplication.
    One instance per process — not shared across Railway restarts.
    """
    def __init__(self):
        self.last_hash: Optional[str] = None
 
 
# Module-level singleton
state = NotifierState()
 
 
# ==================================================
# CORE HANDLER
# ==================================================
 
async def notify_discord(
    bot: discord.Client,
    games: List[Dict[str, Any]],
    redis=None,           # kept for call-site compatibility, not used here
) -> None:
    """
    Public entry point — called directly from main.py's event handler.
    Delegates to handle_free_games.
    """
    await handle_free_games(bot, games)
 
 
async def handle_free_games(
    bot: discord.Client,
    games: List[Dict[str, Any]],
) -> None:
    """
    Main notification handler.
 
    - Deduplicates using a SHA-256 hash of the game list.
    - Sends embeds in chunks of 10 (Discord API limit).
    - Logs per-guild failures without crashing the whole loop.
    """
    if not games:
        logger.info("handle_free_games called with empty list — skipping")
        return
 
    # ── Deduplication ──────────────────────────────────────────────────────
    current_hash = hash_games(games)
    if state.last_hash == current_hash:
        logger.info("Duplicate game list detected — skipping notification")
        return
    state.last_hash = current_hash
 
    logger.info(f"Notifying {len(bot.guilds)} guild(s) about {len(games)} new game(s)")

    # ── Per-guild dispatch with platform filtering ─────────────────────────
    for guild in bot.guilds:
        try:
            config = await get_guild_config(guild.id)
            if not config:
                logger.debug(f"No config for guild {guild.name} — skipping")
                continue

            channel_id = config.get("games_channel_id") or config.get("announce_channel_id")
            if not channel_id:
                logger.debug(f"No games channel for guild {guild.name} — skipping")
                continue

            # ── Filter by per-guild platform toggles ──────────────────────
            enable_epic  = config.get("enable_epic",  True)
            enable_gog   = config.get("enable_gog",   True)
            enable_steam = config.get("enable_steam", True)

            filtered = [
                g for g in games
                if not (
                    (g.get("platform", "").lower() == "epic"  and not enable_epic)  or
                    (g.get("platform", "").lower() == "gog"   and not enable_gog)   or
                    (g.get("platform", "").lower() == "steam" and not enable_steam)
                )
            ]

            if not filtered:
                logger.debug(f"All games filtered for guild {guild.name} — skipping")
                continue

            count   = len(filtered)
            label   = "game" if count == 1 else "games"
            summary = f"🔥 {count} new free {label} available!"
            embeds  = [build_embed(g) for g in filtered]

            channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found in {guild.name}")
                continue

            for i in range(0, len(embeds), 10):
                chunk = embeds[i:i + 10]
                await retry_async(lambda c=chunk: channel.send(embeds=c))

            await retry_async(lambda: channel.send(summary))
            logger.info(f"✅ Notified {guild.name} — {count} {label}")
 
        except discord.Forbidden:
            logger.error(
                f"Missing permissions to post in channel {channel_id} "
                f"(guild {guild.id} — {guild.name})"
            )
        except discord.HTTPException as e:
            logger.error(f"Discord HTTP error for guild {guild.id}: {e.status} {e.text}")
        except Exception as e:
            logger.exception(f"Unexpected error for guild {guild.id} ({guild.name}): {e}")
 
 
# ==================================================
# EVENT BUS REGISTRATION
# ==================================================
 
def register_notifier(bot: discord.Client) -> None:
    """
    Subscribe handle_free_games to the 'free_games_fetched' event bus topic.
    Call this once during bot startup.
    """
    async def _handler(games: List[Dict[str, Any]]) -> None:
        await handle_free_games(bot, games)
 
    event_bus.subscribe("free_games_fetched", _handler)
    logger.info("Notifier registered on event bus")
