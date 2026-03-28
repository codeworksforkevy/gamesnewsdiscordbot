"""
core/registry.py
────────────────────────────────────────────────────────────────
Tracks which command modules are loaded, when, and how many times.

Improvements over original:
- Records reload_count so you can see how many times a module has
  been hot-reloaded during the bot's lifetime
- Records last_error alongside the error string so you can surface
  it in a /debug command
- unregister() added for explicit module removal
- status() returns a clean summary dict for health-check endpoints
  or a Discord slash command
- All timestamps stored as float (time.time()) for easy formatting
"""

import time
from typing import Optional


class CommandRegistry:

    def __init__(self):
        # name → { module, loaded_at, reload_count }
        self._commands: dict[str, dict] = {}
        # module path → { error, failed_at }
        self._errors: dict[str, dict] = {}

    # ──────────────────────────────────────────────────────────
    # REGISTER
    # ──────────────────────────────────────────────────────────

    def register(self, name: str, module: str) -> None:
        """
        Records a successfully loaded / reloaded command module.
        Increments reload_count if the module was already registered.
        """
        existing = self._commands.get(name)

        self._commands[name] = {
            "module":       module,
            "loaded_at":    time.time(),
            "reload_count": (existing["reload_count"] + 1) if existing else 0,
        }

        # Clear any previous error for this module
        self._errors.pop(module, None)

    def register_error(self, module: str, error: Exception) -> None:
        self._errors[module] = {
            "error":     str(error),
            "type":      type(error).__name__,
            "failed_at": time.time(),
        }

    # ──────────────────────────────────────────────────────────
    # UNREGISTER
    # ──────────────────────────────────────────────────────────

    def unregister(self, name: str) -> bool:
        """Removes a command from the registry. Returns True if it existed."""
        return self._commands.pop(name, None) is not None

    # ──────────────────────────────────────────────────────────
    # READ
    # ──────────────────────────────────────────────────────────

    def get_all(self) -> dict[str, dict]:
        return dict(self._commands)

    def get_errors(self) -> dict[str, dict]:
        return dict(self._errors)

    def get(self, name: str) -> Optional[dict]:
        return self._commands.get(name)

    def is_loaded(self, name: str) -> bool:
        return name in self._commands

    # ──────────────────────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────────────────────

    def status(self) -> dict:
        """
        Returns a health-check-friendly summary, useful for a
        /debug or /status slash command.
        """
        return {
            "loaded_count": len(self._commands),
            "error_count":  len(self._errors),
            "commands":     list(self._commands.keys()),
            "errors":       list(self._errors.keys()),
        }

    def __repr__(self) -> str:
        return (
            f"<CommandRegistry "
            f"loaded={len(self._commands)} "
            f"errors={len(self._errors)}>"
        )
