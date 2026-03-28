"""
services/logging_config.py
────────────────────────────────────────────────────────────────
Centralised logging setup.

Improvements over original:
- Structured JSON formatter for production (machine-readable logs)
- Human-readable format for development (controlled by LOG_FORMAT env var)
- Rotating file handler so logs don't fill the disk
- Per-module level overrides via LOG_LEVELS env var
- Filters noisy third-party libraries down to WARNING by default
"""

import logging
import logging.handlers
import os
import json
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
# JSON FORMATTER  (used in production)
# ──────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """
    Emits one JSON object per line, compatible with most log aggregators
    (Datadog, Loki, Railway structured logs, etc.)
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }

        # Attach any extra_data dict the caller passed in
        extra = getattr(record, "extra_data", None)
        if extra and isinstance(extra, dict):
            payload.update(extra)

        # Attach exception info if present
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# SETUP
# ──────────────────────────────────────────────────────────────

def setup_logging(
    log_dir: str = "logs",
    max_bytes: int = 10 * 1024 * 1024,   # 10 MB per file
    backup_count: int = 5,
) -> None:
    """
    Configures the root logger and per-module levels.

    Environment variables:
      LOG_FORMAT   "json" (default) | "text"
      LOG_LEVEL    root level, default "INFO"
      LOG_LEVELS   comma-separated overrides, e.g.
                   "discord=WARNING,asyncio=WARNING,aiohttp=WARNING"
      LOG_TO_FILE  "1" to enable rotating file output (default off)
    """

    log_format  = os.getenv("LOG_FORMAT", "json").lower()
    root_level  = os.getenv("LOG_LEVEL",  "INFO").upper()
    log_to_file = os.getenv("LOG_TO_FILE", "0") == "1"

    # ── Choose formatter ────────────────────────────────────────
    if log_format == "text":
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = JsonFormatter()

    # ── Root handler (stdout) ───────────────────────────────────
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [stream_handler]

    # ── Optional rotating file handler ─────────────────────────
    if log_to_file:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(log_dir, "bot.log"),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # ── Apply to root logger ────────────────────────────────────
    logging.basicConfig(
        level=getattr(logging, root_level, logging.INFO),
        handlers=handlers,
        force=True,   # override any prior basicConfig calls
    )

    # ── Silence noisy third-party libraries ────────────────────
    _noisy = ["discord", "asyncio", "aiohttp", "aiohttp.client", "urllib3"]
    for lib in _noisy:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # ── Per-module level overrides ──────────────────────────────
    # e.g. LOG_LEVELS="event_router=DEBUG,twitch-monitor=DEBUG"
    overrides = os.getenv("LOG_LEVELS", "")
    for entry in overrides.split(","):
        entry = entry.strip()
        if "=" not in entry:
            continue
        module, level = entry.split("=", 1)
        lvl = getattr(logging, level.strip().upper(), None)
        if lvl is not None:
            logging.getLogger(module.strip()).setLevel(lvl)

    logging.getLogger(__name__).info(
        "Logging initialised",
        extra={"extra_data": {
            "format":   log_format,
            "level":    root_level,
            "file":     log_to_file,
        }},
    )
