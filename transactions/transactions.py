import discord

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

from .transStringTemplates import TransactionsStringsTemplates as stringTemplates
from teamManager import TeamManager
from prefixManager import PrefixManager
from dmHelper import DMHelper

defaults = {
    "TransChannel": None,
    "CutMessage": None,
    "ContractExpirationMessage": stringTemplates.contract_expiration_msg
}


class Transactions(commands.Cog):
    """Used to set franchise and role prefixes and give to members in those franchises or with those roles"""

    LEAGUE_ROLE = "League"
    PERM_FA_ROLE = "PermFA"
    SUBBED_OUT_ROLE = "Subbed Out"
    TROPHY_EMOJI = "\U0001F3C6" # :trophy:
    GOLD_MEDAL_EMOJI = "\U0001F3C5" # gold medal
    FIRST_PLACE_EMOJI = "\U0001F947" # first place medal
    STAR_EMOJI = "\U00002B50" # :star:
    LEAGUE_AWARDS = [TROPHY_EMOJI, GOLD_MEDAL_EMOJI, FIRST_PLACE_EMOJI, STAR_EMOJI]

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567895, force_registration=True)
        self.config.register_guild(**defaults)
        self.prefix_cog : PrefixManager = bot.get_cog("PrefixManager")
        self.team_manager_cog : TeamManager = bot.get_cog("TeamManager")
        self.dm_helper_cog : DMHelper = bot.get_cog("DMHelper")

