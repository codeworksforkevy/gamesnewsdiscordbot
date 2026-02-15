import discord
from utils.cache import redis_client

class RedisPagination(discord.ui.View):
    def __init__(self, pages, user_id):
        super().__init__(timeout=None)
        self.pages = pages
        self.key = f"page:{user_id}"
        if redis_client:
            redis_client.set(self.key, 0)

    def get_page(self):
        if redis_client:
            val = redis_client.get(self.key)
            return int(val) if val else 0
        return 0

    def set_page(self, value):
        if redis_client:
            redis_client.set(self.key, value)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        page = self.get_page()
        if page > 0:
            page -= 1
            self.set_page(page)
        await interaction.response.edit_message(embed=self.pages[page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        page = self.get_page()
        if page < len(self.pages) - 1:
            page += 1
            self.set_page(page)
        await interaction.response.edit_message(embed=self.pages[page], view=self)
