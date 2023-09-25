import logging
from sys import prefix
from typing import NewType
import discord
import re
import ast
import asyncio
import difflib

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks
from collections import Counter
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

from teamManager.embeds import ErrorEmbed
from teamManager.views import (
    AddFranchiseView,
    RemoveFranchiseView,
    TransferFranchiseView,
    RebrandFranchiseView,
)

from typing import NoReturn

log = logging.getLogger("red.RSCBot.teamManager")

defaults = {"Tiers": [], "Teams": [], "Team_Roles": {}}
verify_timeout = 30


class TeamManager(commands.Cog):
    """Used to match roles to teams"""

    FRANCHISE_ROLE_KEY = "Franchise Role"
    TIER_ROLE_KEY = "Tier Role"
    GM_ROLE = "General Manager"

    DE_ROLE = "Draft Eligible"
    FA_ROLE = "Free Agent"
    CAPTAN_ROLE = "Captain"
    IR_ROLE = "IR"
    PERM_FA_ROLE = "PermFA"
    SUBBED_OUT_ROLE = "Subbed Out"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567892, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.prefix_cog = bot.get_cog("PrefixManager")

    # Admin Commands
    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addTier(self, ctx, tier_name: str):
        """Add a tier to the tier list and creates corresponding roles.
        This will need to be done before any transactions can be done for players in this tier
        """
        await self._add_tier(ctx, tier_name)
        await ctx.send("Done")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addTiers(self, ctx, *, tier_names):
        """Add one or more tiers to the tier list and creates corresponding roles.
        This will need to be done before any transactions can be done for players in this tier
        """
        tier_names = tier_names.split()
        for tier_name in tier_names:
            await self._add_tier(ctx, tier_name)
        await ctx.send("Done")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def removeTier(self, ctx, tier_name: str) -> NoReturn:
        """Remove a tier from the tier list and the tier's corresponding roles"""
        removed = await self._remove_tier(ctx, tier_name)
        if removed:
            await ctx.send("Done.")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def removeAllTiers(self, ctx):
        """Removes all tiers and corresponding roles from the server"""
        # we need tiers
        tiers = await self.tiers(ctx)

        removed = []
        not_removed = []
        for tier in tiers:
            if await self._remove_tier(ctx, tier):
                removed.append(tier)
            else:
                not_removed.append(tier)

        if not_removed:
            message = (
                ":white_check_mark: The following tiers have been removed: {0}".format(
                    ", ".join(removed)
                )
            )
            message += "\n:x: The following tiers could not be removed: {0}".format(
                ", ".join(not_removed)
            )
            await ctx.send(message)
        else:
            await ctx.send("Removed {} tiers.".format(len(removed)))

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addFranchise(
        self, ctx, gm: discord.Member, franchise_prefix: str, *, franchise_name: str
    ) -> NoReturn:
        """Add a single franchise and prefix
        This will also create the franchise role in the format: <franchise name> (GM name)
        Afterwards it will assign this role and the General Manager role to the new GM and modify their nickname

        Examples:
        [p]addFranchise nullidea MEC Mechanics
        [p]addFranchise adammast OCE The Ocean
        [p]addFranchise Drupenson POA Planet of the Apes
        """
        if self.is_gm(gm):
            await ctx.send(
                embed=ErrorEmbed(description=f"{gm.name} is already a General Manager")
            )
            return

        add_view = AddFranchiseView(self, ctx, franchise_name, franchise_prefix, gm)
        await add_view.prompt()

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def removeFranchise(self, ctx, *, franchise_identifier: str) -> NoReturn:
        """Removes a franchise and all of its components (role, prefix) from the league.
        A franchise must not have any teams for this command to work.

        Examples:
        \t[p]removeFranchise adammast
        \t[p]removeFranchise OCE
        \t[p]removeFranchise The Ocean"""
        franchise_data = await self._get_franchise_data(ctx, franchise_identifier)
        if not franchise_data:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"No franchise could be found with the identifier: **{franchise_identifier}**"
                )
            )
            return

        franchise_role, gm_name, franchise_prefix, franchise_name = franchise_data

        # Convert GM name to discord.Member
        gm = self._find_member_by_name(ctx, gm_name)

        remove_view = RemoveFranchiseView(
            self, ctx, franchise_role, franchise_name, franchise_prefix, gm
        )
        await remove_view.prompt()

    @commands.command(aliases=["recoverFranchise", "claimFranchise"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def transferFranchise(
        self, ctx, new_gm: discord.Member, *, franchise_identifier: str
    ):
        """Transfer ownership of a franchise to a new GM, with the franchise's name, prefix, or previous GM.

        Examples:
        \t[p]transferFranchise nullidea adammast
        \t[p]recoverFranchise nullidea The Ocean
        \t[p]claimFranchise nullidea OCE"""

        if self.is_gm(new_gm):
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"**{new_gm}** already has the \x22General Manager\x22 role."
                )
            )
            return

        franchise_data = await self._get_franchise_data(ctx, franchise_identifier)
        if not franchise_data:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"No franchise could be found with the identifier: **{franchise_identifier}**"
                )
            )
            return

        franchise_role, old_gm_name, franchise_prefix, franchise_name = franchise_data
        # Convert GM name to discord.Member
        old_gm = self._find_member_by_name(ctx, old_gm_name)

        transfer_view = TransferFranchiseView(
            self, ctx, franchise_role, franchise_name, franchise_prefix, old_gm, new_gm
        )
        await transfer_view.prompt()

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def rebrandFranchise(
        self, ctx, franchise_identifier: str, prefix: str, franchise_name: str, *teams
    ):
        """Rebrands Franchise name, prefix and teams"""
        franchise_data = await self._get_franchise_data(ctx, franchise_identifier)
        if not franchise_data:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"No franchise could be found with the identifier: **{franchise_identifier}**"
                )
            )
            return

        (
            franchise_role,
            gm_name,
            old_franchise_prefix,
            old_franchise_name,
        ) = franchise_data
        log.debug(f"Rebrand Franchise Data: {franchise_data}")
        old_teams = await self._find_teams_for_franchise(ctx, franchise_role)
        log.debug(f"Franchise teams: {old_teams}")
        tier_roles = [
            role[1]
            for role in [await self._roles_for_team(ctx, team) for team in old_teams]
        ]
        log.debug(f"Tier Roles: {', '.join(tier.name for tier in tier_roles)}")
        log.debug(f"Old Teams: {old_teams}")
        if len(tier_roles) != len(teams):
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"**{old_franchise_name} ({old_franchise_prefix})** has **{len(tier_roles)}** teams, but **{len(teams)}** were provided.\n\n"
                    "Please make sure the number of teams match the current tier range."
                )
            )
            return

        tier_roles.sort(key=lambda role: role.position, reverse=True)
        gm = self._find_member_by_name(ctx, gm_name)

        rebrand_view = RebrandFranchiseView(
            self,
            ctx,
            franchise_role,
            franchise_name,
            prefix,
            gm,
            franchise_name,
            teams,
            old_teams,
        )
        await rebrand_view.prompt()

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addTeams(self, ctx, *teams_to_add):
        """Add the teams provided to the team list.

        Arguments:

        teams_to_add -- One or more teams in the following format:
        ```
        "['<team_name>','<gm_name>','<tier>']"
        ```
        Each team should be separated by a space.

        Examples:
        ```
        [p]addTeams "['Derechos','Shamu','Challenger']"
        [p]addTeams "['Derechos','Shamu','Challenger']" "['Barbarians','Snipe','Challenger']"
        ```
        """
        addedCount = 0
        try:
            for teamStr in teams_to_add:
                team = ast.literal_eval(teamStr)
                teamAdded = await self._add_team(ctx, *team)
                if teamAdded:
                    addedCount += 1
        except Exception as exc:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"{type(exc)} {exc}\n\n"
                    "**Arguments:**\n\n"
                    "`teams_to_add` -- One or more teams in the following format:\n"
                    "```\"['<team_name>','<gm_name>','<tier>']\"```\n"
                    "Each team should be separated by a space.\n\n"
                    "**Examples:**\n"
                    "```\n"
                    "[p]addTeams \"['Derechos','Shamu','Challenger']\"\n"
                    "[p]addTeams \"['Derechos','Shamu','Challenger']\" \"['Barbarians','Snipe','Challenger']\"\n"
                    "```\n"
                )
            )
            return

        add_embed = discord.Embed(
            title="Teams Added",
            description=f"Added {addedCount} team(s).",
            color=discord.Color.blue(),
        )
        await ctx.send(embed=add_embed)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addTeam(self, ctx, team_name: str, gm_name: str, tier: str):
        """Add a single team and it's corresponding roles to the file system to be used for transactions and match info"""
        teamAdded = await self._add_team(ctx, team_name, gm_name, tier)
        if teamAdded:
            await ctx.send("Done.")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def removeTeam(self, ctx, *, team_name: str):
        """Removes team from the file system. Team roles will be cleared as well"""
        if await self._remove_team(ctx, team_name):
            await ctx.send("Done.")
        else:
            await ctx.send(
                embed=ErrorEmbed(description=f"**{team_name}** does not exist.")
            )

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearTeams(self, ctx):
        """Removes all teams from the file system. Team roles will be cleared as well"""
        teams = await self._teams(ctx)
        team_roles = await self._team_roles(ctx)

        teams.clear()
        team_roles.clear()

        await self._save_teams(ctx, teams)
        await self._save_team_roles(ctx, team_roles)
        await ctx.send("Done.")

    # General Commands
    @commands.command(aliases=["getFranchises", "listFranchises"])
    @commands.guild_only()
    async def franchises(self, ctx):
        """Provides a list of all the franchises set up in the server
        including the name of the GM for each franchise"""
        franchise_roles = self._get_all_franchise_roles(ctx)
        franchise_roles.sort(key=lambda role: role.name.lower())

        prefixes = []
        franchises = []
        gms = []

        for role in franchise_roles:
            (
                franchise_role,
                gm_name,
                franchise_prefix,
                franchise_name,
            ) = await self._get_franchise_data(ctx, role)
            if franchise_prefix:
                prefixes.append(franchise_prefix)
            else:
                prefixes.append("-")
                log.debug(
                    f"Could not find prefix for {franchise_name} ({gm_name}). Found {franchise_prefix}."
                )

            franchises.append(franchise_name)
            gms.append(gm_name)

        embed = discord.Embed(title="Franchises", color=discord.Colour.blue())
        embed.add_field(
            name="Pfx.", value="{}\n".format("\n".join(prefixes)), inline=True
        )
        embed.add_field(
            name="Franchise", value="{}\n".format("\n".join(franchises)), inline=True
        )
        embed.add_field(
            name="General Manager", value="{}\n".format("\n".join(gms)), inline=True
        )
        if ctx.guild.icon.url:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    async def teams(self, ctx, *, franchise_tier_identifier: str):
        """Returns a list of teams based on the input.
        You can either give it the name of a franchise, a tier, or the prefix for a franchise.

        Examples:
        \t[p]teams The Ocean
        \t[p]teams Challenger
        \t[p]teams OCE"""

        # Franchise Identifier
        franchise_data = await self._get_franchise_data(ctx, franchise_tier_identifier)
        if franchise_data:
            try:
                (
                    franchise_role,
                    gm_name,
                    franchise_prefix,
                    franchise_name,
                ) = franchise_data
                await ctx.send(
                    embed=await self._format_teams_for_franchise(ctx, franchise_role)
                )
            except LookupError as exc:
                err_embed = discord.Embed(
                    title="Error", description=f"{exc}", color=discord.Color.red()
                )
                await ctx.send(embed=err_embed)
            return

        # Tier
        tiers = await self.tiers(ctx)
        for tier in tiers:
            if tier.lower() == franchise_tier_identifier.lower():
                await ctx.send(embed=await self._format_teams_for_tier(ctx, tier))
                return

        await ctx.send(
            embed=ErrorEmbed(
                description=f"No tier, franchise, prefix or GM with name: **{franchise_tier_identifier}**"
            )
        )

    @commands.command(aliases=["team"])
    @commands.guild_only()
    async def getTeam(self, ctx: commands.Context, player: discord.Member) -> None:
        """Fetches current team of discord user and returns the active roster"""
        log.debug(f"Fetching team name for {player}")
        team = await self.get_current_team_name(ctx, player)
        if team:
            log.debug(f"Found Team: {team}")
            await ctx.send(embed=await self.create_roster_embed(ctx, team))
        else:
            await ctx.send(f"{player.display_name} is not currently on a team.")

    @commands.command()
    @commands.guild_only()
    async def roster(self, ctx, *, team_name: str):
        """Shows all the members associated with a team including the GM"""
        team, found = await self._match_team_name(ctx, team_name)
        if found:
            franchise_role, tier_role = await self._roles_for_team(ctx, team)
            if franchise_role is None or tier_role is None:
                await ctx.send(
                    ErrorEmbed(
                        description=f"No franchise and tier roles set up for **{team}**"
                    )
                )
                return
            await ctx.send(embed=await self.create_roster_embed(ctx, team))
        else:
            message = f"No team with name: **{team_name}**"
            if len(team) > 0:
                message += "\n\nDo you mean one of these teams?"
                for possible_team in team:
                    message += " `{0}`".format(possible_team)
            await ctx.send(embed=ErrorEmbed(description=message))

    @commands.command(aliases=["tiers", "getTiers"])
    @commands.guild_only()
    async def listTiers(self, ctx):
        """Provides a list of all the tiers set up in the server"""
        tiers = await self.tiers(ctx)
        tier_roles = [self._get_tier_role(ctx, tier) for tier in tiers]
        tier_roles.sort(key=lambda role: role.position, reverse=True)
        tier_embed = discord.Embed(
            title=f"{ctx.guild.name} Tiers", color=discord.Color.blue()
        )
        if tiers:
            tier_embed.description = "\n".join(role.mention for role in tier_roles)
        else:
            tier_embed.description = "No tiers set up in this server."
        await ctx.send(embed=tier_embed)

    @commands.command(aliases=["captain", "cptn", "cptns"])
    @commands.guild_only()
    async def captains(self, ctx, *, franchise_tier_prefix: str):
        """Returns a list of team captains under a tier or franchise based on the input.
        You can either give it the name of a tier, or a franchise identifier (prefix, name, or GM name).

        Examples:
        \t[p]captains The Ocean
        \t[p]captains Challenger
        \t[p]captains OCE"""

        found = False
        # Prefix
        prefixes = await self.prefix_cog._prefixes(ctx)
        if len(prefixes.items()) > 0:
            for key, value in prefixes.items():
                if (
                    franchise_tier_prefix.lower() == value.lower()
                    or franchise_tier_prefix.lower() == key.lower()
                ):
                    gm_name = key
                    franchise_role = self._get_franchise_role(ctx, gm_name)
                    found = True

        # Franchise name
        if not found:
            franchise_role = self.get_franchise_role_from_name(
                ctx, franchise_tier_prefix
            )
            if franchise_role is not None:
                found = True

        # find captains for franchise by franchise role
        if found:
            await ctx.send(
                embed=await self._format_franchise_captains(ctx, franchise_role)
            )
            return

        # Tier
        tiers = await self.tiers(ctx)
        for tier in tiers:
            if tier.lower() == franchise_tier_prefix.lower():
                found = True
                await ctx.send(embed=await self._format_tier_captains(ctx, tier))
                return

        await ctx.send(
            embed=ErrorEmbed(
                description=f"No franchise, tier, or prefix with name: **{franchise_tier_prefix}**"
            )
        )

    @commands.command(aliases=["getTeams"])
    @commands.guild_only()
    async def listTeams(self, ctx):
        """Provides a list of all the teams set up in the server"""
        teams = await self._teams(ctx)
        if teams:
            messages = []
            message = "Teams set up in this server:\n"
            for team in teams:
                message += "\n{0}".format(team)
                if len(message) > 1900:
                    messages.append(message)
                    message = ""
            if message:
                messages.append(message)
            for msg in messages:
                await ctx.send("{0}{1}{0}".format("```", msg))
        else:
            await ctx.send(
                embed=ErrorEmbed(description="No teams set up in this server.")
            )

    @commands.command()
    @commands.guild_only()
    async def teamRoles(self, ctx, team_name: str):
        """Prints out the franchise and tier role that corresponds with the given team"""
        try:
            franchise_role, tier_role = await self._roles_for_team(ctx, team_name)
        except LookupError:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"No franchise or tier roles found for **{team_name}**"
                )
            )
            return

        role_embed = discord.Embed(
            title=f"{team_name} Team Roles",
            description=f"Franchise Role: **{franchise_role.name}**\n"
            f"Tier Role: **{tier_role.name}**",
            color=discord.Color.blue(),
        )
        await ctx.send(embed=role_embed)

    @commands.command(aliases=["fa", "fas"])
    @commands.guild_only()
    async def freeAgents(self, ctx, tier: str, filter: str = None):
        """Gets a list of all free agents in a specific tier
        - Filters for PermFA: perm, permfa, restricted, p, r, rfa, permanent
        - Filters for signable FAs: non-perm, unrestricted, u, ufa, signable
        """
        tiers = await self.tiers(ctx)
        tier_name = None
        for _tier in tiers:
            if tier.lower() == _tier.lower():
                tier_name = _tier
                break

        perm_fa_filters = ["perm", "permfa", "restricted", "p", "r", "rfa", "permanent"]
        signable_fa_filters = [
            "nonperm",
            "non-perm",
            "unrestricted",
            "u",
            "ufa",
            "signable",
        ]

        # Validate tier name
        if tier_name is None:
            await ctx.send(
                embed=ErrorEmbed(description=f"No tier with name: **{tier}**")
            )
            return

        # Validate filters
        if filter:
            filter = filter.lower()
            if filter not in perm_fa_filters and filter not in signable_fa_filters:
                await ctx.send(
                    embed=ErrorEmbed(description=f"Invalid FA filter: **{filter}**")
                )
                return

        # Validate FA role exists for Tier
        fa_role = self._find_role_by_name(ctx, tier_name + "FA")
        if fa_role is None:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"No free agent role with name: **{tier_name}FA**"
                )
            )
            return

        perm_fa_role = self._find_role_by_name(ctx, self.PERM_FA_ROLE)

        # Get all of the PermFA and FAs in a dictionary object.
        fa_Dictionary = {"PermFA": [], "FA": []}

        for member in ctx.message.guild.members:
            if fa_role in member.roles:
                if filter:  # Optional filter for PermFA and signable FAs
                    if filter in perm_fa_filters:
                        if perm_fa_role is not None and perm_fa_role in member.roles:
                            fa_Dictionary["PermFA"].append(member.display_name)
                    elif filter in signable_fa_filters:
                        if (
                            perm_fa_role is not None
                            and perm_fa_role not in member.roles
                        ):
                            fa_Dictionary["FA"].append(member.display_name)
                else:
                    if perm_fa_role is not None and perm_fa_role in member.roles:
                        fa_Dictionary["PermFA"].append(member.display_name)
                    else:
                        fa_Dictionary["FA"].append(member.display_name)

        if len(fa_Dictionary["FA"]) == 0 and len(fa_Dictionary["PermFA"]) == 0:
            message = "No matching free agents found."
        else:
            message = "```"
            for fa in sorted(fa_Dictionary["FA"], key=str.casefold):
                message += "\n{0}".format(fa)
            for permFA in sorted(fa_Dictionary["PermFA"], key=str.casefold):
                message += "\n{0} {1}".format(permFA, "(Permanent FA)")
            message += "```"

        color = discord.Colour.blue()
        for role in ctx.guild.roles:
            if role.name.lower() == tier_name.lower():
                color = role.color
        embed = discord.Embed(
            title="{0} Free Agents".format(tier_name), color=color, description=message
        )
        embed.set_thumbnail(url=ctx.guild.icon)

        await ctx.send(embed=embed)

    @commands.command(aliases=["de", "des", "DEs"])
    @commands.guild_only()
    async def draftEligibles(self, ctx):
        """Gets a list of all draft eligible players"""
        # Get all members with DE role
        de_role = None
        for role in ctx.guild.roles:
            if role.name == self.DE_ROLE:
                de_role = role
                break

        if not de_role:
            await ctx.send(
                embed=ErrorEmbed(
                    description="Draft Eligible role is not configured in this server."
                )
            )
            return

        de_members = []
        for member in ctx.guild.members:
            if de_role in member.roles:
                de_members.append(member)

        if not de_members:
            empty_embed = discord.Embed(
                title="Draft Eligble Players",
                description="There are currently no Draft Eligible players.",
                color=discord.Color.yellow(),
            )
            return await ctx.send(embed=empty_embed)

        # Display DE members in <2000 chunks
        de_members.sort(key=lambda member: member.display_name, reverse=True)
        output_blocks = []
        output_segment = "```"
        for member in de_members:
            if len(output_segment) + len(member.display_name) <= 1900:
                output_segment += "\n{}".format(member.display_name)
            else:
                output_blocks.append(output_segment)
                output_segment += "\n```"
                output_segment += "\n{}".format(member.display_name)

        output_segment += "\n```"
        output_blocks.append(output_segment)

        for i in range(len(output_blocks)):
            title = (
                "Draft Eligible Players ({}/{})".format(i + 1, len(output_blocks))
                if len(output_blocks) > 1
                else "Draft Eligible Players"
            )
            output = output_blocks[i]
            embed = discord.Embed(title=title, description=output, color=de_role.color)
            await ctx.send(embed=embed)

    # Helper Functions

    async def _react_prompt(self, ctx, prompt, if_not_msg=None):
        user = ctx.message.author
        react_msg = await ctx.send(prompt)
        start_adding_reactions(react_msg, ReactionPredicate.YES_OR_NO_EMOJIS)
        try:
            pred = ReactionPredicate.yes_or_no(react_msg, user)
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=verify_timeout)
            if pred.result:
                return True
            if if_not_msg:
                await ctx.send(if_not_msg)
            return False
        except asyncio.TimeoutError:
            await ctx.send(
                "Sorry {}, you didn't react quick enough. Please try again.".format(
                    user.mention
                )
            )
            return False

    async def _add_tier(self, ctx, tier_name):
        await self._create_role(ctx, tier_name)
        await self._create_role(ctx, "{0}FA".format(tier_name))
        tiers = await self.tiers(ctx)
        tiers.append(tier_name)
        await self._save_tiers(ctx, tiers)

    async def _get_franchise_data(self, ctx, franchise_identifier):
        """Returns franchise data as 4-set-tuple from a franchise identifier (Franchise name, prefix, role, GM name)."""
        franchise_found = False

        # Role Identifier
        if franchise_identifier in self._get_all_franchise_roles(ctx):
            franchise_found = True
            franchise_role = franchise_identifier
            gm_name = self._get_gm_name(franchise_role)
            franchise_prefix = await self.prefix_cog._get_gm_prefix(ctx, gm_name)
            franchise_name = self.get_franchise_name_from_role(franchise_role)

        # GM/Prefix Identifier
        prefixes = await self.prefix_cog._prefixes(ctx)
        if not franchise_found and prefixes:
            for key, value in prefixes.items():
                if (
                    franchise_identifier.lower() == key.lower()
                    or franchise_identifier.lower() == value.lower()
                ):
                    franchise_found = True
                    gm_name = key
                    franchise_prefix = value
                    franchise_role = self._get_franchise_role(ctx, gm_name)
                    franchise_name = self.get_franchise_name_from_role(franchise_role)

        # Franchise name identifier
        if not franchise_found:
            franchise_role = self.get_franchise_role_from_name(
                ctx, franchise_identifier
            )
            if franchise_role:
                franchise_found = True
                franchise_name = self.get_franchise_name_from_role(franchise_role)
                gm_name = self._get_gm_name(franchise_role)
                franchise_prefix = await self.prefix_cog._get_gm_prefix(ctx, gm_name)

        if franchise_found:
            return franchise_role, gm_name, franchise_prefix, franchise_name
        return None

    def is_gm(self, member):
        for role in member.roles:
            if role.name == self.GM_ROLE:
                return True
        return False

    def is_captain(self, member):
        for role in member.roles:
            if role.name == self.CAPTAN_ROLE:
                return True
        return False

    def is_IR(self, member):
        for role in member.roles:
            if role.name == self.IR_ROLE:
                return True
        return False

    def is_subbed_out(self, member):
        if self.is_IR(member):
            return True
        for role in member.roles:
            if role.name == self.SUBBED_OUT_ROLE:
                return True
        return False

    async def teams_for_user(self, ctx, user):
        franchise_role = self.get_current_franchise_role(user)
        if self.is_gm(user):
            return await self._find_teams_for_franchise(ctx, franchise_role)
        tiers = await self.tiers(ctx)
        teams = []
        for role in user.roles:
            if role.name in tiers:
                tier_role = role
                team_name = await self._find_team_name(ctx, franchise_role, tier_role)
                teams.append(team_name)
        return teams

    async def members_from_team(self, franchise_role, tier_role):
        """Retrieve the list of all users that are on the team
        indicated by the provided franchise_role and tier_role.
        """
        team_members = []
        for member in franchise_role.members:
            if tier_role in member.roles:
                team_members.append(member)
        return team_members

    async def create_roster_embed(self, ctx, team_name):
        franchise_role, tier_role = await self._roles_for_team(ctx, team_name)
        message = await self.format_roster_info(ctx, team_name)

        embed = discord.Embed(description=message, color=tier_role.color)
        emoji = await self._get_franchise_emoji(ctx, franchise_role)
        if emoji:
            embed.set_thumbnail(url=emoji.url)
        else:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        return embed

    async def format_roster_info(self, ctx, team_name: str):
        franchise_role, tier_role = await self._roles_for_team(ctx, team_name)
        team_members = await self.members_from_team(franchise_role, tier_role)
        captain = await self._get_team_captain(ctx, franchise_role, tier_role)

        message = "```\n{0} - {1} - {2}:\n".format(
            team_name, franchise_role.name, tier_role.name
        )
        subbed_out_message = ""

        for member in team_members:
            role_tags = ["C"] if member == captain else []
            user_message = await self._format_team_member_for_message(
                ctx, member, *role_tags
            )
            if self.is_subbed_out(member):
                subbed_out_message += "  {0}\n".format(user_message)
            else:
                message += "  {0}\n".format(user_message)

        if not team_members:
            message += "\nNo members found."
        if not subbed_out_message == "":
            message += "\nSubbed Out:\n{0}".format(subbed_out_message)
        message += "```"
        return message

    async def _format_franchise_captains(self, ctx, franchise_role: discord.Role):
        teams = await self._find_teams_for_franchise(ctx, franchise_role)
        captains_mentioned = []
        captains_username = []
        team_names = []
        team_tiers = []

        gm = self._get_gm(ctx, franchise_role)
        message = "**General Manager:** {0}".format(gm.mention)
        if teams:
            for team in teams:
                f_role, tier_role = await self._roles_for_team(ctx, team)
                captain = await self._get_team_captain(ctx, franchise_role, tier_role)
                team_names.append("{0} ({1})".format(team, tier_role.name))
                team_tiers.append(tier_role.name)

                if captain:
                    # captains_mentioned.append(captain.mention) # mention disabled
                    captains_username.append(str(captain))
                else:
                    # captains_mentioned.append("(No captain)")
                    # .append("N/A") # mention disabled
                    captains_username.append("(No captain)")
        else:
            message += "\nNo teams have been made."

        franchise_name = self._extract_franchise_name_from_role(franchise_role)
        embed = discord.Embed(
            title="{0} Captains:".format(franchise_name),
            color=discord.Colour.blue(),
            description=message,
        )
        embed.add_field(
            name="Team", value="{}\n".format("\n".join(team_names)), inline=True
        )
        # embed.add_field(name="Tier", value="{}\n".format("\n".join(team_tiers)), inline=True)
        # embed.add_field(name="Captain", value="{}\n".format("\n".join(captains_mentioned)), inline=True)  # name = Captain
        embed.add_field(
            name="Captain",
            value="{}\n".format("\n".join(captains_username)),
            inline=True,
        )  # name = Username

        emoji = await self._get_franchise_emoji(ctx, franchise_role)
        if emoji:
            embed.set_thumbnail(url=emoji.url)
        else:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        return embed

    async def _format_tier_captains(self, ctx, tier: str):
        tier_role = self._get_tier_role(ctx, tier)
        teams = await self._find_teams_for_tier(ctx, tier)
        captains = []
        captainless_teams = []
        for team in teams:
            franchise_role, tier_role = await self._roles_for_team(ctx, team)
            captain = await self._get_team_captain(ctx, franchise_role, tier_role)
            if captain:
                captains.append((captain, team))
            else:
                gm = self._get_gm(ctx, franchise_role)
                captainless_teams.append((gm, team))

        # dumb.
        captains.sort(key=lambda captain_team: captain_team[1].casefold())
        captainless_teams.sort(key=lambda gm_team: gm_team[1].casefold())

        embed = discord.Embed(
            title="{0} Captains:".format(tier_role.name), color=tier_role.color
        )

        captains_formatted = []
        captains_mentioned_formatted = []
        teams_formatted = []
        if captains:
            for captain, team in captains:
                captains_formatted.append(str(captain))
                captains_mentioned_formatted.append(captain.mention)
                teams_formatted.append(team)

        if captainless_teams:
            for gm, team in captainless_teams:
                captains_formatted.append("(No captain)")  # .append("N/A")
                # captains_mentioned_formatted.append("(No Captain)")
                teams_formatted.append(team)

        embed.add_field(
            name="Team", value="{}\n".format("\n".join(teams_formatted)), inline=True
        )
        # embed.add_field(name="Captain", value="{}\n".format("\n".join(captains_mentioned_formatted)), inline=True)    # mention disabled
        embed.add_field(
            name="Captain",
            value="{}\n".format("\n".join(captains_formatted)),
            inline=True,
        )  # name="Username"
        return embed

    async def _get_team_captain(
        self, ctx, franchise_role: discord.Role, tier_role: discord.Role
    ):
        captain_role = self._find_role_by_name(ctx, "Captain")
        members = await self.members_from_team(franchise_role, tier_role)
        for member in members:
            if captain_role in member.roles:
                return member
        return None

    async def _create_role(self, ctx, role_name: str):
        """Creates and returns a new Guild Role"""
        for role in ctx.guild.roles:
            if role.name == role_name:
                await ctx.send(
                    'The role "{0}" already exists in the server.'.format(role_name)
                )
                return None
        return await ctx.guild.create_role(name=role_name)

    async def _format_team_member_for_message(self, ctx, member, *args):
        extraRoles = list(args)
        if self.is_gm(member):
            extraRoles.insert(0, "GM")
        if self.is_IR(member):
            extraRoles.append("IR")
        roleString = ""
        if extraRoles:
            roleString = " ({0})".format("|".join(extraRoles))
        return "{0}{1}".format(member.display_name, roleString)

    async def _format_teams_for_franchise(self, ctx, franchise_role):
        teams = await self._find_teams_for_franchise(ctx, franchise_role)
        tiers = [(await self._roles_for_team(ctx, team))[1].name for team in teams]
        embed = discord.Embed(
            title="{0}".format(franchise_role.name), color=discord.Colour.blue()
        )

        embed.add_field(name="Tier", value="{}\n".format("\n".join(tiers)), inline=True)
        embed.add_field(name="Team", value="{}\n".format("\n".join(teams)), inline=True)

        emoji = await self._get_franchise_emoji(ctx, franchise_role)
        if emoji:
            embed.set_thumbnail(url=emoji.url)
        else:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        return embed

    async def _format_teams_for_tier(self, ctx, tier):
        teams = await self._find_teams_for_tier(ctx, tier)
        franchises = [
            self._extract_franchise_name_from_role(
                (await self._roles_for_team(ctx, team))[0]
            )
            for team in teams
        ]
        teams_message = ""
        for team in teams:
            franchise_role = (await self._roles_for_team(ctx, team))[0]
            gmNameFromRole = re.findall(r"(?<=\().*(?=\))", franchise_role.name)[0]
            teams_message += "\n\t{0} ({1})".format(team, gmNameFromRole)

        color = discord.Colour.blue()
        for role in ctx.guild.roles:
            if role.name.lower() == tier.lower():
                color = role.color

        embed = discord.Embed(title="{0} Tier Teams".format(tier), color=color)

        if teams and franchises:
            embed.add_field(
                name="Team", value="{}\n".format("\n".join(teams)), inline=True
            )
            embed.add_field(
                name="Franchise",
                value="{}\n".format("\n".join(franchises)),
                inline=True,
            )
        else:
            embed.description = "No teams have been set up for this tier."
        embed.set_thumbnail(url=ctx.guild.icon.url)
        return embed

    async def tier_roles(self, ctx):
        tier_roles = [
            (self._find_role_by_name(ctx, tier_name))
            for tier_name in (await self.tiers(ctx))
        ]
        tier_roles.sort(key=lambda role: role.position, reverse=True)
        return tier_roles

    async def tiers(self, ctx):
        return await self.config.guild(ctx.guild).Tiers()

    async def _remove_tier(self, ctx, tier_name: str) -> bool:
        if len(await self._find_teams_for_tier(ctx, tier_name)) > 0:
            return False
        else:
            tier_role = self._get_tier_role(ctx, tier_name)
            tier_fa_role = self._find_role_by_name(ctx, "{0}FA".format(tier_name))
            if tier_role:
                await tier_role.delete()
            if tier_fa_role:
                await tier_fa_role.delete()
            tiers = await self.tiers(ctx)
            try:
                tiers.remove(tier_name)
            except ValueError:
                err_embed = ErrorEmbed(
                    description=f"**{tier_name}** is not a valid tier."
                )
                await ctx.send(embed=err_embed)
                return False
            await self._save_tiers(ctx, tiers)
            return True

    async def _save_tiers(self, ctx, tiers):
        await self.config.guild(ctx.guild).Tiers.set(tiers)

    def _extract_tier_from_role(self, team_role):
        tier_matches = re.findall(r"\w*\b(?=\))", team_role.name)
        return None if not tier_matches else tier_matches[0]

    def _extract_franchise_name_from_role(self, franchise_role: discord.Role):
        franchise_name_gm = franchise_role.name
        franchise_name = franchise_name_gm[: franchise_name_gm.index(" (")]
        return franchise_name

    async def _add_team(self, ctx, team_name: str, gm_name: str, tier: str):
        teams = await self._teams(ctx)
        team_roles = await self._team_roles(ctx)

        tier_role = self._get_tier_role(ctx, tier)

        franchise_role = self._get_franchise_role(ctx, gm_name)

        # Validation of input
        # There are other validations we could do, but don't
        #     - that there aren't extra args
        errors = []
        if not team_name:
            errors.append("Team name not found.")
        if not gm_name:
            errors.append("GM name not found.")
        if not tier_role:
            errors.append("Tier role not found.")
        if not franchise_role:
            errors.append("Franchise role not found.")
        if errors:
            errorfmt = "\n".join(errors)
            await ctx.send(embed=ErrorEmbed(description=errorfmt))
            return False

        try:
            teams.append(team_name)
            team_data = team_roles.setdefault(team_name, {})
            team_data["Franchise Role"] = franchise_role.id
            team_data["Tier Role"] = tier_role.id
        except:
            return False
        await self._save_teams(ctx, teams)
        await self._save_team_roles(ctx, team_roles)
        return True

    async def _remove_team(self, ctx, team_name: str) -> bool:
        try:
            franchise_role, tier_role = await self._roles_for_team(ctx, team_name)
            teams = await self._teams(ctx)
            team_roles = await self._team_roles(ctx)
            teams.remove(team_name)
            del team_roles[team_name]
        except (ValueError, LookupError):
            return False
        await self._save_teams(ctx, teams)
        await self._save_team_roles(ctx, team_roles)
        return True

    def _get_tier_role(self, ctx, tier: str):
        roles = ctx.guild.roles
        for role in roles:
            if role.name.lower() == tier.lower():
                return role
        return None

    async def _teams(self, ctx):
        return await self.config.guild(ctx.guild).Teams()

    async def _save_teams(self, ctx, teams):
        await self.config.guild(ctx.guild).Teams.set(teams)

    async def _team_roles(self, ctx):
        return await self.config.guild(ctx.guild).Team_Roles()

    async def _save_team_roles(self, ctx, team_roles):
        await self.config.guild(ctx.guild).Team_Roles.set(team_roles)

    def _find_role(self, ctx, role_id):
        for role in ctx.guild.roles:
            if role.id == role_id:
                return role
        raise LookupError("No role with id: {0} found in server roles".format(role_id))

    def _find_role_by_name(self, ctx, role_name):
        for role in ctx.message.guild.roles:
            if role.name.lower() == role_name.lower():
                return role
        return None

    def _find_member_by_name(self, ctx, member_name: str):
        for member in ctx.guild.members:
            if member.name == member_name:
                return member
        return None

    def _get_franchise_role(self, ctx, gm_name):
        for role in ctx.message.guild.roles:
            try:
                gmNameFromRole = re.findall(r"(?<=\().*(?=\))", role.name)[0]
                if gmNameFromRole == gm_name:
                    return role
            except:
                continue

    def _get_all_franchise_roles(self, ctx):
        franchise_roles = []
        for role in ctx.message.guild.roles:
            try:
                gmNameFromRole = re.findall(r"(?<=\().*(?=\))", role.name)[0]
                if gmNameFromRole is not None:
                    franchise_roles.append(role)
            except:
                continue
        return franchise_roles

    async def _roles_for_team(self, ctx, team_name: str):
        teams = await self._teams(ctx)
        if teams and team_name in teams:
            team_roles = await self._team_roles(ctx)
            team_data = team_roles.setdefault(team_name, {})
            franchise_role_id = team_data["Franchise Role"]
            franchise_role = self._find_role(ctx, franchise_role_id)
            tier_role_id = team_data["Tier Role"]
            tier_role = self._find_role(ctx, tier_role_id)
            return (franchise_role, tier_role)
        else:
            raise LookupError("No team with name: {0}".format(team_name))

    async def _find_team_name(self, ctx, franchise_role, tier_role):
        teams = await self._teams(ctx)
        for team in teams:
            if await self._roles_for_team(ctx, team) == (franchise_role, tier_role):
                return team
        return

    async def _find_teams_for_franchise(self, ctx, franchise_role):
        franchise_teams = []
        teams = await self._teams(ctx)
        for team in teams:
            if (await self._roles_for_team(ctx, team))[0] == franchise_role:
                franchise_teams.append(team)
        return franchise_teams

    async def _find_franchise_tier_roles(self, ctx, franchise_role: discord.Role):
        franchise_tier_roles = []
        teams = await self._teams(ctx)
        for team in teams:
            if (await self._roles_for_team(ctx, team))[0] == franchise_role:
                tier_role = (await self._roles_for_team(ctx, team))[1]
                franchise_tier_roles.append(tier_role)
        return franchise_tier_roles

    async def _get_franchise_tier_team(
        self, ctx, franchise_role: discord.Role, tier_role: discord.Role
    ):
        teams = await self._teams(ctx)
        for team in teams:
            if (await self._roles_for_team(ctx, team)) == (franchise_role, tier_role):
                return team
        return None

    def get_current_franchise_role(self, user: discord.Member):
        for role in user.roles:
            try:
                gmNameFromRole = re.findall(r"(?<=\().*(?=\))", role.name)[0]
                if gmNameFromRole:
                    return role
            except:
                continue
        return None

    async def get_current_tier_role(self, ctx, user: discord.Member):
        tierList = await self.tiers(ctx)
        for role in user.roles:
            if role.name in tierList:
                return role
        return None

    async def get_current_team_name(self, ctx, user: discord.Member):
        tier_role = await self.get_current_tier_role(ctx, user)
        franchise_role = self.get_current_franchise_role(user)
        return await self._find_team_name(ctx, franchise_role, tier_role)

    def get_player_nickname(self, user: discord.Member):
        if user.nick is not None:
            array = user.nick.split(" | ", 1)
            if len(array) == 2:
                currentNickname = array[1].strip()
            else:
                currentNickname = array[0]
            return currentNickname

        return user.global_name

    async def _set_user_nickname_prefix(self, ctx, prefix: str, user: discord.member):
        try:
            if prefix:
                await user.edit(nick=f"{prefix} | {self.get_player_nickname(user)}")
            else:
                await user.edit(nick=self.get_player_nickname(user))
        except discord.Forbidden:
            await ctx.send(f"Changing nickname forbidden for user: **{user.name}**")

    def get_franchise_role_from_name(self, ctx, franchise_name: str):
        for role in ctx.message.guild.roles:
            try:
                matchedString = re.findall(r".+?(?= \()", role.name)[0]
                if matchedString.lower() == franchise_name.lower():
                    return role
            except:
                continue

    def get_franchise_name_from_role(self, franchise_role: discord.Role):
        end_of_name = franchise_role.name.rindex("(") - 1
        return franchise_role.name[0:end_of_name]

    async def _match_team_name(self, ctx, team_name):
        teams = await self._teams(ctx)
        for team in teams:
            if team_name.lower() == team.lower():
                return team, True
        return difflib.get_close_matches(team_name, teams, n=3, cutoff=0.4), False

    async def _match_tier_name(self, ctx, tier_name):
        tiers = await self.tiers(ctx)
        for tier in tiers:
            if tier_name.lower() == tier.lower():
                return tier
        close_match = difflib.get_close_matches(tier_name, tiers, n=1, cutoff=0.6)
        if len(close_match) > 0:
            return close_match[0]
        return None

    async def _find_teams_for_tier(self, ctx, tier):
        teams_in_tier = []
        teams = await self._teams(ctx)
        for team in teams:
            team_tier = (await self._roles_for_team(ctx, team))[1]
            if team_tier.name.lower() == tier.lower():
                teams_in_tier.append(team)
        return teams_in_tier

    async def _get_franchise_emoji(self, ctx, franchise_role):
        prefix = await self.prefix_cog._get_franchise_prefix(ctx, franchise_role)
        gm_name = self._get_gm_name(franchise_role)
        if prefix:
            for emoji in ctx.guild.emojis:
                lower_emoji = emoji.name.lower()
                if lower_emoji == prefix.lower() or lower_emoji == gm_name.lower():
                    return emoji
        return None

    async def get_franchise_emoji_url(self, ctx, franchise_role):
        emoji = await self._get_franchise_emoji(ctx, franchise_role)
        if emoji:
            return emoji.url

        guild_icon_url = franchise_role.guild.icon.url
        if guild_icon_url:
            return guild_icon_url

        return None

    # TODO: remove unused ctx - must remove from other references
    def _get_gm(self, ctx, franchise_role: discord.Role):
        for member in franchise_role.members:
            if self.is_gm(member):
                return member

    def _get_gm_name(self, franchise_role):
        try:
            return re.findall(r"(?<=\().*(?=\))", franchise_role.name)[0]
        except:
            raise LookupError(
                "GM name not found from role {0}".format(franchise_role.name)
            )

    async def _get_user_tier_roles(self, ctx, user: discord.Member):
        user_tier_roles = []
        for tier_name in await self.tiers(ctx):
            tier_role = self._find_role_by_name(ctx, tier_name)
            if tier_role in user.roles:
                user_tier_roles.append(tier_role)
        return user_tier_roles

    async def get_active_members_by_team_name(self, ctx, team_name):
        franchise_role, tier_role = await self._roles_for_team(ctx, team_name)
        team_members = await self.members_from_team(franchise_role, tier_role)
        active_members = []
        for member in team_members:
            if not self.is_subbed_out(member):
                active_members.append(member)
        return active_members