# region commands
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def genericAnnounce(self, ctx, *, message):
        """Posts the message to the transaction log channel"""
        try:
            trans_channel = await self._trans_channel(ctx)
            await trans_channel.send(message)
            await ctx.send("Done")
        except KeyError:
            await ctx.send(":x: Transaction log channel not set")

    @commands.command(aliases=['makeFA'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def expireContracts(self, ctx: commands.Context, *userList):
        """Displays each member that can be found from the userList a Free Agent in their respective tier"""
        empty = True
        free_agents = 0
        notFound = 0
        message = ""
        fa_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")
        league_role = self.team_manager_cog._find_role_by_name(ctx, "League")

        roles_to_remove = [
            self.team_manager_cog._find_role_by_name(ctx, "Draft Eligible"),
            self.team_manager_cog._find_role_by_name(ctx, self.PERM_FA_ROLE),
            self.team_manager_cog._find_role_by_name(ctx, "Former Player")
        ]

        trans_channel : discord.TextChannel = await self._trans_channel(ctx)

        for user in userList:
            try:
                member : discord.Member = await commands.MemberConverter().convert(ctx, user)
            except Exception as e:
                await ctx.send(f"Error: {e}")
                if notFound == 0:
                    message += "Couldn't find:\n"
                message += "{0}\n".format(user)
                notFound += 1
            
            # Process Contract expiration
            # For each user in guild
            if member in ctx.guild.members:

                # prep roles to remove
                franchise_role = self.team_manager_cog.get_current_franchise_role(member)
                removable_roles = [franchise_role] if franchise_role else []
                for role in roles_to_remove:
                    if role in member.roles:
                        removable_roles.append(role)
                
                # prep roles to add
                tier_role = await self.team_manager_cog.get_current_tier_role(ctx, member)

                if tier_role:
                    tier_fa_role: discord.Role = self.team_manager_cog._find_role_by_name(ctx, tier_role.name + "FA")
                    add_roles = [league_role, fa_role, tier_fa_role]
                else:
                    add_roles = [league_role, fa_role]

                # get team/franchise info before role removal
                team = (await self.team_manager_cog.teams_for_user(ctx, member))[0]
                # gm_name = self.team_manager_cog._get_gm_name(franchise_role)
                # franchise_name = self.team_manager_cog.get_franchise_name_from_role(franchise_role)
                # gm: discord.Member = self.team_manager_cog._find_member_by_name(ctx, gm_name)
                gm: discord.Member = self.team_manager_cog._get_gm(ctx, franchise_role)

                # performs role updates
                await member.remove_roles(*removable_roles)
                await member.add_roles(*add_roles)

                # Updates Name
                prefix, name, awards = self._get_name_components(member)
                new_name = self._generate_new_name('FA', name, awards)

                if member.nick != new_name:
                    try:
                        await member.edit(nick=new_name)
                    except:
                        pass
                
                transaction_msg = f"Contract with {member.mention} and {team} has expired ({gm.mention} - {tier_role.name})"

                await trans_channel.send(transaction_msg)
                await self.send_player_expire_contract_message(ctx, member, franchise_role, team, gm)

                empty = False
        if empty:
            message += ":x: Nobody was set as a free agent."
        else:
            message += ":white_check_mark: everyone that was found from list is now a free agent"
        if notFound > 0:
            message += ". {0} user(s) were not found".format(notFound)
        if free_agents > 0:
            message += ". {0} user(s) have been set as a free agent.".format(free_agents)
        await ctx.send(message)

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def draft(self, ctx, user: discord.Member, team_name: str, round: int = None, pick: int = None):
        """Assigns the franchise, tier, and league role to a user when they are drafted and posts to the assigned channel"""
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
        gm_name = self._get_gm_name(ctx, franchise_role)
        if franchise_role in user.roles:
            message = "Round {0} Pick {1}: {2} was kept by the {3} ({4} - {5})".format(
                round, pick, user.mention, team_name, gm_name, tier_role.name)
        else:
            message = "Round {0} Pick {1}: {2} was drafted by the {3} ({4} - {5})".format(
                round, pick, user.mention, team_name, gm_name, tier_role.name)

        trans_channel = await self._trans_channel(ctx)
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
    async def sign(self, ctx, user: discord.Member, team_name: str):
        """Assigns the team role, franchise role and prefix to a user when they are signed and posts to the assigned channel"""
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
        if franchise_role in user.roles and tier_role in user.roles:
            await ctx.send(":x: {0} is already on the {1}".format(user.mention, team_name))
            return

        trans_channel = await self._trans_channel(ctx)
        if trans_channel is not None:
            try:
                await self.add_player_to_team(ctx, user, team_name)
                free_agent_roles = await self.find_user_free_agent_roles(ctx, user)
                if len(free_agent_roles) > 0:
                    for role in free_agent_roles:
                        await user.remove_roles(role)
                gm_name = self._get_gm_name(ctx, franchise_role)
                message = "{0} was signed by the {1} ({2} - {3})".format(
                    user.mention, team_name, gm_name, tier_role.name)
                await trans_channel.send(message)
                await ctx.send("Done")
            except Exception as e:
                await ctx.send(e)

    @commands.guild_only()
    @commands.command(aliases=['re-sign', "rs"])
    @checks.admin_or_permissions(manage_roles=True)
    async def resign(self, ctx, user: discord.Member, team_name: str):
        """Re-signs a user to a given team, and if necessary, reapplys roles before posting to the assigned channel"""
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
        trans_channel = await self._trans_channel(ctx)
        gm_name = self._get_gm_name(ctx, franchise_role)
        message = "{0} was re-signed by the {1} ({2} - {3})".format(
            user.mention, team_name, gm_name, tier_role.name)

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
            await ctx.send('Done')
        else:
            await ctx.send("Unable to complete transaction as transaction channel is not set.")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def cut(self, ctx, user: discord.Member, team_name: str, tier_fa_role: discord.Role = None):
        """Removes the team role and franchise role. Adds the free agent prefix and role to a user and posts to the assigned channel"""
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
        trans_channel = await self._trans_channel(ctx)
        if trans_channel is not None:
            try:
                await self.remove_player_from_team(ctx, user, team_name)
                if not self.team_manager_cog.is_gm(user):
                    if tier_fa_role is None:
                        role_name = "{0}FA".format((await self.team_manager_cog.get_current_tier_role(ctx, user)).name)
                        tier_fa_role = self.team_manager_cog._find_role_by_name(ctx, role_name)
                    fa_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")
                    await self.team_manager_cog._set_user_nickname_prefix(ctx, "FA", user)
                    await user.add_roles(tier_fa_role, fa_role)
                gm_name = self._get_gm_name(ctx, franchise_role)
                message = f"{user.mention} was cut by the {team_name} ({gm_name} - {tier_role.name})"
                await trans_channel.send(message)

                franchise_name = self.team_manager_cog.get_franchise_name_from_role(franchise_role)
                cut_embed = await self.get_cut_embed(ctx, ctx.author, gm_name, franchise_name, team_name, tier_role.name)
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
    async def trade(self, ctx, user: discord.Member, new_team_name: str, user_2: discord.Member, new_team_name_2: str):
        """Swaps the teams of the two players and announces the trade in the assigned channel"""
        franchise_role_1, tier_role_1 = await self.team_manager_cog._roles_for_team(ctx, new_team_name)
        franchise_role_2, tier_role_2 = await self.team_manager_cog._roles_for_team(ctx, new_team_name_2)
        gm_name_1 = self._get_gm_name(ctx, franchise_role_1)
        gm_name_2 = self._get_gm_name(ctx, franchise_role_2)
        if franchise_role_1 in user.roles and tier_role_1 in user.roles:
            await ctx.send(":x: {0} is already on the {1}".format(user.mention, new_team_name))
            return
        if franchise_role_2 in user_2.roles and tier_role_2 in user_2.roles:
            await ctx.send(":x: {0} is already on the {1}".format(user_2.mention, new_team_name_2))
            return

        trans_channel = await self._trans_channel(ctx)
        if trans_channel is not None:
            await self.remove_player_from_team(ctx, user, new_team_name_2)
            await self.remove_player_from_team(ctx, user_2, new_team_name)
            await self.add_player_to_team(ctx, user, new_team_name)
            await self.add_player_to_team(ctx, user_2, new_team_name_2)
            message = "{0} was traded by the {1} ({4} - {5}) to the {2} ({6} - {7}) for {3}".format(user.mention, new_team_name_2, new_team_name,
                                                                                                    user_2.mention, gm_name_2, tier_role_2.name, gm_name_1, tier_role_1.name)
            await trans_channel.send(message)
            await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def sub(self, ctx, user: discord.Member, team_name: str, subbed_out_user: discord.Member = None):
        """
        Adds the team roles to the user and posts to the assigned transaction channel

        This command is also used to end substitution periods"""
        trans_channel = await self._trans_channel(ctx)
        free_agent_role = self.team_manager_cog._find_role_by_name(ctx, "Free Agent")
        perm_fa_role = self.team_manager_cog._find_role_by_name(ctx, "permFA")
        if trans_channel:
            leagueRole = self.team_manager_cog._find_role_by_name(ctx, self.LEAGUE_ROLE)
            if leagueRole:
                franchise_role, team_tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)

                # End Substitution
                if franchise_role in user.roles and team_tier_role in user.roles:
                    if list(set([free_agent_role, perm_fa_role]) & set(user.roles)):
                        await user.remove_roles(franchise_role)
                        team_tier_fa_role = self.team_manager_cog._find_role_by_name(ctx, "{0}FA".format(team_tier_role))
                        if not team_tier_fa_role in user.roles:
                            player_tier = await self.get_tier_role_for_fa(ctx, user)
                            await user.remove_roles(team_tier_role)
                            await user.add_roles(player_tier)
                    else:
                        await user.remove_roles(team_tier_role)
                    gm = self._get_gm_name(ctx, franchise_role, True)
                    message = f"{user.name} has finished their time as a substitute for the {team_name} ({gm} - {team_tier_role.name})"
                    # Removed subbed out role from all team members on team
                    subbed_out_role = self.team_manager_cog._find_role_by_name(ctx, self.SUBBED_OUT_ROLE)
                    if subbed_out_role:
                        team_members = self.team_manager_cog.members_from_team(ctx, franchise_role, team_tier_role)
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
                    gm = self._get_gm_name(ctx, franchise_role)
                    if subbed_out_user:
                        message = f"{user.mention} was signed to a temporary contract by the {team_name}, subbing for {subbed_out_user.name} ({gm} - {team_tier_role.name})"
                    else:
                        message = f"{user.mention} was signed to a temporary contract by the {team_name} ({gm} - {team_tier_role.name})"
                    # Give subbed out user the subbed out role if there is one
                    subbed_out_role = self.team_manager_cog._find_role_by_name(ctx, self.SUBBED_OUT_ROLE)
                    if subbed_out_user and subbed_out_role:
                        await subbed_out_user.add_roles(subbed_out_role)
                        player_ratings = self.bot.get_cog("PlayerRatings")
                        if player_ratings:
                            await player_ratings.set_player_temp_rating(ctx, user, subbed_out_user)
                    elif subbed_out_user:
                        await ctx.send(":x: The subbed out role is not set in this server")
                await trans_channel.send(message)
                await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def promote(self, ctx, user: discord.Member, team_name: str):
        """Adds the team tier role to the user and posts to the assigned channel"""
        old_team_name = await self.team_manager_cog.get_current_team_name(ctx, user)
        if old_team_name is not None:
            if (await self.team_manager_cog._roles_for_team(ctx, old_team_name))[0] != (await self.team_manager_cog._roles_for_team(ctx, team_name))[0]:
                await ctx.send(":x: {0} is not in the same franchise as {1}'s current team, the {2}".format(team_name.name, user.name, old_team_name))
                return

            trans_channel = await self._trans_channel(ctx)
            if trans_channel:
                await self.remove_player_from_team(ctx, user, old_team_name)
                await self.add_player_to_team(ctx, user, team_name)
                franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
                gm_name = self._get_gm_name(ctx, franchise_role)
                message = "{0} was promoted to the {1} ({2} - {3})".format(
                    user.mention, team_name, gm_name, tier_role.name)
                await trans_channel.send(message)
                await ctx.send("Done")
        else:
            await ctx.send("Either {0} isn't on a team right now or his current team can't be found".format(user.name))

    @commands.command(aliases=['lpwt'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def leaguePlayersWithoutTier(self, ctx: commands.Context):
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
        
        
        description: str = "\n".join([f"**{player.display_name}**: \<@{player.id}>" for player in no_tier_league_players]) if no_tier_league_players else "All League Players have tier assignmentss"
        color: discord.Color = discord.Color.red() if no_tier_league_players else discord.Color.green()
        embed = discord.Embed(title="League Players Without Tiers", description=description, color=color)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(aliases=["setTransChannel", "setTransactionsChannel"])
    @checks.admin_or_permissions(manage_guild=True)
    async def setTransactionChannel(self, ctx, trans_channel: discord.TextChannel):
        """Sets the channel where all transaction messages will be posted"""
        await self._save_trans_channel(ctx, trans_channel.id)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["getTransChannel"])
    @checks.admin_or_permissions(manage_guild=True)
    async def getTransactionChannel(self, ctx):
        """Gets the channel currently assigned as the transaction channel"""
        try:
            await ctx.send("Transaction log channel set to: {0}".format((await self._trans_channel(ctx)).mention))
        except:
            await ctx.send(":x: Transaction log channel not set")

    @commands.guild_only()
    @commands.command(aliases=["unsetTransChannel"])
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetTransactionChannel(self, ctx):
        """Unsets the transaction channel. Transactions will not be performed if no transaction channel is set"""
        await self._save_trans_channel(ctx, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setCutMessage(self, ctx, *, cut_message: str):
        """Sets the message to be sent to players when they are cut."""
        await self._save_cut_message(ctx.guild, cut_message)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command(aliases=["clearCutMessage"])
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetCutMessage(self, ctx):
        """Clears the cut message. When a cut message is not set, cut players will not receive a DM from the bot."""
        await self._save_cut_message(ctx.guild, None)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getCutMessage(self, ctx):
        embed = await self.get_cut_embed(ctx, ctx.author, "{franchise_name}", "{gm}", "{team_name}", "{tier_name}")
        if embed:
            await ctx.send(embed=embed)
        else:
            await ctx.send(":x: No cut message has been set.")

# endregion

# region helper functions
    async def get_cut_embed(self, ctx: commands.Context, player: discord.Member, gm_name, franchise_name, team_name, tier):
        cut_message = await self._get_cut_message(ctx.guild)
        cut_message = cut_message.format(
            player=player,
            franchise=franchise_name,
            gm=gm_name,
            team=team_name,
            tier=tier,
            guild=ctx.guild.name
        )
        embed = discord.Embed(
            title=f"Message from {ctx.guild.name}",
            description=cut_message,
            color=discord.Color.red()
        )
        
        try:
            embed.set_thumbnail(url=ctx.guild.icon_url)
        except:
            pass
        
        return embed

    async def add_player_to_team(self, ctx, user, team_name):
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
        leagueRole = self.team_manager_cog._find_role_by_name(ctx, "League")
        if leagueRole is not None:
            prefix = await self.prefix_cog._get_franchise_prefix(ctx, franchise_role)
            if prefix is not None:
                currentTier = await self.team_manager_cog.get_current_tier_role(ctx, user)
                if currentTier is not None and currentTier != tier_role:
                    await user.remove_roles(currentTier)
                await self.team_manager_cog._set_user_nickname_prefix(ctx, prefix, user)
                await user.add_roles(tier_role, leagueRole, franchise_role)

    async def remove_player_from_team(self, ctx, user, team_name):
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
        if franchise_role not in user.roles or tier_role not in user.roles:
            await ctx.send(":x: {0} is not on the {1}".format(user.mention, team_name))
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
            role = self.team_manager_cog._find_role_by_name(
                ctx, "{0}FA".format(tier))
            if role is not None:
                free_agent_roles.append(role)
        free_agent_roles.append(
            self.team_manager_cog._find_role_by_name(ctx, "Free Agent"))
        return free_agent_roles

    def get_player_nickname(self, user: discord.Member):
        return self.team_manager_cog.get_player_nickname(user)

    async def set_user_nickname_prefix(self, ctx, prefix: str, user: discord.member):
        return self.team_manager_cog._set_user_nickname_prefix(ctx, prefix, user)

    async def get_tier_role_for_fa(self, ctx, user: discord.Member):
        fa_roles = await self.find_user_free_agent_roles(ctx, user)
        standard_fa_role = self.team_manager_cog._find_role_by_name(
            ctx, "Free Agent")
        if standard_fa_role in fa_roles:
            fa_roles.remove(standard_fa_role)
        tier_role_name = fa_roles[0].name[:-2]
        tier_role = self.team_manager_cog._find_role_by_name(
            ctx, tier_role_name)
        return tier_role

    def _get_gm_name(self, ctx, franchise_role, returnNameAsString=False):
        gm = self.team_manager_cog._get_gm(ctx, franchise_role)
        if gm:
            if returnNameAsString:
                return gm.name
            else:
                return gm.mention
        else:
            return self.team_manager_cog._get_gm_name(franchise_role)

    async def _send_member_message(self, ctx, member, message):
        if not message:
            return False
        message_title = "**Message from {0}:**\n\n".format(ctx.guild.name)
        command_prefix = ctx.prefix
        message = message.replace('[p]', command_prefix)
        message = message_title + message
        
        await self.dm_helper_cog.add_to_dm_queue(member, content=message, ctx=ctx)

    async def send_player_expire_contract_message(self, ctx: commands.Context, player: discord.Member, franchise_role: discord.Role, team: str, gm: discord.Member):
        franchise_name = self.team_manager_cog.get_franchise_name_from_role(franchise_role)
        msg = stringTemplates.contract_expiration_msg.format(
            p=ctx.prefix, player=player, team=team, franchise=franchise_name, gm=gm.display_name
        )
        
        embed = discord.Embed(title=f"Notice from {ctx.guild.name}", description=msg, color=discord.Color.blue())
        if ctx.guild.icon_url:
            embed.set_thumbnail(url=ctx.guild.icon_url)

        await self.dm_helper_cog.add_to_dm_queue(member=player, embed=embed, ctx=ctx)

    def _get_name_components(self, member: discord.Member):
        if member.nick:
            name = member.nick
        else:
            return "", member.name, ""
        prefix = name[0:name.index(' | ')] if ' | ' in name else ''
        if prefix:
            name = name[name.index(' | ')+3:]
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
            awards = ''.join(sorted(awards))
            new_name += " {}".format(awards)
        return new_name

# endregion

# region json db

    async def _trans_channel(self, ctx):
        return ctx.guild.get_channel(await self.config.guild(ctx.guild).TransChannel())

    async def _save_trans_channel(self, ctx, trans_channel):
        await self.config.guild(ctx.guild).TransChannel.set(trans_channel)

    async def _get_cut_message(self, guild):
        return await self.config.guild(guild).CutMessage()

    async def _save_cut_message(self, guild, message):
        await self.config.guild(guild).CutMessage.set(message)

# endregion
