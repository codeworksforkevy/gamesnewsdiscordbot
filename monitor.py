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
from datetime import datetime, timezone

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

    async def _recover_offline(self, login: str, user_id: str, guild_id: int) -> None:
        """
        Symmetric to _recover_stream, but for the reverse case: the DB
        still thinks a streamer is live but Twitch says they're not —
        meaning the stream.offline event was likely missed.

        Rather than duplicate the offline-handling logic (VOD lookup,
        stream_history closing, dashboard update, raid field, etc.) this
        just dispatches the same event on_stream_offline already listens
        for in commands/live_commands.py, reusing that flow entirely.
        """
        display_name = login
        try:
            if hasattr(self.twitch_api, "get_user_by_login"):
                user_data = await self.twitch_api.get_user_by_login(login) or {}
            elif hasattr(self.twitch_api, "get_user"):
                user_data = await self.twitch_api.get_user(login) or {}
            elif hasattr(self.twitch_api, "get_users_by_logins"):
                users = await self.twitch_api.get_users_by_logins([login])
                user_data = users.get(login, {})
            else:
                user_data = {}
            display_name = user_data.get("display_name", login)
        except Exception as e:
            logger.warning(f"[Watchdog] Could not fetch display name for {login}: {e}")

        # Estimate how long they were live from the open stream_history row
        duration_mins = 0
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT started_at FROM stream_history
                    WHERE twitch_login = $1 AND guild_id = $2 AND ended_at IS NULL
                    ORDER BY started_at DESC LIMIT 1
                    """,
                    login, guild_id,
                )
            if row and row["started_at"]:
                elapsed = datetime.now(timezone.utc) - row["started_at"]
                duration_mins = max(int(elapsed.total_seconds() // 60), 0)
        except Exception as e:
            logger.warning(f"[Watchdog] Could not compute duration for {login}: {e}")

        self.bot.dispatch("stream_offline", user_id, login, display_name, duration_mins, guild_id)
        logger.info(f"[Watchdog] Dispatched stream_offline for {login} (missed event reconciliation)")

    async def run_safety_check(self):
        """
        [Watchdog] Periodically verifies live status against Twitch API.
        If an EventSub notification was missed, posts it directly.
        Also catches the reverse case — a missed stream.offline event
        leaving is_live stuck as TRUE — and reconciles it the same way.

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
            live_now = {s["user_login"].lower() for s in live_streams}

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

            # ── 5. Reconciliation: catch missed OFFLINE events too ────────────
            # Symmetric to step 4 — if the DB thinks a streamer is live but
            # Twitch says they're not, the offline event was likely missed.
            try:
                stale_rows = await self.db.fetch(
                    "SELECT twitch_login, twitch_user_id, guild_id FROM streamers WHERE is_live = TRUE"
                )
                for row in stale_rows:
                    login = row["twitch_login"]
                    if login in live_now or login not in tracked:
                        continue

                    status_key = f"stream:status:{login}"
                    still_marked_live = await self.redis.get(status_key)
                    if not still_marked_live:
                        continue  # already reconciled elsewhere (e.g. /live list self-heal)

                    guild_id = row["guild_id"]
                    user_id = str(row["twitch_user_id"]) if row["twitch_user_id"] else tracked[login][0]

                    logger.warning(
                        f"[Watchdog] {login} is marked live in DB but Twitch says offline — "
                        f"the stream.offline event was likely missed. Reconciling."
                    )
                    try:
                        await self._recover_offline(login, user_id, guild_id)
                    except Exception as e:
                        logger.error(f"[Watchdog] Offline reconciliation failed for {login}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"[Watchdog] Offline reconciliation pass failed: {e}", exc_info=True)

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
