def detect_changes(old, new):

    changes = {}

    if not old:
        return {"title": new["title"], "game": new["game"]}

    if old.get("title") != new.get("title"):
        changes["title"] = {
            "old": old.get("title"),
            "new": new.get("title")
        }

    if old.get("game") != new.get("game"):
        changes["game"] = {
            "old": old.get("game"),
            "new": new.get("game")
        }

    return changes
