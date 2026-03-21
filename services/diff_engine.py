# services/diff_engine.py

import hashlib


def _make_key(game):
    base = f"{game['platform']}::{game['title']}"
    return hashlib.sha256(base.encode()).hexdigest()


def diff_games(old_games, new_games):
    """
    Returns only NEW games (not seen before)
    """

    old_keys = {_make_key(g) for g in old_games}
    new_keys = {_make_key(g) for g in new_games}

    diff = []

    for game in new_games:
        key = _make_key(game)
        if key not in old_keys:
            diff.append(game)

    return diff
