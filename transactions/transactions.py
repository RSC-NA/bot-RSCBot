import discord
import logging
import datetime
import re

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

from .transStringTemplates import TransactionsStringsTemplates as stringTemplates
from teamManager import TeamManager
from prefixManager import PrefixManager
from dmHelper import DMHelper

from transactions.embeds import ErrorEmbed

from typing import NoReturn, Optional, Tuple, Union, List

log = logging.getLogger("red.RSCBot.transactions")

defaults = {
    "ContractExpirationMessage": stringTemplates.contract_expiration_msg,
    "CutMessage": None,
    "FANotifications": False,
    "TransChannel": None,
    "TransLogChannel": None,
    "TransNotifications": False,
    "TransRole": None,
}


class Transactions(commands.Cog):
    """Used to set franchise and role prefixes and give to members in those franchises or with those roles"""

    LEAGUE_ROLE = "League"
    PERM_FA_ROLE = "PermFA"
    SUBBED_OUT_ROLE = "Subbed Out"
    DEV_LEAGUE_ROLE = "Dev League Interest"
    TROPHY_EMOJI = "\U0001F3C6"  # :trophy:
    GOLD_MEDAL_EMOJI = "\U0001F3C5"  # gold medal
    FIRST_PLACE_EMOJI = "\U0001F947"  # first place medal
    STAR_EMOJI = "\U00002B50"  # :star:
    LEAGUE_AWARDS = [TROPHY_EMOJI, GOLD_MEDAL_EMOJI, FIRST_PLACE_EMOJI, STAR_EMOJI]

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567895, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.prefix_cog: PrefixManager = bot.get_cog("PrefixManager")
        self.team_manager_cog: TeamManager = bot.get_cog("TeamManager")
        self.dm_helper_cog: DMHelper = bot.get_cog("DMHelper")

    # region commands
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def genericAnnounce(self, ctx, *, message):
        """Posts the message to the transaction log channel"""
        try:
            trans_channel = await self._trans_channel(ctx.guild)
            await trans_channel.send(message)
            await ctx.send("Done")
        except KeyError:
            await ctx.send(":x: Transaction log channel not set")

    @commands.command(aliases=["makeFA"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def expireContracts(self, ctx: commands.Context, *userList):
        """Displays each member that can be found from the userList a Free Agent in their respective tier"""
        empty = True
        fa_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")
        league_role = self.team_manager_cog._find_role_by_name(ctx, "League")

        roles_to_remove = [
            self.team_manager_cog._find_role_by_name(ctx, "Draft Eligible"),
            self.team_manager_cog._find_role_by_name(ctx, self.PERM_FA_ROLE),
            self.team_manager_cog._find_role_by_name(ctx, "Former Player"),
        ]

        trans_channel: discord.TextChannel = await self._trans_channel(ctx.guild)

        message = discord.Embed(
            title="Expire Contract Results", colour=discord.Colour.blue()
        )

        not_found_list = []
        no_franchise_list = []

        for user in userList:
            try:
                member: discord.Member = await commands.MemberConverter().convert(
                    ctx, user
                )
            except Exception as e:
                log.debug(f"{user} not found... skipping.")
                not_found_list.append(user)
                continue

            # Process Contract expiration
            # For each user in guild
            if member in ctx.guild.members:
                # prep roles to remove
                franchise_role = self.team_manager_cog.get_current_franchise_role(
                    member
                )
                # Skip if player does not have a franchise role.
                if not franchise_role:
                    log.debug(f"{member} has no franchise role... skipping.")
                    no_franchise_list.append(member.display_name)
                    continue
                removable_roles = [franchise_role] if franchise_role else []
                for role in roles_to_remove:
                    if role in member.roles:
                        removable_roles.append(role)

                # prep roles to add
                tier_role = await self.team_manager_cog.get_current_tier_role(
                    ctx, member
                )

                if tier_role:
                    tier_fa_role: discord.Role = (
                        self.team_manager_cog._find_role_by_name(
                            ctx, tier_role.name + "FA"
                        )
                    )
                    add_roles = [league_role, fa_role, tier_fa_role]
                else:
                    add_roles = [league_role, fa_role]

                # get team/franchise info before role removal
                try:
                    teams = await self.team_manager_cog.teams_for_user(ctx, member)
                except Exception as exc:
                    log.error(f"Error fetching teams for {member}. {type(exc)} {exc}")
                    continue
                if len(teams) <= 0:
                    continue
                team = teams[0]
                # gm_name = await self.team_manager_cog._get_gm_name(franchise_role)
                # franchise_name = self.team_manager_cog.get_franchise_name_from_role(franchise_role)
                # gm: discord.Member = self.team_manager_cog._find_member_by_name(ctx, gm_name)
                gm: discord.Member = await self.team_manager_cog._get_gm(franchise_role)

                # performs role updates
                await member.remove_roles(*removable_roles)
                await member.add_roles(*add_roles)

                # Updates Name
                prefix, name, awards = self._get_name_components(member)
                new_name = self._generate_new_name("FA", name, awards)

                if member.nick != new_name:
                    try:
                        await member.edit(nick=new_name)
                    except:
                        pass

                transaction_msg = f"Contract with {member.mention} and {team} has expired ({gm.mention} - {tier_role.name})"

                await trans_channel.send(transaction_msg)
                # await self.send_player_expire_contract_message(ctx, member, franchise_role, team, gm)

                empty = False

        expireCount = len(userList) - len(not_found_list) - len(no_franchise_list)
        if not not_found_list:
            not_found_list.append("None")
        if not no_franchise_list:
            no_franchise_list.append("None")

        message.add_field(
            name="Users Not Found", value="\n".join(not_found_list), inline=True
        )
        message.add_field(
            name="No Franchise Role", value="\n".join(no_franchise_list), inline=True
        )

        if empty:
            message.description = "No users have been set as a free agent."
            message.colour = discord.Colour.red()
        else:
            message.description = "Successfully processed contracts."

        message.set_footer(
            text=f"{expireCount}/{len(userList)} users have been set as a free agent."
        )
        await ctx.send(embed=message)

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def draft(
        self,
        ctx,
        user: discord.Member,
        team_name: str,
        round: int = None,
        pick: int = None,
    ):
        """Assigns the franchise, tier, and league role to a user when they are drafted and posts to the assigned channel"""
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
            ctx, team_name
        )
        gm_name = await self._get_gm_name(franchise_role)
        if franchise_role in user.roles:
            message = "Round {0} Pick {1}: {2} was kept by {3} ({4} - {5})".format(
                round, pick, user.mention, team_name, gm_name, tier_role.name
            )
        else:
            message = "Round {0} Pick {1}: {2} was drafted by {3} ({4} - {5})".format(
                round, pick, user.mention, team_name, gm_name, tier_role.name
            )

        trans_channel = await self._trans_channel(ctx.guild)
        if trans_channel is not None:
            try:
                await self.add_player_to_team(ctx, user, team_name)
                free_agent_roles = await self.find_user_free_agent_roles(ctx, user)
                await trans_channel.send(message)
                draftEligibleRole = None
                for role in user.roles:
                    if role.name == "Draft Eligible":
                        draftEligibleRole = role
                        break
                if len(free_agent_roles) > 0:
                    for role in free_agent_roles:
                        await user.remove_roles(role)
                if draftEligibleRole is not None:
                    await user.remove_roles(draftEligibleRole)
                await ctx.send("Done")
            except KeyError:
                await ctx.send(":x: Free agent role not found in dictionary")
            except LookupError:
                await ctx.send(":x: Free agent role not found in server")
            return

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def sign(self, ctx, user: discord.Member, team_name: str) -> NoReturn:
        """Assigns the team role, franchise role and prefix to a user when they are signed and posts to the assigned channel"""
        try:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, team_name
            )
        except LookupError:
            errorEmbed = discord.Embed(
                title="Sign Error",
                description=f"No team found with name: **{team_name}**",
                colour=discord.Colour.red(),
            )
            await ctx.send(embed=errorEmbed)
            return

        if franchise_role in user.roles and tier_role in user.roles:
            errorEmbed = discord.Embed(
                title="Sign Error",
                description=f"{user.mention} is already on {team_name}",
                colour=discord.Colour.red(),
            )
            await ctx.send(embed=errorEmbed)
            return

        trans_channel = await self._trans_channel(ctx.guild)
        if trans_channel is not None:
            try:
                await self.add_player_to_team(ctx, user, team_name)
                free_agent_roles = await self.find_user_free_agent_roles(ctx, user)
                if len(free_agent_roles) > 0:
                    for role in free_agent_roles:
                        await user.remove_roles(role)
                gm_name = await self._get_gm_name(franchise_role)
                message = "{0} was signed by {1} ({2} - {3})".format(
                    user.mention, team_name, gm_name, tier_role.name
                )
                await trans_channel.send(message)
                await ctx.send("Done")
            except Exception as e:
                await ctx.send(e)

    @commands.guild_only()
    @commands.command(aliases=["re-sign", "rs"])
    @checks.admin_or_permissions(manage_roles=True)
    async def resign(self, ctx, user: discord.Member, team_name: str) -> None:
        """Re-signs a user to a given team, and if necessary, reapplys roles before posting to the assigned channel"""
        try:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, team_name
            )
        except LookupError:
            errorEmbed = discord.Embed(
                title="Re-sign Error",
                description=f"No team found with name: **{team_name}**",
                colour=discord.Colour.red(),
            )
            await ctx.send(embed=errorEmbed)
            return None

        trans_channel = await self._trans_channel(ctx.guild)
        gm_name = await self._get_gm_name(franchise_role)
        message = "{0} was re-signed by {1} ({2} - {3})".format(
            user.mention, team_name, gm_name, tier_role.name
        )

        if franchise_role not in user.roles or tier_role not in user.roles:
            try:
                await self.add_player_to_team(ctx, user, team_name)
                free_agent_roles = await self.find_user_free_agent_roles(ctx, user)
                if len(free_agent_roles) > 0:
                    for role in free_agent_roles:
                        await user.remove_roles(role)
            except Exception as e:
                await ctx.send(e)

        if trans_channel:
            await trans_channel.send(message)
            await ctx.send("Done")
        else:
            await ctx.send(
                "Unable to complete transaction as transaction channel is not set."
            )

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def cut(
        self,
        ctx,
        user: discord.Member,
        team_name: str,
        tier_fa_role: discord.Role = None,
    ) -> NoReturn:
        """Removes the team role and franchise role. Adds the free agent prefix and role to a user and posts to the assigned channel"""
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
            ctx, team_name
        )
        trans_channel = await self._trans_channel(ctx.guild)
        if not trans_channel:
            ctx.send(":x: Transaction channel is not configured.")
            return

        try:
            await self.remove_player_from_team(ctx, user, team_name)
            # Add FA role is user is not a GM.
            if not self.team_manager_cog.is_gm(user):
                if tier_fa_role is None:
                    role_name = "{0}FA".format(
                        (
                            await self.team_manager_cog.get_current_tier_role(ctx, user)
                        ).name
                    )
                    tier_fa_role = self.team_manager_cog._find_role_by_name(
                        ctx, role_name
                    )
                fa_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")

                # add the dev league role to this new FA so that they get pings!
                dev_league_role = self.team_manager_cog._find_role_by_name(
                    ctx, self.DEV_LEAGUE_ROLE
                )
                if dev_league_role is not None:
                    await user.add_roles(dev_league_role)

                await self.team_manager_cog._set_user_nickname_prefix(ctx, "FA", user)
                await user.add_roles(tier_fa_role, fa_role)
            gm_name = await self._get_gm_name(franchise_role)
            message = (
                f"{user.mention} was cut by {team_name} ({gm_name} - {tier_role.name})"
            )
            await trans_channel.send(message)

            franchise_name = self.team_manager_cog.get_franchise_name_from_role(
                franchise_role
            )
            cut_embed = await self.get_cut_embed(
                ctx, ctx.author, gm_name, franchise_name, team_name, tier_role.name
            )
            if cut_embed:
                await self.dm_helper_cog.add_to_dm_queue(user, embed=cut_embed)

            await ctx.send("Done")
        except KeyError:
            await ctx.send(":x: Free agent role not found in dictionary")
        except LookupError:
            await ctx.send(":x: Free agent role not found in server")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def trade(
        self,
        ctx,
        user: discord.Member,
        new_team_name: str,
        user_2: discord.Member,
        new_team_name_2: str,
    ):
        """Swaps the teams of the two players and announces the trade in the assigned channel"""
        franchise_role_1, tier_role_1 = await self.team_manager_cog._roles_for_team(
            ctx, new_team_name
        )
        franchise_role_2, tier_role_2 = await self.team_manager_cog._roles_for_team(
            ctx, new_team_name_2
        )
        gm_name_1 = await self._get_gm_name(franchise_role_1)
        gm_name_2 = await self._get_gm_name(franchise_role_2)
        if franchise_role_1 in user.roles and tier_role_1 in user.roles:
            await ctx.send(
                ":x: {0} is already on the {1}".format(user.mention, new_team_name)
            )
            return
        if franchise_role_2 in user_2.roles and tier_role_2 in user_2.roles:
            await ctx.send(
                ":x: {0} is already on the {1}".format(user_2.mention, new_team_name_2)
            )
            return

        trans_channel = await self._trans_channel(ctx.guild)
        if trans_channel is not None:
            await self.remove_player_from_team(ctx, user, new_team_name_2)
            await self.remove_player_from_team(ctx, user_2, new_team_name)
            await self.add_player_to_team(ctx, user, new_team_name)
            await self.add_player_to_team(ctx, user_2, new_team_name_2)
            message = (
                "{0} was traded by {1} ({4} - {5}) to {2} ({6} - {7}) for {3}".format(
                    user.mention,
                    new_team_name_2,
                    new_team_name,
                    user_2.mention,
                    gm_name_2,
                    tier_role_2.name,
                    gm_name_1,
                    tier_role_1.name,
                )
            )
            await trans_channel.send(message)
            await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def sub(
        self,
        ctx,
        user: discord.Member,
        team_name: str,
        subbed_out_user: discord.Member = None,
    ) -> NoReturn:
        """
        Adds the team roles to the user and posts to the assigned transaction channel

        This command is also used to end substitution periods"""
        trans_channel = await self._trans_channel(ctx.guild)
        free_agent_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")
        perm_fa_role = self.team_manager_cog._find_role_by_name(ctx, "permFA")
        # Check for transaction channel
        if not trans_channel:
            await ctx.send(
                embed=ErrorEmbed(
                    description="Transaction channel is not configured for this server."
                )
            )
            return

        # Check if "League" role exists
        leagueRole = self.team_manager_cog._find_role_by_name(ctx, self.LEAGUE_ROLE)
        if not leagueRole:
            await ctx.send(
                embed=ErrorEmbed(description="League role not found in this server.")
            )
            return

        franchise_role, team_tier_role = await self.team_manager_cog._roles_for_team(
            ctx, team_name
        )
        # End Substitution
        if franchise_role in user.roles and team_tier_role in user.roles:
            if list(set([free_agent_role, perm_fa_role]) & set(user.roles)):
                await user.remove_roles(franchise_role)
                team_tier_fa_role = self.team_manager_cog._find_role_by_name(
                    ctx, "{0}FA".format(team_tier_role)
                )
                if not team_tier_fa_role in user.roles:
                    player_tier = await self.get_tier_role_for_fa(ctx, user)
                    await user.remove_roles(team_tier_role)
                    await user.add_roles(player_tier)
            else:
                await user.remove_roles(team_tier_role)
            gm = await self._get_gm_name(franchise_role)
            message = f"{user.mention} has finished their time as a substitute for {team_name} ({gm} - {team_tier_role.name})"
            # Removed subbed out role from all team members on team
            subbed_out_role = self.team_manager_cog._find_role_by_name(
                ctx, self.SUBBED_OUT_ROLE
            )
            if subbed_out_role:
                team_members = await self.team_manager_cog.members_from_team(
                    franchise_role, team_tier_role
                )
                for team_member in team_members:
                    await team_member.remove_roles(subbed_out_role)
            # Reset player temp rating if the player rating cog is used
            player_ratings = self.bot.get_cog("PlayerRatings")
            if player_ratings:
                await player_ratings.reset_temp_rating(ctx, user)

        # Begin Substitution:
        else:
            if list(set([free_agent_role, perm_fa_role]) & set(user.roles)):
                player_tier = await self.get_tier_role_for_fa(ctx, user)
                await user.remove_roles(player_tier)
            await user.add_roles(franchise_role, team_tier_role, leagueRole)
            gm = await self._get_gm_name(franchise_role)
            if subbed_out_user:
                message = f"{user.mention} was signed to a temporary contract by {team_name}, subbing for {subbed_out_user.mention} ({gm} - {team_tier_role.name})"
            else:
                message = f"{user.mention} was signed to a temporary contract by {team_name} ({gm} - {team_tier_role.name})"
            # Give subbed out user the subbed out role if there is one
            subbed_out_role = self.team_manager_cog._find_role_by_name(
                ctx, self.SUBBED_OUT_ROLE
            )
            if subbed_out_user and subbed_out_role:
                await subbed_out_user.add_roles(subbed_out_role)
                player_ratings = self.bot.get_cog("PlayerRatings")
                if player_ratings:
                    await player_ratings.set_player_temp_rating(
                        ctx, user, subbed_out_user
                    )
            elif subbed_out_user:
                await ctx.send(
                    embed=ErrorEmbed(
                        description="The subbed out role is not configured in this server."
                    )
                )
        await trans_channel.send(message)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def promote(self, ctx, user: discord.Member, team_name: str):
        """Adds the team tier role to the user and posts to the assigned channel"""
        old_team_name = await self.team_manager_cog.get_current_team_name(ctx, user)
        if old_team_name is not None:
            if (await self.team_manager_cog._roles_for_team(ctx, old_team_name))[0] != (
                await self.team_manager_cog._roles_for_team(ctx, team_name)
            )[0]:
                await ctx.send(
                    ":x: {0} is not in the same franchise as {1}'s current team, the {2}".format(
                        team_name.name, user.name, old_team_name
                    )
                )
                return

            trans_channel = await self._trans_channel(ctx.guild)
            if trans_channel:
                await self.remove_player_from_team(ctx, user, old_team_name)
                await self.add_player_to_team(ctx, user, team_name)
                franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                    ctx, team_name
                )
                gm_name = await self._get_gm_name(franchise_role)
                message = "{0} was promoted to the {1} ({2} - {3})".format(
                    user.mention, team_name, gm_name, tier_role.name
                )
                await trans_channel.send(message)
                await ctx.send("Done")
        else:
            await ctx.send(
                "Either {0} isn't on a team right now or his current team can't be found".format(
                    user.name
                )
            )

    @commands.command(aliases=["lpwt"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def leaguePlayersWithoutTier(self, ctx: commands.Context):
        # Perform Search
        guild: discord.Guild = ctx.guild
        league_role: discord.Role = None
        for role in guild.roles:
            if role.name == self.LEAGUE_ROLE:
                league_role = role
                break
        if not league_role:
            return await ctx.send(":x: League role not found.")

        no_tier_league_players = []
        tier_roles_set = set(await self.team_manager_cog.tier_roles(ctx))
        for player in league_role.members:
            if not list(set(player.roles) & tier_roles_set):
                no_tier_league_players.append(player)

        # Create embed groups (avoid char limit)
        embed = discord.Embed(title="League Players Without Tiers")
        if not no_tier_league_players:
            embed.description = "All League Players have tier assignmentss"
            embed.color = discord.Color.green()
            return await ctx.send(embed=embed)

        name_char_count = len("player")
        mention_char_count = len("mention")
        active_embed_list = []
        complete_player_embed_lists = []

        while no_tier_league_players:
            player = no_tier_league_players.pop()
            player_name = player.display_name
            player_mention = f"\\<@{player.id}>"

            if (name_char_count + len(player_name) + 2 <= 1024) and (
                mention_char_count + len(player_mention) + 2 <= 1024
            ):
                active_embed_list.append(player)
                name_char_count += len(player_name) + 2
                mention_char_count += len(player_mention) + 2
            else:
                complete_player_embed_lists.append(active_embed_list)
                name_char_count = len("player") + len(player_name) + 2
                mention_char_count = len("mention") + len(player_mention) + 2
                active_embed_list = [player]

        # Build Embeds
        complete_player_embed_lists.append(active_embed_list)
        embeds = []
        for player_group in complete_player_embed_lists:
            embed = discord.Embed(
                title="League Players Without Tiers", color=discord.Color.red()
            )
            embed.add_field(
                name="Player",
                value="\n".join([f"{player.display_name}" for player in player_group]),
            )
            embed.add_field(
                name="Mention",
                value="\n".join([f"\\<@{player.id}>" for player in player_group]),
            )
            embeds.append(embed)

        # Send Embeds
        # await ctx.send(embeds=embeds)
        for embed in embeds:
            await ctx.send(embed=embed)

    # Listeners

    @commands.Cog.listener("on_member_remove")
    async def fa_server_leave(self, member: discord.Member):
        """Check if a rostered player has left the server and report to tranasction log channel"""
        guild = member.guild
        log.debug(f"Member left guild. Member: {member.display_name} Guild: {guild}")

        # Check if notifications are enabled
        if not await self._fa_notifications(member.guild):
            return

        # Return if transaction log channel is not configured
        try:
            log_channel = await self._trans_log_channel(guild)
            if not log_channel:
                log.warning("Transaction log channel is not configured.")
                return
        except:
            log.error("Error fetching transaction log channel.")
            return

        # Check if player was an FA
        free_agent = False
        for r in member.roles:
            if r.name.lower() == "permfa":
                free_agent = True
                break
            if r.name.lower() == "free agent":
                free_agent = True
                break

        if not free_agent:
            log.debug("Member was not a free agent.")
            return

        log.debug(
            f"{member.display_name} left the server while in free agency. Sending notification."
        )
        # Check if user was kicked from server
        perp, reason = await self.get_audit_log_reason(
            member.guild, member, discord.AuditLogAction.kick
        )

        log_embed = discord.Embed(
            description=f"Free agent has left the server.",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        log_embed.add_field(name="Member", value=member.mention, inline=True)
        log_embed.add_field(name="Member ID", value=str(member.id), inline=True)

        if perp:
            log_embed.add_field(name="Kicked", value=perp.mention, inline=True)
        if reason:
            log_embed.add_field(name="Reason", value=str(reason), inline=False)

        log_embed.set_author(
            name=f"{member} ({member.id}) has left the guild",
            url=member.display_avatar,
            icon_url=member.display_avatar,
        )
        log_embed.set_thumbnail(url=member.display_avatar)

        # Send to transaction log channel
        log.debug(f"Sending FA notice to transaction log channel.")
        await log_channel.send(embed=log_embed)

    @commands.Cog.listener("on_member_remove")
    async def rostered_server_leave(self, member: discord.Member):
        """Check if a rostered player has left the server and report to tranasction log channel"""
        log.debug(
            f"Member left guild. Member: {member.display_name} Guild: {member.guild} "
        )
        # Check if notifications are enabled
        if not await self._notifications_enabled(member.guild):
            return

        # Return if transaction log channel is not configured
        guild = member.guild
        try:
            log_channel = await self._trans_log_channel(guild)
            if not log_channel:
                log.warning("Transaction log channel is not configured.")
                return
        except:
            log.error("Error fetching transaction log channel.")
            return

        # Only log if the member is currently on a team
        team_manager: TeamManager = self.bot.get_cog("TeamManager")
        on_team = team_manager.get_current_franchise_role(member)
        if not on_team:
            log.debug(f"{member.display_name} left the server but was not on a team.")
            return

        log.debug(
            f"{member.display_name} left the server while rostered on {on_team}. Sending notification."
        )
        # Check if user was kicked from server
        perp, reason = await self.get_audit_log_reason(
            member.guild, member, discord.AuditLogAction.kick
        )

        log_embed = discord.Embed(
            description=f"Player left server while rostered on {on_team.mention}",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        log_embed.add_field(name="Member", value=member.mention, inline=True)
        log_embed.add_field(name="Member ID", value=str(member.id), inline=True)

        if perp:
            log_embed.add_field(name="Kicked", value=perp.mention, inline=True)
        if reason:
            log_embed.add_field(name="Reason", value=str(reason), inline=False)

        log_embed.set_author(
            name=f"{member} ({member.id}) has left the guild",
            url=member.display_avatar,
            icon_url=member.display_avatar,
        )
        log_embed.set_thumbnail(url=member.display_avatar)

        # Ping Transaction Committee if role is configured and send embed to log channel
        trans_role = await self._trans_role(guild)
        if trans_role and trans_role.mentionable:
            log.debug(f"Pinging {trans_role.name}")
            await log_channel.send(
                content=trans_role.mention,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

        await log_channel.send(embed=log_embed)

        # Ping GM and AGM in franchise transaction channel.
        franchise_name = on_team.name.split(" (")[0]
        trans_channel_name = f"{franchise_name.lower().replace(' ', '-')}-transactions"
        log.debug(f"Transaction Channel: {trans_channel_name}")
        trans_channel: discord.TextChannel = discord.utils.get(
            member.guild.channels, name=trans_channel_name
        )
        if trans_channel:
            # Find GM and mention them in their transaction channel
            gm: discord.Member = await self._get_franchise_gm(on_team.guild, on_team)
            if gm:
                await trans_channel.send(content=gm.mention)
            await trans_channel.send(embed=log_embed)
        else:
            log.error(
                f"Unable to find transaction channel. Role: {on_team.name} Channel: {trans_channel_name}"
            )
            log_channel.send(
                f"Unable to ping GM/AGM of {on_team.mention}. Missing or invalid transaction channel: **{trans_channel_name}**"
            )

    @commands.guild_only()
    @commands.command(aliases=["agm", "getAGM"])
    @checks.admin_or_permissions(manage_guild=True)
    async def findAGM(self, ctx: commands.Context, franchise_role: discord.Role):
        """Return the AGMs for a provided franchise role"""
        franchise_name = franchise_role.name.split(" (")
        if not franchise_name:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"Invalid franchise role: {franchise_role.mention}"
                )
            )
            return

        agms = await self._get_franchise_agms(ctx.guild, franchise_role)
        agm_embed = discord.Embed(
            title=f"{franchise_name[0]} AGM(s)", color=discord.Color.blue()
        )
        if agms:
            agm_embed.description = "\n".join([agm.mention for agm in agms])
            await ctx.send(embed=agm_embed)
        else:
            agm_embed.description = (
                f"There are currently no Assistant GM(s) in {franchise_role.mention}"
            )
            agm_embed.color = discord.Color.orange()
            await ctx.send(embed=agm_embed)

    @commands.guild_only()
    @commands.command(aliases=["gm", "getGM"])
    @checks.admin_or_permissions(manage_guild=True)
    async def findGM(self, ctx: commands.Context, franchise_role: discord.Role):
        """Return the GM for a provided franchise role"""
        franchise_name = franchise_role.name.split(" (")
        if not franchise_name:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"Invalid franchise role: {franchise_role.mention}"
                )
            )
            return

        gm = await self._get_franchise_gm(ctx.guild, franchise_role)
        gm_embed = discord.Embed(
            title=f"{franchise_name[0]} General Manager", color=discord.Color.blue()
        )
        if gm:
            gm_embed.description = gm.mention
            await ctx.send(embed=gm_embed)
        else:
            gm_embed.description = (
                f"Currently there is no General Manager for {franchise_role.mention}"
            )
            gm_embed.color = discord.Color.orange()
            await ctx.send(embed=gm_embed)

    async def _get_franchise_agms(
        self, guild: discord.Guild, franchise_role: discord.Role
    ) -> List[discord.Member]:
        """Return a list of AGMs in a franchise"""
        agm_role = discord.utils.get(guild.roles, name="Assistant GM")
        agms = []
        for member in franchise_role.members:
            if agm_role in member.roles:
                agms.append(member)
        return agms

    async def _get_franchise_gm(
        self, guild: discord.Guild, franchise_role: discord.Role
    ) -> Optional[discord.Member]:
        """Return GM from franchise role"""
        gm_role = discord.utils.get(guild.roles, name="General Manager")
        for member in franchise_role.members:
            if gm_role in member.roles:
                return member
        return None

    @commands.guild_only()
    @commands.command(aliases=["validateTransChan", "vts"])
    @checks.admin_or_permissions(manage_guild=True)
    async def validateTransactionChannels(self, ctx: commands.Context):
        """Validate all transaction channels exist and are properly formatted"""
        errors: List(Tuple(discord.Role, str)) = []
        for role in ctx.guild.roles:
            found = re.match(r"^\w.*?\x28.*?\x29$", role.name)
            if not found:
                continue

            franchise_name = role.name.split(" (")[0]
            trans_channel_name = (
                f"{franchise_name.lower().replace(' ', '-')}-transactions"
            )
            log.debug(f"Transaction Channel: {trans_channel_name}")
            trans_channel: discord.TextChannel = discord.utils.get(
                ctx.guild.channels, name=trans_channel_name
            )

            if not trans_channel:
                log.debug(
                    f"Unable to find transaction channel. Role: {role.name} Channel: {trans_channel_name}"
                )
                errors.append((role, trans_channel_name))

        if len(errors) > 0:
            field_data = list(zip(*errors))
            err_embed = discord.Embed(
                title="Missing Transaction Channls",
                description=f"Error finding **{len(errors)}** transaction channels.",
                color=discord.Color.red(),
            )
            role_data = "\n".join([r.mention for r in field_data[0]])
            channel_data = "\n".join(field_data[1])
            err_embed.add_field(name="Role", value=role_data, inline=True)
            err_embed.add_field(
                name="Transaction Channel", value=channel_data, inline=True
            )
            await ctx.send(embed=err_embed)
        else:
            await ctx.send(
                embed=discord.Embed(
                    title="Validation Results",
                    description="All transaction channels are properly configured.",
                    color=discord.Color.green(),
                )
            )

    async def get_audit_log_reason(
        self,
        guild: discord.Guild,
        target: Union[discord.abc.GuildChannel, discord.Member, discord.Role, int],
        action: discord.AuditLogAction,
    ) -> Tuple[Optional[discord.abc.User], Optional[str]]:
        """Retrieve audit log reason for `discord.AuditLogAction`"""
        perp = None
        reason = None
        if not isinstance(target, int):
            target_id = target.id
        else:
            target_id = target
        if guild.me.guild_permissions.view_audit_log:
            async for log in guild.audit_logs(limit=5, action=action):
                if not log.target:
                    continue
                if log.target.id == target_id:
                    perp = log.user
                    if log.reason:
                        reason = log.reason
                    break
        return perp, reason

    # Settings

    @commands.guild_only()
    @commands.group(name="transactions", aliases=["trans"])
    @checks.admin_or_permissions(manage_guild=True)
    async def _transactions(self, ctx: commands.Context) -> NoReturn:
        """Display or configure transaction cog settings"""
        pass

    @_transactions.command(name="settings")
    async def _show_transactions_settings(self, ctx: commands.Context):
        """Show transactions settings"""

        guild = ctx.guild
        if not guild:
            return

        log_channel = await self._trans_log_channel(guild)
        trans_channel = await self._trans_channel(guild)
        trans_role = await self._trans_role(guild)
        cut_msg = await self._get_cut_message(guild) or "None"
        notifications = await self._notifications_enabled(guild)
        fa_notifications = await self._fa_notifications(guild)

        settings_embed = discord.Embed(
            title="Transactions Settings",
            description="Current configuration for Transactions Cog.",
            color=discord.Color.blue(),
        )

        # Check channel values before mention to avoid exception
        settings_embed.add_field(
            name="Notifications Enabled", value=notifications, inline=False
        )

        settings_embed.add_field(
            name="Free Agent Notifications", value=fa_notifications, inline=False
        )

        if trans_channel:
            settings_embed.add_field(
                name="Transaction Channel", value=trans_channel.mention, inline=False
            )
        else:
            settings_embed.add_field(
                name="Transaction Channel", value="None", inline=False
            )

        if log_channel:
            settings_embed.add_field(
                name="Log Channel", value=log_channel.mention, inline=False
            )
        else:
            settings_embed.add_field(name="Log Channel", value="None", inline=False)

        if trans_role:
            settings_embed.add_field(
                name="Committee Role", value=trans_role.mention, inline=False
            )
        else:
            settings_embed.add_field(name="Committee Role", value="None", inline=False)

        # Discord embed field max length is 1024. Send a seperate embed for cut message if greater.
        if len(cut_msg) <= 1024:
            settings_embed.add_field(name="Cut Message", value=cut_msg, inline=False)
            await ctx.send(embed=settings_embed)
        else:
            await ctx.send(embed=settings_embed)
            cut_embed = discord.Embed(
                title="Cut Message", description=cut_msg, color=discord.Color.blue()
            )
            await ctx.send(embed=cut_embed)

    @_transactions.command(name="notifications")
    async def _toggle_notifications(self, ctx: commands.Context):
        """Toggle channel notifications on or off"""
        status = await self._notifications_enabled(ctx.guild)
        log.debug(f"Current Notifications: {status}")
        status ^= True  # Flip boolean with xor
        log.debug(f"Transaction Notifications: {status}")
        await self._set_notifications(ctx.guild, status)
        result = "**enabled**" if status else "**disabled**"
        await ctx.send(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction committee and GM notifications are now {result}.",
                color=discord.Color.green(),
            )
        )

    @_transactions.command(name="fanotify")
    async def _toggle_fa_notifications(self, ctx: commands.Context):
        """Toggle free agent notifications on or off"""
        guild = ctx.guild
        if not guild:
            return

        status = await self._fa_notifications(guild)
        log.debug(f"Current FA Notifications: {status}")
        status ^= True  # Flip boolean with xor
        log.debug(f"New FA Notifications: {status}")
        await self._set_fa_notifications(guild, status)
        result = "**enabled**" if status else "**disabled**"
        await ctx.send(
            embed=discord.Embed(
                title="Success",
                description=f"Free agent notifications are now {result}.",
                color=discord.Color.green(),
            )
        )

    @_transactions.command(name="channel")
    async def _set_transactions_channel(
        self, ctx: commands.Context, trans_channel: discord.TextChannel
    ):
        """Set transaction channel"""
        await self._save_trans_channel(ctx.guild, trans_channel.id)
        await ctx.send(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction channel configured to {trans_channel.mention}",
                color=discord.Color.green(),
            )
        )

    @_transactions.command(name="log")
    async def _set_transactions_logchannel(
        self, ctx: commands.Context, log_channel: discord.TextChannel
    ):
        """Set transactions log channel"""
        await self._save_trans_log_channel(ctx.guild, log_channel.id)
        await ctx.send(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction log channel configured to {log_channel.mention}",
                color=discord.Color.green(),
            )
        )

    @_transactions.command(name="role")
    async def _set_transactions_role(
        self, ctx: commands.Context, trans_role: discord.Role
    ):
        """Set transactions log channel"""
        await self._save_trans_role(ctx.guild, trans_role.id)
        await ctx.send(
            embed=discord.Embed(
                title="Success",
                description=f"Transaction committee role configured to {trans_role.mention}",
                color=discord.Color.green(),
            )
        )

    @_transactions.command(name="cutmsg")
    async def _set_cut_msg(self, ctx: commands.Context, *, msg: str):
        """Set cut message (4096 characters max)"""
        if len(msg) > 4096:
            await ctx.send(
                embed=ErrorEmbed(
                    description=f"Cut message must be a maximum of 4096 characters. (Length: {len(msg)})"
                )
            )
            return

        await self._save_cut_message(ctx.guild, msg)
        cut_embed = discord.Embed(
            title="Cut Message", description=f"{msg}", color=discord.Color.green()
        )
        cut_embed.set_footer(text="Successfully configured new cut message.")
        await ctx.send(embed=cut_embed)

    @_transactions.group(name="unset")
    async def _transactions_unset(self, ctx: commands.Context) -> NoReturn:
        """Command group for removing configuration options"""
        pass

    @_transactions_unset.command(name="channel")
    async def _unset_trans_channel(self, ctx: commands.Context):
        """Remove configured transaction channel."""
        await self._save_trans_channel(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Removed",
                description="Transaction channel has been unset.",
                color=discord.Color.orange(),
            )
        )

    @_transactions_unset.command(name="role")
    async def _unset_trans_role(self, ctx: commands.Context):
        """Remove configured transaction channel."""
        await self._save_trans_role(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Removed",
                description="Transaction committee role has been unset.",
                color=discord.Color.orange(),
            )
        )

    @_transactions_unset.command(name="log")
    async def _unset_trans_log_channel(self, ctx: commands.Context):
        """Remove configured log channel."""
        await self._save_trans_log_channel(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Removed",
                description="Transaction log channel has been unset.",
                color=discord.Color.orange(),
            )
        )

    @_transactions_unset.command(name="cutmsg")
    async def _unset_cut_msg(self, ctx: commands.Context):
        await self._save_cut_message(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Removed",
                description="Cut message has been unset.",
                color=discord.Color.orange(),
            )
        )

    # endregion

    # region helper functions
    async def get_cut_embed(
        self,
        ctx: commands.Context,
        player: discord.Member,
        gm_name,
        franchise_name,
        team_name,
        tier,
    ):
        cut_message = await self._get_cut_message(ctx.guild)
        if not cut_message:
            return None

        cut_message = cut_message.format(
            player=player,
            franchise=franchise_name,
            gm=gm_name,
            team=team_name,
            tier=tier,
            guild=ctx.guild.name,
        )
        embed = discord.Embed(
            title=f"Message from {ctx.guild.name}",
            description=cut_message,
            color=discord.Color.red(),
        )

        try:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        except:
            pass

        return embed

    async def add_player_to_team(self, ctx, user, team_name):
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
            ctx, team_name
        )
        leagueRole = self.team_manager_cog._find_role_by_name(ctx, "League")
        if leagueRole is not None:
            prefix = await self.prefix_cog._get_franchise_prefix(ctx, franchise_role)
            if prefix is not None:
                currentTier = await self.team_manager_cog.get_current_tier_role(
                    ctx, user
                )
                if currentTier is not None and currentTier != tier_role:
                    await user.remove_roles(currentTier)
                await self.team_manager_cog._set_user_nickname_prefix(ctx, prefix, user)
                await user.add_roles(tier_role, leagueRole, franchise_role)

    async def remove_player_from_team(self, ctx, user: discord.Member, team_name: str):
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
            ctx, team_name
        )
        if franchise_role not in user.roles or tier_role not in user.roles:
            errorEmbed = discord.Embed(
                title="Error",
                description=f"{user.mention} is not on {team_name}",
                colour=discord.Colour.red(),
            )
            await ctx.send(embed=errorEmbed)
            return

        if self.team_manager_cog.is_gm(user):
            # For GMs remove the tier role
            await user.remove_roles(tier_role)
        elif franchise_role is not None:
            # For regular players remove the franchise role
            await user.remove_roles(franchise_role)

    async def find_user_free_agent_roles(self, ctx, user):
        free_agent_roles = await self.get_free_agent_roles(ctx)
        if free_agent_roles:
            return list(set(user.roles) & set(free_agent_roles))
        return []

    async def get_free_agent_roles(self, ctx):
        free_agent_roles = []
        tiers = await self.team_manager_cog.tiers(ctx)
        for tier in tiers:
            role = self.team_manager_cog._find_role_by_name(ctx, "{0}FA".format(tier))
            if role is not None:
                free_agent_roles.append(role)
        free_agent_roles.append(
            self.team_manager_cog._find_role_by_name(ctx, "Free Agent")
        )
        return free_agent_roles

    def get_player_nickname(self, user: discord.Member):
        return self.team_manager_cog.get_player_nickname(user)

    async def set_user_nickname_prefix(self, ctx, prefix: str, user: discord.member):
        return self.team_manager_cog._set_user_nickname_prefix(ctx, prefix, user)

    async def get_tier_role_for_fa(self, ctx, user: discord.Member):
        fa_roles = await self.find_user_free_agent_roles(ctx, user)
        standard_fa_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")
        if standard_fa_role in fa_roles:
            fa_roles.remove(standard_fa_role)
        tier_role_name = fa_roles[0].name[:-2]
        tier_role = self.team_manager_cog._find_role_by_name(ctx, tier_role_name)
        return tier_role

    async def _get_gm_name(self, franchise_role, returnNameAsString=False):
        gm = await self.team_manager_cog._get_gm(franchise_role)
        if gm:
            if returnNameAsString:
                return gm.name
            else:
                return gm.mention
        else:
            return await self.team_manager_cog._get_gm_name(franchise_role)

    async def _send_member_message(self, ctx, member, message):
        if not message:
            return False
        message_title = "**Message from {0}:**\n\n".format(ctx.guild.name)
        command_prefix = ctx.prefix
        message = message.replace("[p]", command_prefix)
        message = message_title + message

        await self.dm_helper_cog.add_to_dm_queue(member, content=message, ctx=ctx)

    async def send_player_expire_contract_message(
        self,
        ctx: commands.Context,
        player: discord.Member,
        franchise_role: discord.Role,
        team: str,
        gm: discord.Member,
    ):
        franchise_name = self.team_manager_cog.get_franchise_name_from_role(
            franchise_role
        )
        msg = stringTemplates.contract_expiration_msg.format(
            p=ctx.prefix,
            player=player,
            team=team,
            franchise=franchise_name,
            gm=gm.display_name,
        )

        embed = discord.Embed(
            title=f"Notice from {ctx.guild.name}",
            description=msg,
            color=discord.Color.blue(),
        )
        if ctx.guild.icon.url:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        await self.dm_helper_cog.add_to_dm_queue(member=player, embed=embed, ctx=ctx)

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
            if char not in self.LEAGUE_AWARDS:
                break
            awards = char + awards

        player_name = name.replace(" " + awards, "") if awards else name

        return prefix.strip(), player_name.strip(), awards.strip()

    def _generate_new_name(self, prefix, name, awards):
        new_name = "{} | {}".format(prefix, name) if prefix else name
        if awards:
            awards = "".join(sorted(awards))
            new_name += " {}".format(awards)
        return new_name

    # endregion

    # region json db

    async def _trans_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        trans_role_id = await self.config.guild(guild).TransRole()
        return guild.get_role(trans_role_id)

    async def _save_trans_role(
        self, guild: discord.Guild, trans_role_id: Optional[int]
    ):
        await self.config.guild(guild).TransRole.set(trans_role_id)

    async def _trans_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        trans_channel_id = await self.config.guild(guild).TransChannel()
        return guild.get_channel(trans_channel_id)

    async def _save_trans_channel(
        self, guild: discord.Guild, trans_channel: Optional[int]
    ):
        await self.config.guild(guild).TransChannel.set(trans_channel)

    async def _trans_log_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        log_channel_id = await self.config.guild(guild).TransLogChannel()
        return guild.get_channel(log_channel_id)

    async def _save_trans_log_channel(
        self, guild: discord.Guild, trans_log_channel: Optional[int]
    ):
        await self.config.guild(guild).TransLogChannel.set(trans_log_channel)

    async def _get_cut_message(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).CutMessage()

    async def _save_cut_message(self, guild: discord.Guild, message):
        await self.config.guild(guild).CutMessage.set(message)

    async def _notifications_enabled(self, guild: discord.Guild) -> bool:
        return await self.config.guild(guild).TransNotifications()

    async def _set_notifications(self, guild: discord.Guild, enabled: bool):
        await self.config.guild(guild).TransNotifications.set(enabled)

    async def _fa_notifications(self, guild: discord.Guild) -> bool:
        return await self.config.guild(guild).FANotifications()

    async def _set_fa_notifications(self, guild: discord.Guild, enabled: bool):
        await self.config.guild(guild).FANotifications.set(enabled)




# endregion
