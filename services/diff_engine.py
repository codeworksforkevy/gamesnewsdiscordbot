import hashlib
import logging
from difflib import SequenceMatcher

logger = logging.getLogger("diff-engine")


# ==================================================
# NORMALIZATION
# ==================================================
def _normalize(text: str) -> str:
    """
    Normalize string for better matching
    """
    return (
        text.strip().lower()
        .replace("™", "")
        .replace("®", "")
        .replace("-", " ")
    )


# ==================================================
# BASE HASH KEY (STRICT MATCH)
# ==================================================
def _make_strict_key(game):
    base = f"{game.get('platform','')}::{game.get('title','')}"
    return hashlib.sha256(base.encode()).hexdigest()


# ==================================================
# FUZZY SIMILARITY
# ==================================================
def _is_similar(title1: str, title2: str, threshold: float = 0.85) -> bool:
    return SequenceMatcher(
        None,
        _normalize(title1),
        _normalize(title2)
    ).ratio() >= threshold


# ==================================================
# DIFF ENGINE (SMART)
# ==================================================
def diff_games(old_games, new_games):
    """
    Advanced diff:
    - strict hash match
    - fuzzy title match
    - platform-aware
    """

    if not old_games:
        return new_games

    old_titles_by_platform = {}
    old_keys = set()

    # Build indexes
    for g in old_games:
        platform = g.get("platform")
        title = g.get("title", "")

        key = _make_strict_key(g)
        old_keys.add(key)

        old_titles_by_platform.setdefault(platform, []).append(title)

    new_items = []

    for game in new_games:
        platform = game.get("platform")
        title = game.get("title", "")

        strict_key = _make_strict_key(game)

        # 1. Exact match check
        if strict_key in old_keys:
            continue

        # 2. Fuzzy match check
        similar_found = False

        for old_title in old_titles_by_platform.get(platform, []):
            if _is_similar(title, old_title):
                similar_found = True
                break

        if similar_found:
            logger.info(
                "Duplicate detected via fuzzy match",
                extra={
                    "platform": platform,
                    "title": title
                }
            )
            continue

        # If passed both → it's new
        new_items.append(game)

    logger.info(
        "Diff computed",
        extra={
            "old_count": len(old_games),
            "new_count": len(new_games),
            "diff_count": len(new_items)
        }
    )

    return new_items
