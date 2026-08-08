import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
import time
import os
import aiohttp
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

    NOTE: the `streamers` table has no unique constraint on
    (guild_id, twitch_login), so ON CONFLICT can't be used here.
    We check-then-insert manually instead.
    """
    inserted = 0
    async with db_pool.acquire() as conn:
        for login, user_id in KNOWN_STREAMERS.items():
            exists = await conn.fetchval(
                "SELECT 1 FROM streamers WHERE guild_id = $1 AND twitch_login = $2",
                GUILD_ID, login,
            )
            if exists:
                continue
            await conn.execute(
                """
                INSERT INTO streamers (guild_id, twitch_user_id, twitch_login)
                VALUES ($1, $2, $3)
                """,
                GUILD_ID, user_id, login,
            )
            inserted += 1
    if inserted:
        logger.info(f"seed_known_streamers: inserted {inserted} missing streamer(s) into DB.")
    else:
        logger.info("seed_known_streamers: all known streamers already in DB.")


async def ensure_stream_history_table(db_pool) -> None:
    """
    Defensive safety net for the streak/consistency stats feature —
    creates stream_history if it doesn't already exist. Safe to call
    on every startup.
    """
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stream_history (
                    id            BIGSERIAL   PRIMARY KEY,
                    twitch_login  TEXT        NOT NULL,
                    guild_id      BIGINT      NOT NULL,
                    title         TEXT,
                    game_name     TEXT,
                    peak_viewers  INTEGER     DEFAULT 0,
                    started_at    TIMESTAMPTZ,
                    ended_at      TIMESTAMPTZ,
                    duration_secs INTEGER     DEFAULT 0
                );
            """)
        logger.info("ensure_stream_history_table: verified.")
    except Exception as e:
        logger.error(f"ensure_stream_history_table failed: {e}")

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

    embed.add_field(name="👩‍💻 Game",   value=game,   inline=True)
    embed.add_field(name="「」Started", value=ts_str, inline=True)

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
    title: str | None = None,
    raided_login: str | None = None,
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

    if title:
        embed.add_field(name="📝 They were streaming", value=title, inline=False)

    if raided_login:
        embed.add_field(
            name="They raided",
            value=f"[{raided_login}](https://www.twitch.tv/{raided_login})",
            inline=False,
        )

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

    async def cog_load(self) -> None:
        """Runs once when the cog is loaded — seeds any missing KNOWN_STREAMERS into the DB."""
        try:
            pool = self.bot.app_state.db.pool
            await seed_known_streamers(pool)
            await ensure_stream_history_table(pool)
        except Exception as e:
            logger.error(f"cog_load: setup failed: {e}", exc_info=True)

        # Start the mid-stream title/game change tracker
        if not hasattr(self, "_title_watch_task") or self._title_watch_task.done():
            self._title_watch_task = asyncio.create_task(self._title_change_loop())

    async def cog_unload(self) -> None:
        if hasattr(self, "_title_watch_task"):
            self._title_watch_task.cancel()

    async def _thumbnail_is_ready(self, url: str) -> bool:
        """
        Checks whether Twitch's live preview image actually exists yet,
        rather than trusting that a non-empty thumbnail_url means the image
        is real — Twitch can hand back a URL for a snapshot that hasn't
        rendered on their CDN yet, which is exactly what produces the
        'blank' thumbnail on some posts.
        """
        session = getattr(self.bot.app_state, "session", None)
        if not session:
            return True  # can't verify — don't block forever on this
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────
    # "WHO'S LIVE" DASHBOARD
    # ──────────────────────────────────────────────────────────

    async def _update_dashboard(self, guild_id: int) -> None:
        """Maintains a single, auto-updating 'who's live' message instead of a new post per event."""
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT twitch_login, game_name FROM streamers
                    WHERE guild_id = $1 AND is_live = TRUE
                    ORDER BY twitch_login ASC
                    """,
                    guild_id,
                )

            from db.guild_settings import get_guild_config
            try:
                cfg = await get_guild_config(guild_id)
                announce_channel_id = (cfg or {}).get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            except Exception:
                announce_channel_id = ANNOUNCE_CHANNEL_ID

            channel = self.bot.get_channel(announce_channel_id)
            if not channel:
                return

            if rows:
                lines = [
                    f"**[{r['twitch_login']}](https://www.twitch.tv/{r['twitch_login']})** — "
                    f"{r['game_name'] or 'Just Chatting'}"
                    for r in rows
                ]
                description = "\n".join(lines)
            else:
                description = "Nobody is live right now."

            embed = discord.Embed(
                title="Who's Live Right Now",
                description=description,
                color=0xFFB6C1,
            )
            embed.set_footer(text="Updates automatically • Find a Curie")
            embed.timestamp = discord.utils.utcnow()

            dash_key = f"dashboard:msg:{guild_id}"
            msg_id = await self.bot.app_state.redis.get(dash_key)

            if msg_id:
                try:
                    message = await channel.fetch_message(int(msg_id))
                    await message.edit(embed=embed)
                    return
                except (discord.NotFound, discord.HTTPException):
                    pass  # message gone — fall through and send a fresh one

            sent = await channel.send(embed=embed)
            await self.bot.app_state.redis.set(dash_key, str(sent.id))
        except Exception as e:
            logger.error(f"_update_dashboard failed for guild {guild_id}: {e}", exc_info=True)

    # ──────────────────────────────────────────────────────────
    # RAID DETECTION
    # ──────────────────────────────────────────────────────────
    # NOTE: nothing calls record_raid() yet. It needs to be wired to a
    # Twitch EventSub "channel.raid" subscription (the streamer as the
    # FROM broadcaster) — that subscription setup and webhook routing
    # live outside this file (eventsub_manager.py + the webhook route).

    async def record_raid(self, from_login: str, to_login: str) -> None:
        """
        Call this when a tracked streamer raids another channel. Stored
        briefly so their 'stream ended' embed can mention who they raided.
        """
        try:
            await self.bot.app_state.redis.set(
                f"raid:{from_login.lower()}", to_login.lower(), ttl=1800
            )
            logger.info(f"record_raid: {from_login} -> {to_login} recorded")
        except Exception as e:
            logger.error(f"record_raid failed: {e}")

    # ──────────────────────────────────────────────────────────
    # FIRST-FOLLOWER SHOUTOUT
    # ──────────────────────────────────────────────────────────
    # NOTE: nothing calls record_first_follower() yet. It needs a Twitch
    # EventSub "channel.follow" subscription per tracked streamer (requires
    # moderator:read:followers scope) — same missing wiring as raids.
    # Twitch's API has no concept of "first viewer" at all — viewer
    # identity is never exposed via REST or EventSub, only aggregate
    # counts — so "first follower since going live" is the closest real
    # equivalent.

    async def record_first_follower(self, login: str, follower_name: str) -> None:
        """
        Call this with the first follower since a stream went live.
        Edits the existing live announcement to add a shoutout field,
        rather than posting a separate message.
        """
        try:
            login = login.lower()
            guard_key = f"first_follower_done:{login}"
            if await self.bot.app_state.redis.get(guard_key):
                return  # already shouted out this session

            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT guild_id FROM streamers WHERE twitch_login = $1 AND is_live = TRUE LIMIT 1",
                    login,
                )
            if not row:
                return
            guild_id = row["guild_id"]

            msg_key = f"stream:msg:{login}:{guild_id}"
            msg_id = await self.bot.app_state.redis.get(msg_key)
            if not msg_id:
                return

            from db.guild_settings import get_guild_config
            try:
                cfg = await get_guild_config(guild_id)
                announce_channel_id = (cfg or {}).get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            except Exception:
                announce_channel_id = ANNOUNCE_CHANNEL_ID

            channel = self.bot.get_channel(announce_channel_id)
            if not channel:
                return

            try:
                message = await channel.fetch_message(int(msg_id))
            except (discord.NotFound, discord.HTTPException):
                return

            if not message.embeds:
                return
            embed = message.embeds[0]
            embed.add_field(name="First follower this stream", value=follower_name, inline=False)
            await message.edit(embed=embed)

            await self.bot.app_state.redis.set(guard_key, "1", ttl=21600)
            logger.info(f"record_first_follower: shoutout added for {login} -> {follower_name}")
        except Exception as e:
            logger.error(f"record_first_follower failed for {login}: {e}", exc_info=True)

    async def _title_change_loop(self):
        """Periodically checks currently-live streamers for title/game changes and edits their embed."""
        await self.bot.wait_until_ready()
        while True:
            try:
                await self._check_title_changes()
                await self._update_dashboard(GUILD_ID)
            except Exception as e:
                logger.error(f"_title_change_loop: cycle failed: {e}", exc_info=True)
            await asyncio.sleep(120)  # every 2 minutes

    async def _check_title_changes(self):
        pool = self.bot.app_state.db.pool
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT twitch_login, twitch_user_id, guild_id, title, game_name FROM streamers WHERE is_live = TRUE"
            )
        if not rows:
            return

        twitch_api = self.bot.app_state.twitch_api
        user_ids = [str(r["twitch_user_id"]) for r in rows if r["twitch_user_id"]]
        if not user_ids:
            return

        try:
            live_streams = await twitch_api.get_streams_by_ids(user_ids)
        except Exception as e:
            logger.error(f"_check_title_changes: get_streams_by_ids failed: {e}")
            return
        live_map = {s["user_login"].lower(): s for s in live_streams}

        for row in rows:
            login = row["twitch_login"]
            stream = live_map.get(login)
            if not stream:
                continue  # Twitch says offline — on_stream_offline will handle it

            new_title = stream.get("title", "") or ""
            new_game  = stream.get("game_name", "") or "Just Chatting"
            old_title = row["title"] or ""
            old_game  = row["game_name"] or ""

            if new_title == old_title and new_game == old_game:
                continue  # nothing changed

            guild_id = row["guild_id"]
            msg_key = f"stream:msg:{login}:{guild_id}"
            msg_id = await self.bot.app_state.redis.get(msg_key)
            if not msg_id:
                continue  # no tracked message to edit

            try:
                from db.guild_settings import get_guild_config
                cfg = await get_guild_config(guild_id)
                announce_channel_id = (cfg or {}).get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            except Exception:
                announce_channel_id = ANNOUNCE_CHANNEL_ID

            channel = self.bot.get_channel(announce_channel_id)
            if not channel:
                continue

            try:
                message = await channel.fetch_message(int(msg_id))
            except (discord.NotFound, discord.HTTPException):
                continue

            user_data = {}
            try:
                if hasattr(twitch_api, "get_user"):
                    user_data = await twitch_api.get_user(login) or {}
                elif hasattr(twitch_api, "get_users_by_logins"):
                    users = await twitch_api.get_users_by_logins([login])
                    user_data = users.get(login, {})
            except Exception:
                pass

            updated_embed = build_live_embed(stream, user_data)
            try:
                await message.edit(embed=updated_embed)
                logger.info(f"_check_title_changes: updated embed for {login} (title/game changed)")
            except Exception as e:
                logger.warning(f"_check_title_changes: failed to edit message for {login}: {e}")
                continue

            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE streamers
                        SET title = $2, game_name = $3,
                            viewer_count = $4, last_updated = NOW()
                        WHERE twitch_login = $1 AND guild_id = $5
                        """,
                        login, new_title, new_game,
                        stream.get("viewer_count", 0), guild_id,
                    )
            except Exception as e:
                logger.error(f"_check_title_changes: DB update failed for {login}: {e}")

    # Base application command group for /live, strictly locked to Administrators
    live_group = app_commands.Group(
        name="live", 
        description="Twitch stream subscription and management tools",
        default_permissions=discord.Permissions(administrator=True)
    )

    @commands.Cog.listener()
    async def on_stream_online(self, user_id: str, login: str, display_name: str, guild_id: int):
        """
        Handles the stream online event and posts the live announcement.
        This is the missing counterpart to on_stream_offline — without it,
        real-time 'went live' events had nowhere to be caught and posted.
        """
        try:
            twitch_api = self.bot.app_state.twitch_api

            # ── Fetch current stream data, with a retry if Twitch hasn't
            # ── fully populated title/thumbnail yet (common right when a
            # ── stream just started — the go-live webhook can arrive
            # ── before Twitch's own API reflects the full stream object).
            stream_data = None
            for attempt in range(2):
                if hasattr(twitch_api, "get_stream_metadata"):
                    stream_data = await twitch_api.get_stream_metadata(login)
                elif hasattr(twitch_api, "get_streams_by_ids"):
                    streams = await twitch_api.get_streams_by_ids([str(user_id)])
                    stream_data = streams[0] if streams else None

                if stream_data and stream_data.get("title") and stream_data.get("thumbnail_url"):
                    break  # got complete data

                if attempt == 0:
                    logger.info(
                        f"on_stream_online: incomplete stream data for {login} "
                        f"(missing title/thumbnail) — retrying in 8s"
                    )
                    await asyncio.sleep(8)

            if not stream_data:
                logger.warning(f"on_stream_online: no live stream data found for {login}, skipping.")
                return

            if hasattr(twitch_api, "get_user"):
                user_data = await twitch_api.get_user(login)
            else:
                users = await twitch_api.get_users_by_logins([login])
                user_data = users.get(login)

            # ── Verify the preview image actually exists before using it.
            # ── A non-empty thumbnail_url doesn't guarantee Twitch has
            # ── actually rendered the snapshot yet — using it blindly is
            # ── exactly what produces a blank/broken image on some posts.
            embed_stream_data = stream_data
            raw_thumb = (stream_data.get("thumbnail_url") or "").replace("{width}", "1280").replace("{height}", "720")
            if raw_thumb and not await self._thumbnail_is_ready(raw_thumb):
                logger.info(f"on_stream_online: thumbnail not ready yet for {login} — posting without it for now")
                embed_stream_data = dict(stream_data)
                embed_stream_data["thumbnail_url"] = ""

            embed = build_live_embed(embed_stream_data, user_data or {})

            from db.guild_settings import get_guild_config
            try:
                cfg = await get_guild_config(guild_id)
                announce_channel_id = (cfg or {}).get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            except Exception:
                announce_channel_id = ANNOUNCE_CHANNEL_ID

            channel = self.bot.get_channel(announce_channel_id)
            if not channel:
                logger.warning(f"on_stream_online: announce channel {announce_channel_id} not found for {login}")
                return

            sent_msg = await channel.send(embed=embed)

            # ── Update Redis: message id + live status ───────────────
            msg_key    = f"stream:msg:{login}:{guild_id}"
            status_key = f"stream:status:{login}"
            stream_id  = stream_data.get("id", "live")
            await self.bot.app_state.redis.set(msg_key, str(sent_msg.id))
            await self.bot.app_state.redis.set(status_key, stream_id, ttl=21600)

            # ── Update DB: mark streamer as live ──────────────────────
            try:
                pool = self.bot.app_state.db.pool
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE streamers
                        SET is_live = TRUE, title = $2, game_name = $3,
                            viewer_count = $4, last_updated = NOW()
                        WHERE twitch_login = $1 AND guild_id = $5
                        """,
                        login,
                        stream_data.get("title", ""),
                        stream_data.get("game_name", ""),
                        stream_data.get("viewer_count", 0),
                        guild_id,
                    )
            except Exception as e:
                logger.error(f"Failed to update is_live=TRUE for {login}: {e}")

            # ── Insert stream_history row for streak/consistency stats ─
            try:
                pool = self.bot.app_state.db.pool
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO stream_history
                            (twitch_login, guild_id, title, game_name, started_at, peak_viewers)
                        VALUES ($1, $2, $3, $4, NOW(), $5)
                        """,
                        login,
                        guild_id,
                        stream_data.get("title", ""),
                        stream_data.get("game_name", ""),
                        stream_data.get("viewer_count", 0),
                    )
            except Exception as e:
                logger.error(f"Failed to insert stream_history for {login}: {e}")

            logger.info(f"on_stream_online: posted live announcement for {login} in guild {guild_id}")

            await self._update_dashboard(guild_id)

            # ── Refresh the thumbnail over the next several minutes ────
            # A single retry isn't reliable enough: Twitch's live preview
            # snapshot can take several minutes (not seconds) to actually
            # render on their CDN, and Discord only re-fetches an embed's
            # image when the message is edited — it won't notice on its
            # own that a URL now points to something different. So this
            # re-edits the message a handful of times over ~6 minutes to
            # give it several chances to catch a properly-rendered image.
            asyncio.create_task(
                self._refresh_live_embed_loop(sent_msg, user_id, login)
            )

        except Exception as e:
            logger.error(f"on_stream_online failed for {login}: {e}", exc_info=True)

    async def _refresh_live_embed_loop(
        self, message: discord.Message, user_id: str, login: str,
        attempts: int = 6, interval: int = 90,
    ):
        """
        Re-checks the live preview image every couple of minutes for up to
        ~9 minutes, and only edits the message once the image genuinely
        exists — not just once Twitch's API returns a URL for it. Stops
        as soon as a real thumbnail is confirmed, or once the stream ends.
        """
        twitch_api = self.bot.app_state.twitch_api
        for attempt in range(attempts):
            await asyncio.sleep(interval)
            try:
                stream_data = None
                if hasattr(twitch_api, "get_stream_metadata"):
                    stream_data = await twitch_api.get_stream_metadata(login)
                elif hasattr(twitch_api, "get_streams_by_ids"):
                    streams = await twitch_api.get_streams_by_ids([str(user_id)])
                    stream_data = streams[0] if streams else None

                if not stream_data:
                    return  # stream already ended — nothing left to refresh

                raw_thumb = (stream_data.get("thumbnail_url") or "").replace("{width}", "1280").replace("{height}", "720")
                if raw_thumb and not await self._thumbnail_is_ready(raw_thumb):
                    logger.info(
                        f"on_stream_online: thumbnail still not ready for {login} "
                        f"(check {attempt + 1}/{attempts}) — waiting for next check"
                    )
                    continue  # don't edit yet — try again next interval

                if hasattr(twitch_api, "get_user"):
                    user_data = await twitch_api.get_user(login)
                else:
                    users = await twitch_api.get_users_by_logins([login])
                    user_data = users.get(login)

                refreshed_embed = build_live_embed(stream_data, user_data or {})
                await message.edit(embed=refreshed_embed)
                logger.info(f"on_stream_online: thumbnail confirmed and updated for {login} (check {attempt + 1}/{attempts})")
                return  # got a real thumbnail — stop retrying
            except discord.NotFound:
                return  # message was deleted — stop retrying
            except Exception as e:
                logger.warning(
                    f"on_stream_online: thumbnail refresh check {attempt + 1} failed for {login}: {e}"
                )

    @commands.Cog.listener()
    async def on_stream_offline(self, user_id: str, login: str, display_name: str, duration_mins: int, guild_id: int):
        """Handles the stream offline event, fetches VOD, and clears cache."""
        await asyncio.sleep(15) 
        
        vod_url = await self._fetch_vod_url(user_id, login)

        # ── Fetch the last-known stream title before it's cleared ─
        last_title = None
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT title FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                    login, guild_id,
                )
                if row:
                    last_title = row["title"]
        except Exception as e:
            logger.error(f"Failed to fetch last title for {login}: {e}")

        # ── Fetch user info for the offline embed's avatar ────────
        user_info = None
        try:
            twitch_api = self.bot.app_state.twitch_api
            if hasattr(twitch_api, "get_user"):
                user_info = await twitch_api.get_user(login)
            elif hasattr(twitch_api, "get_users_by_logins"):
                users = await twitch_api.get_users_by_logins([login])
                user_info = users.get(login)
        except Exception as e:
            logger.warning(f"Failed to fetch user_info for offline embed ({login}): {e}")

        # ── Consume any recorded raid target ───────────────────────
        raid_target = None
        try:
            raid_key = f"raid:{login}"
            raid_target = await self.bot.app_state.redis.get(raid_key)
            if raid_target:
                await self.bot.app_state.redis.delete(raid_key)
        except Exception as e:
            logger.warning(f"Failed to check raid target for {login}: {e}")

        embed = await build_offline_embed(
            login=login, display_name=display_name, duration_mins=duration_mins,
            vod_url=vod_url, title=last_title, user_info=user_info, raided_login=raid_target,
        )

        sent_msg = None
        try:
            from db.guild_settings import get_guild_config
            config = await get_guild_config(guild_id)
            announce_channel_id = (
                config.get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
            )
            channel = self.bot.get_channel(announce_channel_id)
            if channel:
                sent_msg = await channel.send(embed=embed)
            else:
                logger.warning(f"Announce channel {announce_channel_id} not found for {login}")
        except Exception as e:
            logger.error(f"Failed to send offline message for {login}: {e}")

        # ── If no VOD yet, retry in the background and edit the message
        # ── in once one shows up. Twitch commonly takes well over 15s to
        # ── finish processing/publishing a VOD after the stream ends.
        if not vod_url and sent_msg:
            asyncio.create_task(
                self._refresh_vod_later(
                    sent_msg, user_id, login, display_name, duration_mins, last_title, user_info, raid_target,
                )
            )

        await self._update_dashboard(guild_id)

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

        # ── Close the open stream_history row for streak/consistency stats ─
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE stream_history
                    SET ended_at = NOW(), duration_secs = $3
                    WHERE twitch_login = $1 AND guild_id = $2 AND ended_at IS NULL
                    """,
                    login, guild_id, duration_mins * 60,
                )
        except Exception as e:
            logger.error(f"Failed to close stream_history row for {login}: {e}")

        # ── Clear Redis keys ─────────────────────────────────────
        msg_key    = f"stream:msg:{login}:{guild_id}"
        status_key = f"stream:status:{login}"
        try:
            await self.bot.app_state.redis.delete(msg_key)
            await self.bot.app_state.redis.delete(status_key)
            logger.info(f"Cleared Redis cache for {login} in guild {guild_id}.")
        except Exception as e:
            logger.error(f"Failed to delete Redis keys for {login}: {e}")

    async def _fetch_vod_url(self, user_id: str, login: str) -> str | None:
        """
        Attempts to fetch the most recent VOD for a streamer.
        Logs clearly whether the call succeeded, returned nothing, or failed
        outright, so future debugging doesn't require re-guessing method names.
        """
        twitch_api = self.bot.app_state.twitch_api
        try:
            if hasattr(twitch_api, "get_videos"):
                videos = await twitch_api.get_videos(user_id=user_id, video_type="archive", first=1)
                if videos:
                    logger.info(f"_fetch_vod_url: found VOD for {login} via get_videos")
                    return videos[0].get("url")
                logger.info(f"_fetch_vod_url: get_videos returned no results for {login} yet")
                return None
            elif hasattr(twitch_api, "request"):
                vod_data = await twitch_api.request(
                    "videos",
                    params={"user_id": user_id, "type": "archive", "first": 1},
                )
                if vod_data and vod_data.get("data"):
                    logger.info(f"_fetch_vod_url: found VOD for {login} via request()")
                    return vod_data["data"][0].get("url")
                logger.info(f"_fetch_vod_url: request() returned no results for {login} yet")
                return None
            else:
                logger.warning(
                    f"_fetch_vod_url: TwitchAPI has neither get_videos nor request — "
                    f"cannot look up VOD for {login}."
                )
                return None
        except Exception as e:
            logger.error(f"_fetch_vod_url: lookup failed for {login}: {e}")
            return None

    async def _refresh_vod_later(
        self,
        message: discord.Message,
        user_id: str,
        login: str,
        display_name: str,
        duration_mins: int,
        title: str | None,
        user_info: dict | None,
        raid_target: str | None = None,
        max_attempts: int = 5,
        interval: int = 60,
    ):
        """
        Retries the VOD lookup periodically (Twitch often takes a few minutes
        to finish processing a VOD after stream end) and edits the offline
        message once one becomes available.
        """
        for attempt in range(max_attempts):
            await asyncio.sleep(interval)
            vod_url = await self._fetch_vod_url(user_id, login)
            if vod_url:
                try:
                    refreshed_embed = await build_offline_embed(
                        login=login, display_name=display_name, duration_mins=duration_mins,
                        vod_url=vod_url, title=title, user_info=user_info, raided_login=raid_target,
                    )
                    await message.edit(embed=refreshed_embed)
                    logger.info(f"_refresh_vod_later: VOD link added for {login} after {attempt + 1} attempt(s)")
                except discord.NotFound:
                    pass  # message was deleted in the meantime
                except Exception as e:
                    logger.warning(f"_refresh_vod_later: failed to edit message for {login}: {e}")
                return
        logger.info(f"_refresh_vod_later: no VOD appeared for {login} after {max_attempts} attempts — giving up")

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
                exists = await conn.fetchval(
                    "SELECT 1 FROM streamers WHERE guild_id = $1 AND twitch_login = $2",
                    guild_id, username_clean,
                )
                if not exists:
                    await conn.execute(
                        """
                        INSERT INTO streamers (guild_id, twitch_user_id, twitch_login)
                        VALUES ($1, $2, $3)
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
                await conn.execute(
                    "DELETE FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                    username_clean, interaction.guild_id,
                )
            
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
                rows = await conn.fetch(
                    "SELECT twitch_login, is_live FROM streamers WHERE guild_id = $1 ORDER BY twitch_login ASC",
                    interaction.guild_id,
                )
            
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

            # ── Insert stream_history row (only if no open session exists) ─
            try:
                async with pool.acquire() as conn:
                    open_row = await conn.fetchval(
                        "SELECT 1 FROM stream_history WHERE twitch_login = $1 AND guild_id = $2 AND ended_at IS NULL",
                        username_clean, guild_id,
                    )
                    if not open_row:
                        await conn.execute(
                            """
                            INSERT INTO stream_history
                                (twitch_login, guild_id, title, game_name, started_at, peak_viewers)
                            VALUES ($1, $2, $3, $4, NOW(), $5)
                            """,
                            username_clean,
                            guild_id,
                            stream_data.get("title", ""),
                            stream_data.get("game_name", ""),
                            stream_data.get("viewer_count", 0),
                        )
            except Exception as e:
                logger.error(f"live_force: failed to insert stream_history for {username_clean}: {e}")

            await self._update_dashboard(guild_id)

            await interaction.followup.send(
                f"🚀 Live notification sent for **{username_clean}** in <#{announce_channel_id}>."
            )
        except Exception as e:
            logger.error(f"Bypass injection sequence failed for {username_clean}: {e}", exc_info=True)
            await interaction.followup.send("❌ Error forcing stream validation context processing.")

    @live_group.command(name="dashboard", description="Post or refresh the 'who's live now' dashboard.")
    async def live_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id or GUILD_ID
        try:
            await self._update_dashboard(guild_id)
            await interaction.followup.send("Dashboard refreshed.")
        except Exception as e:
            logger.error(f"live_dashboard failed: {e}", exc_info=True)
            await interaction.followup.send("Failed to refresh the dashboard.")

    @live_group.command(name="streaks", description="Shows a streamer's current and longest streaming streak.")
    @app_commands.describe(username="The Twitch login username to check streak stats for")
    async def live_streaks(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        username_clean = username.lower().strip()
        guild_id = interaction.guild_id or GUILD_ID
        try:
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT started_at::date AS stream_date
                    FROM stream_history
                    WHERE twitch_login = $1 AND guild_id = $2 AND started_at IS NOT NULL
                    ORDER BY stream_date DESC
                    """,
                    username_clean, guild_id,
                )

            if not rows:
                await interaction.followup.send(f"No stream history found yet for **{username_clean}**.")
                return

            from datetime import date, timedelta
            dates = {r["stream_date"] for r in rows}
            today = date.today()

            # Current streak — consecutive days ending today or yesterday
            current_streak = 0
            cursor = today if today in dates else today - timedelta(days=1)
            while cursor in dates:
                current_streak += 1
                cursor -= timedelta(days=1)

            # Longest streak ever
            sorted_dates = sorted(dates)
            longest_streak = 1
            run = 1
            for i in range(1, len(sorted_dates)):
                if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
                    run += 1
                else:
                    longest_streak = max(longest_streak, run)
                    run = 1
            longest_streak = max(longest_streak, run)

            embed = discord.Embed(
                title=f"Streak Stats — {username_clean}",
                color=0xFFB6C1,
            )
            embed.add_field(name="Current Streak", value=f"{current_streak} day{'s' if current_streak != 1 else ''}", inline=True)
            embed.add_field(name="Longest Streak", value=f"{longest_streak} day{'s' if longest_streak != 1 else ''}", inline=True)
            embed.add_field(name="Total Stream Days", value=str(len(dates)), inline=True)
            embed.set_footer(text=f"twitch.tv/{username_clean}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"live_streaks failed for {username_clean}: {e}", exc_info=True)
            await interaction.followup.send("Failed to compute streak stats.")

    @live_group.command(name="stats", description="Scans Twitch right now and posts any missed live announcements.")
    async def live_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id = interaction.guild_id or GUILD_ID

            # Pull all tracked logins and user IDs from DB
            pool = self.bot.app_state.db.pool
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT twitch_login, twitch_user_id FROM streamers WHERE guild_id = $1", guild_id
                )
            
            # Map logins to user IDs
            user_id_map = {}
            for r in rows:
                if r["twitch_user_id"]:
                    user_id_map[r["twitch_login"]] = str(r["twitch_user_id"])
                    
            # Fallback mapping from KNOWN_STREAMERS
            for login, uid in KNOWN_STREAMERS.items():
                if uid:
                    user_id_map[login] = str(uid)

            all_user_ids = list(set(user_id_map.values()))
            all_logins = list(set(user_id_map.keys()))

            if not all_user_ids:
                await interaction.followup.send("📭 No streamers tracked yet.")
                return

            # Ask Twitch who is actually live right now using the IDs mapping
            twitch_api   = self.bot.app_state.twitch_api
            live_streams = await twitch_api.get_streams_by_ids(all_user_ids)
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
                    # Insert stream_history row (only if no open session exists)
                    open_row = await conn.fetchval(
                        "SELECT 1 FROM stream_history WHERE twitch_login = $1 AND guild_id = $2 AND ended_at IS NULL",
                        login, guild_id,
                    )
                    if not open_row:
                        await conn.execute(
                            """
                            INSERT INTO stream_history
                                (twitch_login, guild_id, title, game_name, started_at, peak_viewers)
                            VALUES ($1, $2, $3, $4, NOW(), $5)
                            """,
                            login,
                            guild_id,
                            stream.get("title", ""),
                            stream.get("game_name", ""),
                            stream.get("viewer_count", 0),
                        )
                recovered += 1

            if recovered:
                await self._update_dashboard(guild_id)
                await interaction.followup.send(
                    f"📡 Scan complete — recovered **{recovered}** missed stream notification(s)!"
                )
            else:
                await interaction.followup.send(
                    f"✅ All {len(live_map)} live stream(s) are already announced. "
                    f"({len(all_logins) - len(live_map)} streamer(s) offline.)"
                )

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

# Fixed: Required setup function for discord.py extension loading
async def setup(bot):
    await bot.add_cog(LiveCommandsCog(bot))
    logger.info("commands.live_commands extension setup complete.")
