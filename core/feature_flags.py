"""
core/feature_flags.py
────────────────────────────────────────────────────────────────
Simple feature flag system for runtime feature toggling.

Improvements over original:
- Flags can be seeded from environment variables automatically
  (FLAG_<NAME>=1 → flag "name" is enabled) so Railway / Docker
  envs control features without code changes
- get() with a default arg added for safe access without is_enabled()
- all() returns a snapshot of current flag states for a /flags debug command
- reset() clears all runtime changes back to the initial config,
  useful after tests or a hot-reload
- Type hints throughout
"""

import logging
import os

logger = logging.getLogger("feature-flags")


class FeatureFlags:

    def __init__(self, config: dict | None = None):
        """
        config: optional dict of initial flag states, e.g.
                {"epic_games": True, "stream_tracking": False}
        Environment variables override config:
                FLAG_EPIC_GAMES=1  →  "epic_games" = True
        """
        self._initial: dict[str, bool] = dict(config or {})
        self._flags:   dict[str, bool] = {}
        self._load(self._initial)

    # ──────────────────────────────────────────────────────────
    # INTERNAL
    # ──────────────────────────────────────────────────────────

    def _load(self, base: dict[str, bool]) -> None:
        self._flags = dict(base)

        # Override from environment: FLAG_<NAME>=1 or FLAG_<NAME>=0
        for key, value in os.environ.items():
            if not key.startswith("FLAG_"):
                continue
            flag_name = key[5:].lower()   # FLAG_EPIC_GAMES → "epic_games"
            self._flags[flag_name] = value.strip() in ("1", "true", "yes")

    # ──────────────────────────────────────────────────────────
    # READ
    # ──────────────────────────────────────────────────────────

    def is_enabled(self, flag: str) -> bool:
        """Returns True if the flag is enabled. Missing flags → False."""
        return self._flags.get(flag, False)

    def get(self, flag: str, default: bool = False) -> bool:
        """Same as is_enabled() but lets you specify your own default."""
        return self._flags.get(flag, default)

    def all(self) -> dict[str, bool]:
        """Returns a copy of all current flag states."""
        return dict(self._flags)

    # ──────────────────────────────────────────────────────────
    # WRITE
    # ──────────────────────────────────────────────────────────

    def enable(self, flag: str) -> None:
        self._flags[flag] = True
        logger.info(f"Feature flag enabled: {flag}")

    def disable(self, flag: str) -> None:
        self._flags[flag] = False
        logger.info(f"Feature flag disabled: {flag}")

    def toggle(self, flag: str) -> bool:
        """Flips the flag and returns the new state."""
        new_state = not self._flags.get(flag, False)
        self._flags[flag] = new_state
        logger.info(f"Feature flag toggled: {flag} → {new_state}")
        return new_state

    def reset(self) -> None:
        """Resets all flags back to the original config (ignores env overrides)."""
        self._load(self._initial)
        logger.info("Feature flags reset to initial config")

    # ──────────────────────────────────────────────────────────
    # DEBUG
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        enabled  = [k for k, v in self._flags.items() if v]
        disabled = [k for k, v in self._flags.items() if not v]
        return f"<FeatureFlags enabled={enabled} disabled={disabled}>"
