"""
Production TwitchMonitor — leader-elected, self-healing cycle.
Includes Watchdog mechanism for state reconciliation.

Self-contained: does NOT depend on services.notifier (that module's
interface has been unreliable/undocumented). Instead reuses the same
embed-building and posting logic already proven to work in
commands/live_commands.py.
"""
import asyncio
import logging

from commands.live_commands import KNOWN_STREAMERS

logger = logging.getLogger("twitch-monitor")


class TwitchMonitor:
    LEADER_LOCK_KEY = "twitch-monitor:leader"
    LEADER_LOCK_TTL = 60

    def __init__(self, twitch_api, eventsub_manager, db_pool, redis, bot, notifier=None):
        self.twitch_api = twitch_api
        self.eventsub = eventsub_manager
        self.db = db_pool
        self.redis = redis
        self.bot = bot
        self.notifier = notifier  # kept for compatibility, unused by run_safety_check
        self._running = False
        self._task = None
        self.monitor_cycles_total = 0

    async def _get_announce_channel_id(self, guild_id: int) -> int:
        """Mirrors _get_announce_channel_id in live_commands.py, with hardcoded fallback."""
        from commands.live_commands import ANNOUNCE_CHANNEL_ID
        try:
            from db.guild_settings import get_guild_config
            cfg = await get_guild_config(guild_id)
            return (cfg or {}).get("announce_channel_id") or ANNOUNCE_CHANNEL_ID
        except Exception:
            return ANNOUNCE_CHANNEL_ID

    async def _recover_stream(self, login: str, guild_id: int, stream: dict) -> None:
        """Posts a missed live notification and syncs Redis + DB state."""
        from commands.live_commands import build_live_embed

        channel_id = await self._get_announce_channel_id(guild_id)
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.error(f"[Watchdog] Could not find channel {channel_id} to recover {login}")
            return

        # Fetch user info (method name varies across TwitchAPI versions)
        user_data = {}
        try:
            if hasattr(self.twitch_api, "get_user_by_login"):
                user_data = await self.twitch_api.get_user_by_login(login) or {}
            elif hasattr(self.twitch_api, "get_user"):
                user_data = await self.twitch_api.get_user(login) or {}
            elif hasattr(self.twitch_api, "get_users_by_logins"):
                users = await self.twitch_api.get_users_by_logins([login])
                user_data = users.get(login, {})
        except Exception as e:
            logger.warning(f"[Watchdog] Could not fetch user data for {login}: {e}")

        embed = build_live_embed(stream, user_data)
        sent_msg = await channel.send(embed=embed)

        msg_key    = f"stream:msg:{login}:{guild_id}"
        status_key = f"stream:status:{login}"
        stream_id  = stream.get("id", "live")
        await self.redis.set(msg_key, str(sent_msg.id))
        await self.redis.set(status_key, stream_id, ttl=21600)

        try:
            async with self.db.acquire() as conn:
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
        except Exception as e:
            logger.error(f"[Watchdog] DB update failed for {login}: {e}")

        logger.info(f"[Watchdog] Recovered missed notification for {login} in guild {guild_id}")

    async def run_safety_check(self):
        """
        [Watchdog] Periodically verifies live status against Twitch API.
        If an EventSub notification was missed, posts it directly.

        NOTE: TwitchAPI in this codebase only exposes get_streams_by_ids —
        there is no get_streams_by_logins method. All lookups must go
        through numeric Twitch user IDs, not logins.
        """
        try:
            from commands.live_commands import GUILD_ID

            # ── 1. Fetch tracked streamers from DB (with guild_id) ───────────
            rows = await self.db.fetch(
                "SELECT DISTINCT twitch_login, twitch_user_id, guild_id FROM streamers"
            )

            # login -> (user_id, guild_id)
            tracked: dict[str, tuple[str, int]] = {
                r["twitch_login"]: (str(r["twitch_user_id"]), r["guild_id"])
                for r in rows
                if r["twitch_user_id"]
            }

            # ── 2. Merge with KNOWN_STREAMERS for anything not yet in DB ──────
            for login, uid in KNOWN_STREAMERS.items():
                if login not in tracked and uid:
                    tracked[login] = (str(uid), GUILD_ID)

            if not tracked:
                return

            user_ids = [uid for uid, _ in tracked.values()]

            # ── 3. Batch-fetch live status from Twitch API ────────────────────
            live_streams = await self.twitch_api.get_streams_by_ids(user_ids)

            # ── 4. Recovery: post notifications for any missed EventSub events ─
            for stream in live_streams:
                login = stream["user_login"].lower()
                if login not in tracked:
                    continue
                _, guild_id = tracked[login]

                status_key = f"stream:status:{login}"
                already_tracked = await self.redis.get(status_key)
                if already_tracked:
                    continue

                logger.warning(
                    f"[Watchdog] {login} is live but not in Redis — "
                    f"EventSub may have been missed. Recovering."
                )
                try:
                    await self._recover_stream(login, guild_id, stream)
                except Exception as e:
                    logger.error(f"[Watchdog] Recovery failed for {login}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"[Watchdog] Failed to run safety check: {e}", exc_info=True)

    async def _cycle(self):
        """Main monitoring loop."""
        while self._running:
            self.monitor_cycles_total += 1

            # Run safety check every 2 cycles (~2 minutes) — catches missed
            # EventSub deliveries quickly instead of leaving streams unposted
            # for up to 5 minutes.
            if self.monitor_cycles_total % 2 == 0:
                await self.run_safety_check()

            await asyncio.sleep(60)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._cycle())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
