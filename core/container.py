class AppState:
    def __init__(self, db=None, redis=None, config=None):
        self.db = db
        self.redis = redis
        self.cache = None
        self.config = config or {}
        self.features = None
        self.registry = None
        self.twitch_api = None
        self.eventsub_manager = None
        self.live_roles = {}
        self.webhook_url = os.getenv("WEBHOOK_URL")
