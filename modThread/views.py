import discord

from typing import Union

class AssignView(discord.ui.View):
    """View class designed to only interact with the interaction author"""

    def __init__(
        self, author: Union[discord.Member, discord.User], timeout: float = 20.0
    ):
        super().__init__()
        self.timeout = timeout
        self.author = author

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        if self.message:
            embed = discord.Embed(
                title="Timed out",
                description=f"{self.author.mention} Sorry, you didn't respond quick enough. Please try again.",
                colour=discord.Colour.orange(),
            )

            await self.message.edit(embed=embed, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            return False
        return True