import discord
import logging
from redbot.core.commands import Context
from teamManager.embeds import TimeoutEmbed, ErrorEmbed

from typing import Callable, Union, List, TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from teamManager.teamManager import TeamManager

log = logging.getLogger("red.RSCBot.teamManager.views")


class AddFranchiseView(discord.ui.View):
    """Add a new franchise view"""

    def __init__(
        self,
        cog: "TeamManager",
        ctx: Context,
        name: str,
        prefix: str,
        gm: Union[discord.Member, discord.User],
        timeout: float = 10.0,
    ):
        super().__init__()
        self.cog = cog
        self.ctx = ctx
        self.author = ctx.author
        self.name = name
        self.prefix = prefix
        self.gm = gm
        self.timeout = timeout
        self.msg = None

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        await self.msg.edit(embed=TimeoutEmbed(author=self.author), view=None)

    async def prompt(self):
        """Prompt user for franchise creation."""
        add_embed = discord.Embed(
            title="Add Franchise",
            description=f"Franchise Name: **{self.name}**\n"
            f"Prefix: **{self.prefix}**\n"
            f"General Manager: **{self.gm.name}**\n\n"
            "Are you sure you want to add this franchise?",
            color=discord.Color.blue(),
        )
        self.msg = await self.ctx.send(embed=add_embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            await interaction.response.send_message(
                content="Only the command author is allowed to interact.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Create new franchise"""
        gm_role = self.cog._find_role_by_name(self.ctx, self.cog.GM_ROLE)
        franchise_role_name = f"{self.name} ({self.gm.name})"
        franchise_role = await self.cog._create_role(self.ctx, franchise_role_name)

        if franchise_role:
            await self.gm.add_roles(gm_role, franchise_role)
            prefix_cog = self.cog.bot.get_cog("PrefixManager")
            await prefix_cog.add_prefix(self.ctx, self.gm.name, self.prefix)
            await self.cog._set_user_nickname_prefix(self.ctx, self.prefix, self.gm)
            success_embed = discord.Embed(
                title="Success",
                description=f"**{self.name}** franchise was successfully created.",
                color=discord.Color.green(),
            )
            await self.msg.edit(embed=success_embed, view=None)
        else:
            await self.msg.edit(
                embed=ErrorEmbed(description="Error creating franchise role."),
                view=None,
            )
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Cancel creating new franchise"""
        deny_embed = discord.Embed(
            title="Cancelled",
            description=f"Add franchise action was cancelled by user.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=deny_embed, view=None)
        self.stop()


class RemoveFranchiseView(discord.ui.View):
    """Remove franchise view"""

    def __init__(
        self,
        cog: "TeamManager",
        ctx: Context,
        role: discord.Role,
        name: str,
        prefix: str,
        gm: Union[discord.Member, discord.Role],
        timeout: float = 10.0,
    ):
        super().__init__()
        self.cog = cog
        self.ctx = ctx
        self.author = ctx.author
        self.gm = gm
        self.name = name
        self.prefix = prefix
        self.role = role
        self.timeout = timeout
        self.msg = None

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        self.timedout = True
        await self.msg.edit(embed=TimeoutEmbed(author=self.author), view=None)

    async def prompt(self):
        """Prompt user for franchise removal."""

        add_embed = discord.Embed(
            title="Remove Franchise",
            description=f"Franchise Name: **{self.name}**\n"
            f"Prefix: **{self.prefix}**\n"
            f"General Manager: **{self.gm.name}**\n\n"
            "Are you sure you want to remove this franchise?",
            color=discord.Color.blue(),
        )
        self.msg = await self.ctx.send(embed=add_embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            await interaction.response.send_message(
                content="Only the command author is allowed to interact.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Create new franchise"""
        # franchise_role = self.cog._get_franchise_role(self.ctx, self.gm.name)
        franchise_teams = await self.cog._find_teams_for_franchise(self.ctx, self.role)
        if len(franchise_teams) > 0:
            await self.msg.edit(
                embed=ErrorEmbed(
                    description="Cannot remove a franchise that has teams enrolled"
                ),
                view=None,
            )
        else:
            gm_role = self.cog._find_role_by_name(self.ctx, self.cog.GM_ROLE)
            if self.gm in self.ctx.guild.members:
                await self.gm.remove_roles(gm_role)
            await self.role.delete()
            await self.cog.prefix_cog.remove_prefix(self.ctx, self.gm.name)
            await self.cog._set_user_nickname_prefix(self.ctx, None, self.gm)
            success_embed = discord.Embed(
                title="Success",
                description=f"**{self.name}** franchise was successfully removed.",
                color=discord.Color.green(),
            )
            await self.msg.edit(embed=success_embed, view=None)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Cancel creating new franchise"""
        deny_embed = discord.Embed(
            title="Cancelled",
            description=f"Remove franchise action was cancelled by user.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=deny_embed, view=None)
        self.stop()


class TransferFranchiseView(discord.ui.View):
    """Transfer franchise ownership view"""

    def __init__(
        self,
        cog: "TeamManager",
        ctx: Context,
        role: discord.Role,
        name: str,
        prefix: str,
        old_gm: Union[discord.Member, discord.Role],
        new_gm: Union[discord.Member, discord.User],
        timeout: float = 10.0,
    ):
        super().__init__()
        self.cog = cog
        self.ctx = ctx
        self.author = ctx.author
        self.name = name
        self.prefix = prefix
        self.role = role
        self.old_gm = old_gm
        self.new_gm = new_gm
        self.timeout = timeout
        self.msg = None

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        self.timedout = True
        await self.msg.edit(embed=TimeoutEmbed(author=self.author), view=None)

    async def prompt(self):
        """Prompt user for franchise transfer."""

        add_embed = discord.Embed(
            title="Transfer Franchise",
            description=f"Transfer ownership of **{self.name}** from **{self.old_gm.display_name}** to **{self.new_gm.display_name}**\n\n"
            "Are you sure?",
            color=discord.Color.blue(),
        )
        self.msg = await self.ctx.send(embed=add_embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            await interaction.response.send_message(
                content="Only the command author is allowed to interact.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Transfer franchise ownership"""
        # Rename franchise role
        franchise_name = self.cog.get_franchise_name_from_role(self.role)
        await self.role.edit(name=f"{franchise_name} ({self.new_gm.name})")

        # Change prefix association to new GM
        await self.cog.prefix_cog.remove_prefix(self.ctx, self.old_gm.name)
        await self.cog.prefix_cog.add_prefix(self.ctx, self.new_gm.name, self.prefix)
        await self.cog._set_user_nickname_prefix(self.ctx, self.prefix, self.new_gm)

        # Reassign roles for gm/franchise
        franchise_tier_roles = await self.cog._find_franchise_tier_roles(
            self.ctx, self.role
        )
        gm_role = self.cog._find_role_by_name(self.ctx, self.cog.GM_ROLE)
        transfer_roles = [gm_role, self.role]
        await self.new_gm.add_roles(*transfer_roles)

        # If old GM is still in server:
        if self.old_gm in self.ctx.guild.members:
            await self.old_gm.remove_roles(*transfer_roles)
            await self.cog._set_user_nickname_prefix(self.ctx, "", self.old_gm)
            former_gm_role = self.cog._find_role_by_name(self.ctx, "Former GM")
            if former_gm_role:
                await self.old_gm.add_roles(former_gm_role)

        success_embed = discord.Embed(
            title="Success",
            description=f"**{self.new_gm.name}** is the new General Manager for **{self.name}**.",
            color=discord.Color.green(),
        )
        await self.msg.edit(embed=success_embed, view=None)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Cancel transfer franchise ownership"""
        deny_embed = discord.Embed(
            title="Cancelled",
            description=f"Transfer franchise action was cancelled by user.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=deny_embed, view=None)
        self.stop()


class RebrandFranchiseView(discord.ui.View):
    """Rebrand Franchise View"""

    def __init__(
        self,
        cog: "TeamManager",
        ctx: Context,
        role: discord.Role,
        old_name: str,
        prefix: str,
        gm: Union[discord.Member, discord.User],
        new_name: str,
        new_teams: Sequence[str],
        old_teams: Sequence[str],
        timeout: float = 30.0,
    ):
        super().__init__()
        self.cog = cog
        self.ctx = ctx
        self.author = ctx.author
        self.old_name = old_name
        self.new_name = new_name
        self.prefix = prefix
        self.role = role
        self.gm = gm
        self.new_teams = new_teams
        self.old_teams = old_teams
        log.debug(f"New: {self.new_teams}")
        log.debug(f"Old: {self.old_teams}")
        self.timeout = timeout
        self.tier_roles: List[discord.Role] = []
        self.msg = None

    async def on_timeout(self):
        """Display time out message if we have reference to original"""
        self.timedout = True
        await self.msg.edit(embed=TimeoutEmbed(author=self.author), view=None)

    async def prompt(self):
        """Prompt user for franchise rebrand."""
        self.tier_roles = [
            role[1]
            for role in [
                await self.cog._roles_for_team(self.ctx, team)
                for team in self.old_teams
            ]
        ]
        log.debug
        # self.tier_roles.sort(key=lambda role: role.position, reverse=True)
        log.debug(f"Prompt Tier Roles: {self.tier_roles}")

        add_embed = discord.Embed(
            title="Rebrand Franchise",
            description=f"Are you sure you want to rebrand **{self.old_name}**?",
            color=discord.Color.blue(),
        )
        add_embed.add_field(name="New Name", value=self.new_name, inline=True)
        add_embed.add_field(name="New Prefix", value=self.prefix, inline=True)
        add_embed.add_field(name="\u200B", value="\u200B")  # newline
        add_embed.add_field(
            name="Tier",
            value="\n".join(tier.mention for tier in self.tier_roles),
            inline=True,
        )
        add_embed.add_field(
            name="Team Name",
            value="\n".join(team for team in self.new_teams),
            inline=True,
        )
        self.msg = await self.ctx.send(embed=add_embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the interaction user is the author. Allow or deny callbacks"""
        if interaction.user != self.author:
            await interaction.response.send_message(
                content="Only the command author is allowed to interact.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Rebrand Franchise"""
        # Rename Franchise
        franchise_role_name = "{} ({})".format(self.new_name, self.gm)
        await self.role.edit(name=franchise_role_name)

        # Update Prefix
        await self.cog.prefix_cog.remove_prefix(self.ctx, self.gm.name)
        await self.cog.prefix_cog.add_prefix(self.ctx, self.gm.name, self.prefix)

        # Fix player prefixes
        await self.cog._set_user_nickname_prefix(
            self.ctx, prefix=self.prefix, user=self.gm
        )
        log.debug(f"Updating rostered players prefix to {self.prefix}")
        for tier in self.tier_roles:
            for player in await self.cog.members_from_team(self.role, tier):
                log.debug(f"Fixing prefix for {player}")
                await self.cog._set_user_nickname_prefix(
                    self.ctx, prefix=self.prefix, user=player
                )

        # Remove old teams
        for old_team in self.old_teams:
            await self.cog._remove_team(self.ctx, old_team)

        # Add New Teams
        added = []
        failed = []
        for i in range(len(self.tier_roles)):
            tier_role = self.tier_roles[i]
            new_team = self.new_teams[i]
            if await self.cog._add_team(
                self.ctx, new_team, self.gm.name, tier_role.name
            ):
                added.append(new_team)
            else:
                failed.append(new_team)

        if failed:
            await self.msg.edit(
                embed=ErrorEmbed(
                    description=f"Something went wrong... Only {len(added)}/{len(added) + len(failed)} teams have been rebranded."
                )
            )
        else:
            success_embed = discord.Embed(
                title="Success",
                description=f"**{self.old_name}** has been rebranded to **{self.new_name}**.",
                color=discord.Color.green(),
            )
            await self.msg.edit(embed=success_embed, view=None)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Cancel Franchise Rebrand"""
        deny_embed = discord.Embed(
            title="Cancelled",
            description=f"Rebrand franchise action was cancelled by user.",
            color=discord.Color.red(),
        )
        await self.msg.edit(embed=deny_embed, view=None)
        self.stop()
