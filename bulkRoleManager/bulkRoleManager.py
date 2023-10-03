import discord
import csv
import os
import asyncio
import logging

from redbot.core import commands, Config, checks
from discord import File
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

from dmHelper import DMHelper
from teamManager import TeamManager

from bulkRoleManager.embeds import ErrorEmbed

from typing import NoReturn, Optional

log = logging.getLogger("red.RSCBot.bulkRoleManager")

defaults = {"DraftEligibleMessage": None, "PermFAMessage": None}

TROPHY_EMOJI = "\U0001F3C6"  # :trophy:
GOLD_MEDAL_EMOJI = "\U0001F3C5"  # gold medal
FIRST_PLACE_EMOJI = "\U0001F947"  # first place medal
STAR_EMOJI = "\U00002B50"  # :star:
LEAGUE_AWARDS = [TROPHY_EMOJI, GOLD_MEDAL_EMOJI, FIRST_PLACE_EMOJI, STAR_EMOJI]


class BulkRoleManager(commands.Cog):
    """Used to manage roles role for large numbers of members"""

    PERM_FA_ROLE = "PermFA"
    DEV_LEAGUE_ROLE = "Dev League Interest"

    def __init__(self, bot):
        self.config = Config.get_conf(
            self, identifier=1234567897, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.team_manager_cog: TeamManager = bot.get_cog("TeamManager")
        self.dm_helper_cog: DMHelper = bot.get_cog("DMHelper")
        self.discord_bot = bot

    # region general
    @commands.command()
    @commands.guild_only()
    async def getAllWithRole(
        self, ctx, role: discord.Role, nickname: bool = False
    ) -> None:
        """Prints out a list of members with the specific role"""
        count = 0
        messages = []
        message = ""
        # Check if role has any members first
        if len(role.members) == 0:
            noUsersEmbed = discord.Embed(
                title="Results",
                description=f"Nobody has the **{role.name}** role.",
                color=discord.Color.orange(),
            )
            noUsersEmbed.set_footer(text="Found 0 user(s) in total.")
            await ctx.send(embed=noUsersEmbed)
            return

        # Debug data for message splitting.
        total_len_display = sum(len(i.display_name) for i in role.members)
        total_len_name = sum(len(i.name) for i in role.members)
        total_len_id = sum(len(str(i.id)) for i in role.members)

        log.debug(
            f"role.members length. Display Name: {total_len_display} Username: {total_len_name} "
        )

        for member in role.members:
            if nickname:
                message += f"{member.display_name}\n"
            else:
                message += f"{member.name}#{member.discriminator}\n"
            # Not sure how we would have a message > 1900 characters.
            if len(message) > 1900:
                messages.append(message)
                message = ""
            count += 1

        if message:
            messages.append(message)

        await ctx.send(f"Players with **{role.name}** role:\n")
        for msg in messages:
            await ctx.send(f"```{msg}```")
        await ctx.send(
            f":white_check_mark: {count} player(s) have the {role.name} role"
        )

    @commands.command()
    @commands.guild_only()
    async def getAllWithRoles(self, ctx, *roles: discord.Role) -> None:
        """Displays a list of members with all of the roles provided"""
        log.debug(f"Getting all members with: {roles}")
        matches = list(set.intersection(*map(set, [r.members for r in roles])))
        log.debug(f"Matches: {matches}")

        if not matches:
            noUsersEmbed = discord.Embed(
                title="Members with Intersecting Roles",
                description="No users intersect those roles.",
                color=discord.Color.orange(),
            )
            await ctx.send(embed=noUsersEmbed)
            return

        # Check for character max being exceeded (6000 total in embed or 1024 per field)
        nicks = "\n".join([f"{p.display_name}" for p in matches])
        usernames = "\n".join([f"{p.name}#{p.discriminator}" for p in matches]),
        ids = "\n".join(str(p.id) for p in matches)

        if (
            len(nicks) > 1024 or
            len(usernames) > 1024 or
            len(ids) > 1024
        ):
            msg = "\n".join([f"{p.display_name}:{p.name}#{p.discriminator}:{p.id}" for p in matches])
            await ctx.send(f"```msg```")
        else:
            embed = discord.Embed(
                color=discord.Color.blue(),
                title="Members with Intersecting Roles",
            )
            embed.add_field(
                name="Name",
                value="\n".join([f"{p.display_name}" for p in matches]),
                inline=True,
            )
            embed.add_field(
                name="Discord",
                value="\n".join([f"{p.name}#{p.discriminator}" for p in matches]),
                inline=True,
            )
            embed.add_field(
                name="ID", value="\n".join(str(p.id) for p in matches), inline=True
            )
            embed.set_footer(text=f"Found {len(matches)} user(s) in total.")

            await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def removeRoleFromAll(self, ctx, role: discord.Role) -> None:
        """Removes the role from every member who has it in the server"""
        empty = True
        # Check if role has no members.
        if len(role.members) == 0:
            noUsersEmbed = discord.Embed(
                title="Results",
                description=f"Nobody has the **{role.name}** role.",
                color=discord.Color.orange(),
            )
            noUsersEmbed.set_footer(text="0 user(s) had role removed.")
            await ctx.send(embed=noUsersEmbed)
            return

        # Essentially a "loading" embed. Adding role to everyone takes time.
        working_embed = discord.Embed(
            title="Working",
            description="Removing role from all users. This can take a bit...",
            color=discord.Color.yellow(),
        )
        msg = await ctx.reply(embed=working_embed)

        # Create embed before role is altered.
        removedEmbed = discord.Embed(
            title="Role Removed",
            description=f"Removed {role.name} from everyone in the server.",
            color=discord.Color.blue(),
        )
        removedEmbed.set_footer(text=f"{len(role.members)} user(s) had role removed.")

        # Remove role from all members.
        for member in role.members:
            await member.remove_roles(role)

        await msg.edit(embed=removedEmbed)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def addRoleToEveryone(self, ctx, role: discord.Role):
        """Add a role to everyone in the server."""
        added = 0
        had = 0
        failed = 0

        # Essentially a "loading" embed. Adding role to everyone takes time.
        working_embed = discord.Embed(
            title="Working",
            description="Adding role to all users. This can take a bit...",
            color=discord.Color.yellow(),
        )
        msg = await ctx.reply(embed=working_embed)

        # Loop through all members of guild and add role.
        for member in ctx.guild.members:
            try:
                if role in member.roles:
                    had += 1
                else:
                    await member.add_roles(role)
                    added += 1
            except Exception as exc:
                log.error(
                    f"Failed to add {role.name} to {member.id}: {type(exc)} {exc}"
                )
                failed += 1

        # Edit "loading" message in place with result.
        role_embed = discord.Embed(
            title="Role Added",
            description=f"Added {role.name} to everyone in {ctx.guild.name}",
            color=discord.Color.blue(),
        )
        role_embed.set_footer(
            text=f"{(added + had)}/{len(ctx.guild.members)} users had role applied. {failed} failure(s)."
        )
        await msg.edit(embed=role_embed)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def addRole(self, ctx, role: discord.Role, *userList):
        """Adds the role to every member that can be found from the userList"""
        empty = True
        added = 0
        had = 0
        failed = 0
        not_found_list = []
        unknown_error_list = []

        # Essentially a "loading" embed. Adding role to everyone takes time.
        working_embed = discord.Embed(
            title="Working",
            description="Adding role to users. This can take a bit...",
            color=discord.Color.yellow(),
        )
        msg = await ctx.send(embed=working_embed)

        for user in userList:
            try:
                member = await commands.MemberConverter().convert(ctx, user)
                if member in ctx.guild.members:
                    if role not in member.roles:
                        await member.add_roles(role)
                        added += 1
                    else:
                        had += 1
                    empty = False
            except discord.ext.commands.errors.MemberNotFound:
                not_found_list.append(user)
                failed += 1
            except Exception as exc:
                log.error(
                    f"Failed to add {role.name} to {member.id}: {type(exc)} {exc}"
                )
                unknown_error_list.append(user)
                failed += 1

        # Update embed in place
        role_embed = discord.Embed(
            title="Role Added",
            description=f"Added {role.name} to specified user(s).",
            color=discord.Color.blue(),
        )
        if len(not_found_list) > 0:
            role_embed.add_field(
                name="Not Found", value="\n".join(not_found_list), inline=True
            )
        if len(unknown_error_list) > 0:
            role_embed.add_field(
                name="Error", value="\n".join(unknown_error_list), inline=True
            )
        role_embed.set_footer(
            text=f"{(added + had)}/{len(ctx.guild.members)} users had role applied. {failed} failure(s)."
        )
        await msg.edit(embed=role_embed)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def removeRole(self, ctx, role: discord.Role, *userList):
        """Removes the role from every member that can be found from the userList"""
        empty = True
        removed = 0
        notHave = 0
        notFound = 0
        message = ""
        for user in userList:
            try:
                member = await commands.MemberConverter().convert(ctx, user)
                if member in ctx.guild.members:
                    if role in member.roles:
                        await member.remove_roles(role)
                        removed += 1
                    else:
                        notHave += 1
                    empty = False
            except:
                if notFound == 0:
                    message += "Couldn't find:\n"
                message += f"{user}\n"
                notFound += 1
        if empty:
            message += f":x: Nobody had the {role.name} role removed"
        else:
            message += f":white_check_mark: {role.name} role removed from everyone that was found from list"
        if notFound > 0:
            message += f". {notFound} user(s) were not found"
        if notHave > 0:
            message += f". {notHave} user(s) didn't have the role"
        if removed > 0:
            message += f". {removed} user(s) had the role removed"
        await ctx.send(message)

    @commands.command()
    @commands.guild_only()
    async def getId(self, ctx, *userList):
        """Gets the id for any user that can be found from the userList"""
        found = []
        notFound = []
        for user in userList:
            try:
                member = await commands.MemberConverter().convert(ctx, user)
                if member in ctx.guild.members:
                    nickname = self.get_player_nickname(member)
                    found.append(
                        f"{nickname}:{member.name}#{member.discriminator}:{member.id}\n"
                    )
            except:
                notFound.append(user)
                found.append(None)

        # Double Check not found (search by nickname without prefix):
        for player in ctx.guild.members:
            player_nick = self.get_player_nickname(player)
            if player_nick in notFound:
                while player_nick in notFound:
                    notFound.remove(player_nick)
                match_indicies = [i for i, x in enumerate(userList) if x == player_nick]
                for match in match_indicies:
                    found[
                        match
                    ] = f"{player_nick}:{player.name}#{player.discriminator}:{player.id}\n"

        if notFound:
            notFoundMessage = ":x: Couldn't find:\n"
            for user in notFound:
                notFoundMessage += f"{user}\n"
            await ctx.send(notFoundMessage)

        messages = []
        if found:
            message = ""
            for member_line in found:
                if member_line and len(message + member_line) < 2000:
                    message += member_line
                else:
                    messages.append(message)
                    message = member_line
            messages.append(message)
        for msg in messages:
            if msg:
                await ctx.send(f"```{msg}```")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def giveRoleToAllWithRole(
        self, ctx, currentRole: discord.Role, roleToGive: discord.Role
    ):
        """Gives the roleToGive to every member who already has the currentRole"""
        count = 0
        hadRoleCount = 0
        countGiven = 0

        for member in currentRole.members:
            count += 1
            if roleToGive in member.roles:
                hadRoleCount += 1
            else:
                await member.add_roles(roleToGive)
                countGiven += 1
        if count == 0:
            message = f":x: Nobody has the {currentRole.name} role"
        else:
            message = (
                f":white_check_mark: {count} user(s) had the {currentRole.name} role"
            )
            if hadRoleCount > 0:
                message += (
                    f". {hadRoleCount} user(s) already had the {roleToGive.name} role"
                )
            if countGiven > 0:
                message += f". {countGiven} user(s) had the {roleToGive.name} role added to them"
        await ctx.send(message)

    # endregion

    # region general admin use
    @commands.command(aliases=["addMissingServerRoles"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def addRequiredServerRoles(self, ctx):
        """Adds any missing roles required for the bulkRoleManager cog to function properly."""
        required_roles = ["Draft Eligible", "League", "Spectator", "Former Player"]
        for role in ctx.guild.roles:
            if role.name in required_roles:
                required_roles.remove(role.name)

        if not required_roles:
            await ctx.send(
                embed=discord.Embed(
                    title="Required Roles",
                    description="No additional roles required.",
                    color=discord.Color.blue(),
                )
            )
        else:
            for role_name in required_roles:
                await ctx.guild.create_role(name=role_name)
            added_roles = "\n".join([f"- {r}" for r in required_roles])
            await ctx.send(
                embed=discord.Embed(
                    title="Required Roles",
                    description=f"The following roles have been added.\n\n{added_roles}",
                    color=discord.Color.green(),
                )
            )

    @commands.command()
    @commands.guild_only()
    async def getIdsWithRole(self, ctx, role: discord.Role, spreadsheet: bool = False):
        """Gets the id for any user that has the given role"""
        messages = []
        message = ""
        if spreadsheet:
            Outputcsv = "./tmp/Ids.csv"
            header = ["Nickname", "Name", "Id"]
            csvwrite = open(Outputcsv, "w", newline="", encoding="utf-8")
            w = csv.writer(csvwrite, delimiter=",")
            w.writerow(header)
            for member in role.members:
                nickname = self.get_player_nickname(member)
                newrow = [
                    f"{nickname}",
                    f"{member.name}#{member.discriminator}",
                    f"{member.id}",
                ]
                w.writerow(newrow)
            csvwrite.close()
            await ctx.send("Done", file=File(Outputcsv))
            os.remove(Outputcsv)
        else:
            for member in role.members:
                nickname = self.get_player_nickname(member)
                message += (
                    f"{nickname}:{member.name}#{member.discriminator}:{member.id}\n"
                )
                if len(message) > 1900:
                    messages.append(message)
                    message = ""
            if message:
                messages.append(message)
            for msg in messages:
                await ctx.send(f"```{msg}```")

    # endregion

    # region Message Configuration

    @commands.guild_only()
    @commands.group(name="bulkrolemanager", aliases=["brm"])
    @checks.admin_or_permissions(manage_guild=True)
    async def _bulk_role_manager(self, ctx: commands.Context) -> NoReturn:
        """Display or configure bulk role manager cog settings"""
        pass

    @_bulk_role_manager.command(name="settings", aliases=["info"])
    async def _show_brm_settings(self, ctx: commands.Context):
        """Display current settings"""
        de_msg = await self._draft_eligible_message(ctx.guild) or "None"
        permfa_msg = await self._perm_fa_message(ctx.guild) or "None"
        settings_embed = discord.Embed(
            title="Bulk Role Manager Settings",
            description="Current configuration for BulkRoleManager Cog.",
            color=discord.Color.blue(),
        )
        # Discord embed field max length is 1024. Determine if multiple embeds are needed.
        if len(de_msg) <= 1024 and len(permfa_msg) <= 1024:
            settings_embed.add_field(name="DE Message", value=de_msg, inline=False)
            settings_embed.add_field(
                name="PermFA Message", value=permfa_msg, inline=False
            )
            await ctx.send(embed=settings_embed)
        else:
            settings_embed.set_footer(text="Bulk Role Manager Settings")
            settings_embed.title = "DE Message"
            settings_embed.description = de_msg
            await ctx.send(embed=settings_embed)

            settings_embed.title = "PermFA Message"
            settings_embed.description = permfa_msg
            await ctx.send(embed=settings_embed)

    @_bulk_role_manager.command(name="de")
    async def _set_de_msg(self, ctx: commands.Context, *, message: str):
        """Set Draft Eligible message (4096 charactere max)"""
        if len(message) > 4096:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"DE message must be a maximum of 4096 characters. (Length: {len(message)})"
                )
            )
            return

        await self._save_draft_eligible_message(ctx.guild, message)
        de_embed = discord.Embed(
            title="Draft Eligible Message",
            description=message,
            color=discord.Color.green(),
        )
        de_embed.set_footer(text="Successfully configured DE message.")
        await ctx.send(embed=de_embed)

    @_bulk_role_manager.command(name="permfa")
    async def _set_permfa_msg(self, ctx: commands.Context, *, message: str):
        """Set PermFA message (4096 character max)"""
        if len(message) > 4096:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"PermFA message must be a maximum of 4096 characters. (Length: {len(message)})"
                )
            )
            return

        await self._save_perm_fa_message(ctx.guild, message)
        permfa_embed = discord.Embed(
            title="PermFA Message", description=message, color=discord.Color.green()
        )
        permfa_embed.set_footer(text="Successfully configured PermFA message.")
        await ctx.send(embed=permfa_embed)

    @_bulk_role_manager.group(name="unset")
    async def _brm_unset(self, ctx: commands.Context):
        """Command group for removing configuration options"""

    @_brm_unset.command(name="de")
    async def _unset_de_msg(self, ctx: commands.Context):
        """Clear Draft Eligible message"""
        await self._save_draft_eligible_message(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Removed",
                description="Draft Eligible message has been unset.",
                color=discord.Color.orange(),
            )
        )

    @_brm_unset.command(name="permfa")
    async def _unset_permfa_msg(self, ctx: commands.Context):
        """Clear PermFA message"""
        await self._save_perm_fa_message(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Removed",
                description="PermFA message has been unset.",
                color=discord.Color.orange(),
            )
        )

    # endregion

    # region league related
    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def makeDE(self, ctx, *userList):
        """Adds the Draft Eligible and League roles, removes Spectator role, and adds the DE prefix to every member that can be found from the userList"""
        empty = True
        added = 0
        had = 0
        notFound = 0
        deRole = None
        leagueRole = None
        spectatorRole = None
        formerPlayerRole = None
        message = ""
        for role in ctx.guild.roles:
            if role.name == "Draft Eligible":
                deRole = role
            elif role.name == "League":
                leagueRole = role
            elif role.name == "Spectator":
                spectatorRole = role
            elif role.name == "Former Player":
                formerPlayerRole = role
            if leagueRole and deRole and spectatorRole and formerPlayerRole:
                break

        # Validate guild roles exist
        if (
            deRole is None
            or leagueRole is None
            or spectatorRole is None
            or formerPlayerRole is None
        ):
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"Couldn't find either the **Draft Eligible**, **League**, **Spectator**, or **Former Player** role in the server.\n\nUse `{ctx.prefix}addRequiredServerRoles` to add these roles."
                )
            )
            return

        for user in userList:
            try:
                # Convert to `discord.Member`
                member = await commands.MemberConverter().convert(ctx, user)
            except:
                message += f"Couldn't find: {user}\n"
                notFound += 1
                continue
            if member in ctx.guild.members:
                if leagueRole in member.roles:
                    msg = await ctx.send(
                        f"{member.mention} already has the league role, are you sure you want to make him a DE?"
                    )
                    start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

                    pred = ReactionPredicate.yes_or_no(msg, ctx.author)
                    await ctx.bot.wait_for("reaction_add", check=pred)
                    if pred.result is False:
                        await ctx.send(f"{member.name} not made DE.")
                        had += 1
                        continue
                    else:
                        await ctx.send(
                            f"You will need to manually remove any team or free agent roles if {member.mention} has any."
                        )

                await member.add_roles(deRole, leagueRole)
                added += 1
                await member.edit(nick=f"DE | {self.get_player_nickname(member)}")
                await member.remove_roles(spectatorRole, formerPlayerRole)
                deMessage = await self._draft_eligible_message(ctx.guild)
                if deMessage:
                    await self._send_member_message(ctx, member, deMessage)

                empty = False

        if empty:
            message += ":x: Nobody was given the Draft Eligible role"
        else:
            message += ":white_check_mark: Draft Eligible role given to everyone that was found from list"
        if notFound > 0:
            message += f". {notFound} user(s) were not found"
        if had > 0:
            message += (
                f". {had} user(s) already had the role or were already in the league"
            )
        if added > 0:
            message += f". {added} user(s) had the role added to them"
        await ctx.send(message)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def makePermFA(self, ctx, tier: str, *userList):
        """Makes each member that can be found from the userList a permanent Free Agent for the given tier"""
        role_names_to_add = [
            self.PERM_FA_ROLE,
            self.DEV_LEAGUE_ROLE,
            "League",
            tier,
            f"{tier}FA",
        ]
        roles_to_add = []
        tiers = await self.team_manager_cog.tiers(ctx)
        for role in ctx.guild.roles:
            if role.name in role_names_to_add:
                roles_to_add.append(role)
                role_names_to_add.remove(role.name)
                if role.name == "League":
                    leagueRole = role

        if role_names_to_add:
            missing_roles = "\n".join([f"- {r}" for r in role_names_to_add])
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"The following roles could not be found.\n\n{missing_roles}"
                )
            )
            return False

        empty = True
        notFound = 0
        had = 0
        added = 0
        message = ""
        for user in userList:
            try:
                member = await commands.MemberConverter().convert(ctx, user)
            except:
                message += f"Couldn't find: {user}\n"
                notFound += 1
                continue
            if member in ctx.guild.members:
                empty = False
                tier_changed = True
                old_tier_role = None
                if leagueRole in member.roles:
                    old_tier_role = await self.team_manager_cog.get_current_tier_role(
                        ctx, member
                    )
                    if old_tier_role in member.roles and old_tier_role in roles_to_add:
                        tier_changed = False
                        had += 1
                        added -= 1  # remove double count of had/added

                if tier_changed:
                    action = "assigned"
                    if old_tier_role and old_tier_role not in roles_to_add:
                        old_tier_fa_role = self.team_manager_cog._find_role_by_name(
                            ctx, f"{old_tier_role.name}FA"
                        )
                        rm_roles = [old_tier_role, old_tier_fa_role]
                        await member.remove_roles(*rm_roles)
                        action = "promoted"
                    tier_change_msg = f"Congrats! Due to your recent ranks you've been {action} to our {tier} tier! You'll only be allowed to play in that tier or any tier above it for the remainder of this season. If you have any questions please let an admin know. \n\nIf you checked in already for the next match day, please use the commands `[p]co` to check out and then `[p]ci` to check in again for your new tier."
                    await self._send_member_message(ctx, member, tier_change_msg)

                if self.get_player_nickname(member)[:5] != "FA | ":
                    try:
                        await member.edit(
                            nick=f"FA | {self.get_player_nickname(member)}"
                        )
                    except (discord.errors.Forbidden, discord.errors.HTTPException):
                        await ctx.send(f"Cannot set nickname for {member.name}")

                await member.add_roles(*roles_to_add)
                # permFAMessage = await self._perm_fa_message(ctx)
                # if permFAMessage:
                #     await self._send_member_message(ctx, member, permFAMessage)
                added += 1

        if len([userList]) and not empty:
            message = f"{len([userList])} members processed...\n{message}"
        if empty:
            message += f":x: Nobody was set as a {tier} permanent FA"
        else:
            message += (
                f":white_check_mark: All members found are now {tier} permanent FAs."
            )
        if notFound:
            message += f". {notFound} user(s) were not found"
        if had:
            message += f". {had} user(s) were already in this tier."
        if added:
            message += f". {added} user(s) had the role added to them"
        await ctx.send(message)

    @commands.command(aliases=["retirePlayer", "retirePlayers", "setFormerPlayer"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def retire(self, ctx, *userList):
        """Removes league roles and adds 'Former Player' role for every member that can be found from the userList"""
        empty = True
        retired = 0
        notFound = 0
        message = ""
        former_player_str = "Former Player"
        former_player_role = self.team_manager_cog._find_role_by_name(
            ctx, former_player_str
        )

        if not former_player_role:
            former_player_role = await self.team_manager_cog.create_role(
                ctx, former_player_str
            )

        roles_to_remove = [
            self.team_manager_cog._find_role_by_name(ctx, "Draft Eligible"),
            self.team_manager_cog._find_role_by_name(ctx, "League"),
            self.team_manager_cog._find_role_by_name(ctx, "Free Agent"),
            self.team_manager_cog._find_role_by_name(ctx, self.PERM_FA_ROLE),
        ]
        # remove dev league interest role if it exists in the server
        dev_league_role = self.team_manager_cog._find_role_by_name(
            ctx, self.PERM_FA_ROLE
        )
        if dev_league_role:
            roles_to_remove.append(dev_league_role)

        tiers = await self.team_manager_cog.tiers(ctx)
        for tier in tiers:
            tier_role = self.team_manager_cog._get_tier_role(ctx, tier)
            if tier_role:
                tier_fa_role = self.team_manager_cog._find_role_by_name(
                    ctx, f"{tier}FA"
                )
            roles_to_remove.append(tier_role)
            roles_to_remove.append(tier_fa_role)

        for user in userList:
            try:
                member = await commands.MemberConverter().convert(ctx, user)
                if member in ctx.guild.members:
                    roles_to_remove.append(
                        self.team_manager_cog.get_current_franchise_role(member)
                    )
                    removable_roles = []
                    for role in roles_to_remove:
                        if role in member.roles:
                            removable_roles.append(role)
                    await member.remove_roles(*removable_roles)
                    await member.add_roles(former_player_role)
                    await member.edit(
                        nick=(self.team_manager_cog.get_player_nickname(member))
                    )
                    empty = False
            except:
                if notFound == 0:
                    message += "Couldn't find:\n"
                message += f"{user}\n"
                notFound += 1
        if empty:
            message += ":x: Nobody was set as a former player."
        else:
            message += ":white_check_mark: everyone that was found from list is now a former player"
        if notFound > 0:
            message += f". {notFound} user(s) were not found"
        if retired > 0:
            message += f". {retired} user(s) have been set as former players."
        await ctx.send(message)

    @commands.command(aliases=["updateTierForPlayers"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def updateTier(self, ctx, tier: discord.Role, *userList):
        """Re-assigns every guild member to the provided tier"""
        await ctx.send(
            f"Processing tier update for {len(userList)} users. This may take some time."
        )
        asyncio.create_task(self.update_tiers(ctx, tier, userList))

    # endregion

    # region Helper Functions
    async def update_tiers(self, ctx, tier_assignment, userList):
        empty = True
        updated = 0
        notFound = 0
        message = ""
        league_role = self.team_manager_cog._find_role_by_name(ctx, "League")
        fa_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")

        # get role groups
        roles_to_remove = []
        tiers = await self.team_manager_cog.tiers(ctx)
        tier_roles = [self.team_manager_cog._get_tier_role(ctx, tier) for tier in tiers]
        tiers_fa_roles = [
            self.team_manager_cog._find_role_by_name(ctx, f"{tier}FA") for tier in tiers
        ]

        # validate tier
        if tier_assignment not in tier_roles:
            return await ctx.send(f":x: {tier_assignment} is not a valid tier.")

        tier_assign_fa_role = self.team_manager_cog._find_role_by_name(
            ctx, tier_assignment.name + "FA"
        )

        # Prep roles to remove
        roles_to_remove = tier_roles + tiers_fa_roles
        roles_to_remove.remove(tier_assignment)
        roles_to_remove.remove(tier_assign_fa_role)

        for user in userList:
            try:
                member = await commands.MemberConverter().convert(ctx, user)

                # For each user in guild
                if member in ctx.guild.members:
                    # prep roles to remove
                    removable_roles = []
                    for role in roles_to_remove:
                        if role in member.roles:
                            removable_roles.append(role)

                    # prep roles to add
                    add_roles = [tier_assignment]
                    if fa_role in member.roles:
                        add_roles.append(tier_assign_fa_role)

                    # performs role updates
                    await member.remove_roles(*removable_roles)
                    await member.add_roles(*add_roles)

                    empty = False
            except Exception as e:
                await ctx.send(f"Error: {e}")
                if notFound == 0:
                    message += "Couldn't find:\n"
                message += f"{user}\n"
                notFound += 1
        if empty:
            message += (
                f":x: Nobody was assigned to the **{tier_assignment.name}** tier."
            )
        else:
            message += f":white_check_mark: everyone that was found from list is now registered to the **{tier_assignment.name}** tier."
        if notFound > 0:
            message += f". {notFound} user(s) were not found"
        if updated > 0:
            message += f". {updated} user(s) have been assigned to the **{tier_assignment.name}** tier."
        await ctx.send(message)

    def get_player_nickname(self, user: discord.Member):
        if user.nick:
            array = user.nick.split(" | ", 1)
            if len(array) == 2:
                currentNickname = array[1].strip()
            else:
                currentNickname = array[0]
            return currentNickname

        if user.global_name:
            return user.global_name

        return user.name

    async def _draft_eligible_message(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).DraftEligibleMessage()

    async def _save_draft_eligible_message(self, guild: discord.Guild, message: str):
        await self.config.guild(guild).DraftEligibleMessage.set(message)

    async def _perm_fa_message(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).PermFAMessage()

    async def _save_perm_fa_message(self, guild: discord.Guild, message: str):
        await self.config.guild(guild).PermFAMessage.set(message)

    async def _send_member_message(self, ctx, member, message):
        message_title = f"**Message from {ctx.guild.name}:**\n\n"
        command_prefix = ctx.prefix
        message = message.replace("[p]", command_prefix)
        message = message.replace("{p}", command_prefix)
        message = message_title + message
        await self.dm_helper_cog.add_to_dm_queue(member, content=message)

    def _get_name_components(self, member: discord.Member):
        if member.nick:
            name = member.nick
        else:
            return "", member.name, ""
        prefix = name[0 : name.index(" | ")] if " | " in name else ""
        if prefix:
            name = name[name.index(" | ") + 3 :]
        player_name = ""
        awards = ""
        for char in name[::-1]:
            if char not in LEAGUE_AWARDS:
                break
            awards = char + awards

        player_name = name.replace(" " + awards, "") if awards else name

        return prefix.strip(), player_name.strip(), awards.strip()

    def _generate_new_name(self, prefix, name, awards):
        new_name = f"{prefix} | {name}" if prefix else name
        if awards:
            awards = "".join(sorted(awards))
            new_name += f" {awards}"
        return new_name


# endregion
