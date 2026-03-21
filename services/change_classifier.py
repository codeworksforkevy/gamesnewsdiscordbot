class ChangeClassifier:

    @staticmethod
    def classify(old, new):

        title_changed = old.get("title") != new.get("title")
        game_changed = old.get("game") != new.get("game")

        if title_changed and game_changed:
            return "title+game"

        if title_changed:
            return "title"

        if game_changed:
            return "game"

        return "unknown"
