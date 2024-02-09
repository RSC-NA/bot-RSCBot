import discord
import logging
from redbot.core.commands import Context
from teamManager.embeds import TimeoutEmbed, ErrorEmbed

from typing import Callable, Union, List, TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from teamManager.teamManager import TeamManager

log = logging.getLogger("red.RSCBot.prefixManager.views")


class ClearPlayerPrefixView(discord.ui.View):
    """Remove all player prefixes view"""

    def __init__(
        self,
        ctx: Context,
        timeout: float = 30.0,
    ):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.author = ctx.author
        self.msg: discord.Message | None = None
        self.guild = ctx.guild
        self.result = False

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        await self.msg.edit(embed=TimeoutEmbed(author=self.author), view=None)

    async def prompt(self):
        """Prompt for prefix clear"""


        if not self.guild:
            await self.ctx.reply(content="Unable to run this command outside of a guild.")
            raise RuntimeError("Unable to run this command outside of a guild.")

        confirm_embed = discord.Embed(
            title="Clear Player Prefixes",
            description=(
                f"You are about to remove the franchise prefix from **{len(self.guild.members)}** players."
                "\n\nAre you sure you want to do this?"
            ),
            color=discord.Color.blue(),
        )
        self.msg = await self.ctx.send(embed=confirm_embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            await self.ctx.reply(
                content="Only the command author is allowed to interact.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.result = True 
        if not self.msg:
            return

        loading_embed = discord.Embed(
            title="Clear Player Prefixes",
            description="Clearing all player prefixes. This can take some time...",
            color=discord.Color.yellow(),
        )
        await self.msg.edit(embed=loading_embed, view=None)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Cancel creating new franchise"""
        self.result = False
        if not self.msg:
            return

        deny_embed = discord.Embed(
            title="Cancelled",
            description=f"Clear all player prefixes action was cancelled by user.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=deny_embed, view=None)
        self.stop()