import discord
from utils.cache import redis_client


class RedisPagination(discord.ui.View):

    def __init__(self, pages, user_id):
        super().__init__(timeout=300)  # 5 minutes timeout

        self.pages = pages
        self.user_id = user_id
        self.memory_page = 0  # fallback

        self.key = None

    # -------------------------------------------------
    # INTERNAL
    # -------------------------------------------------

    def _build_key(self, message_id):
        return f"pagination:{self.user_id}:{message_id}"

    def get_page(self):
        if redis_client and self.key:
            val = redis_client.get(self.key)
            return int(val) if val else 0
        return self.memory_page

    def set_page(self, value):
        if redis_client and self.key:
            redis_client.set(self.key, value, ex=600)  # expire 10 min
        else:
            self.memory_page = value

    # -------------------------------------------------
    # PREVIOUS
    # -------------------------------------------------

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You cannot control this pagination.",
                ephemeral=True
            )
            return

        if not self.key:
            self.key = self._build_key(interaction.message.id)

        page = self.get_page()

        if page > 0:
            page -= 1
            self.set_page(page)

        await interaction.response.edit_message(
            embed=self.pages[page],
            view=self
        )

    # -------------------------------------------------
    # NEXT
    # -------------------------------------------------

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You cannot control this pagination.",
                ephemeral=True
            )
            return

        if not self.key:
            self.key = self._build_key(interaction.message.id)

        page = self.get_page()

        if page < len(self.pages) - 1:
            page += 1
            self.set_page(page)

        await interaction.response.edit_message(
            embed=self.pages[page],
            view=self
        )

    # -------------------------------------------------
    # TIMEOUT
    # -------------------------------------------------

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
