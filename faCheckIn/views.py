from collections.abc import Callable, Coroutine
from typing import Any

import discord


class AuthorOnlyView(discord.ui.View):
    """View class designed to only interact with the interaction author"""

    def __init__(self, author: discord.Member | discord.User, timeout: float = 10.0):
        super().__init__()
        self.timeout = timeout
        self.author = author
        self.message = None

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.message:
            embed = discord.Embed(
                title="Time out",
                description=f"{self.author.mention} Sorry, you didn't respond quick enough. Please try again.",
                colour=discord.Colour.orange(),
            )

            await self.message.edit(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        return interaction.user == self.author


class ConfirmButton(discord.ui.Button):
    def __init__(
        self,
        callback: Callable[[discord.Interaction], Coroutine[Any, Any, Any]]
        | None = None,
    ):
        super().__init__()
        self.label = "Confirm"
        self.custom_id = "confirmed"
        self.style = discord.ButtonStyle.green
        self._callback = callback

    async def callback(self, interaction: discord.Interaction):
        if self._callback:
            await self._callback(interaction)


class DeclineButton(discord.ui.Button):
    def __init__(
        self,
        callback: Callable[[discord.Interaction], Coroutine[Any, Any, Any]]
        | None = None,
    ):
        super().__init__()
        self.label = "Decline"
        self.custom_id = "declined"
        self.style = discord.ButtonStyle.red
        self._callback = callback

    async def callback(self, interaction: discord.Interaction):
        if self._callback:
            await self._callback(interaction)
