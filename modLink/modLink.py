import asyncio
import discord
import logging
from datetime import date, datetime
from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

from typing import Union, NoReturn, Optional, List

log = logging.getLogger("red.RSCBot.modLink")

# Bot Detection
SPAM_JOIN_BT = "spam join"
SUS_NEW_ACC_BT = "suspicious new account"
NEW_MEMBER_JOIN_TIME = 300  # 5 minutes
ACC_AGE_THRESHOLD = 86400  # 1 day
DISABLE_BOT_INVITES = False

defaults = {
    "Guilds": [],
    "SharedRoles": ["Muted"],
    "EventLogChannel": None,
    "BotDetection": False,
    "WelcomeMessage": None,
    "ModeratorRole": None,
    "BlacklistedNames": ["reward", "giveaway", "give away", "gift", "drop", "bot"],
}


class ModeratorLink(commands.Cog):
    def __init__(self, bot):
        self.config = Config.get_conf(
            self, identifier=1234567892, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.bot = bot

        self.TROPHY_EMOJI = "\U0001F3C6"  # :trophy:
        self.GOLD_MEDAL_EMOJI = "\U0001F3C5"  # gold medal
        self.FIRST_PLACE_EMOJI = "\U0001F947"  # first place medal
        self.STAR_EMOJI = "\U00002B50"  # :star:
        self.LEAGUE_AWARDS = [
            self.TROPHY_EMOJI,
            self.GOLD_MEDAL_EMOJI,
            self.FIRST_PLACE_EMOJI,
            self.STAR_EMOJI,
        ]
        self.whitelist = []
        self.bot_detection = {}
        self.recently_joined_members = {}
        asyncio.create_task(self._pre_load_data())

    def cog_unload(self):
        """Clean up when cog shuts down."""
        self.cancel_all_tasks()

    # Mod Role

    @commands.guild_only()
    @commands.group(name="modlink", aliases=["mlink"])
    @checks.admin_or_permissions(manage_guild=True)
    async def _mod_link(self, ctx: commands.Context) -> NoReturn:
        """Display or configure mod link cog settings"""
        pass

    @_mod_link.command(name="settings", aliases=["info"])
    async def _mod_link_settings(self, ctx: commands.Context):
        """Display the current Mod Link configuration."""
        mod_role = await self._mod_role(ctx.guild)
        bot_detect = await self._get_bot_detection(ctx.guild)
        event_channel = await self._event_log_channel(ctx.guild)
        shared_roles = await self._get_shared_role_names(ctx.guild)
        welcome_msg = await self._get_welcome_message(ctx.guild) or "None"

        # Format Shared Roles
        converted_roles = []
        for r in shared_roles:
            srole = discord.utils.get(ctx.guild.roles, name=r)
            if not srole:
                log.debug(f"Shared role {r} not found in {ctx.guild.name}.")
                converted_roles.append(f"{r} **(NOT FOUND)**")
            else:
                converted_roles.append(srole.mention)

        if not len(converted_roles):
            converted_roles = "None"
        else:
            converted_roles = ", ".join(converted_roles)

        settings_embed = discord.Embed(
            title="Mod Link Settings",
            description="Current configuration for Mod Link Cog.",
            color=discord.Color.blue(),
        )

        if mod_role:
            settings_embed.add_field(
                name="Moderator Role", value=mod_role.mention, inline=False
            )
        else:
            settings_embed.add_field(name="Moderator Role", value="None", inline=False)
        settings_embed.add_field(name="Bot Detection", value=bot_detect, inline=False)
        if event_channel:
            settings_embed.add_field(
                name="Event Channel", value=event_channel.mention, inline=False
            )
        else:
            settings_embed.add_field(name="Event Channel", value="None", inline=False)
        settings_embed.add_field(
            name="Shared Roles", value=converted_roles, inline=False
        )
        settings_embed.add_field(
            name="Welcome Message", value=welcome_msg, inline=False
        )
        await ctx.send(embed=settings_embed)

    @_mod_link.command(name="modrole", aliases=["mrole"])
    async def _set_mod_role(self, ctx: commands.Context, role: discord.Role):
        """Configure the Moderator Role"""
        await self._save_mod_role(ctx.guild, role.id)
        await ctx.send(
            embed=discord.Embed(
                title="Moderator Role Configured",
                description=f"Moderator role has been set to {role.mention}",
                color=discord.Color.green(),
            )
        )

    @_mod_link.command(name="welcome", aliases=["welcomemsg"])
    async def _set_welcome_msg(self, ctx: commands.Context, *, message: str):
        """Configure the welcome message"""
        await self._save_welcome_message(ctx.guild, message)
        await ctx.send(
            embed=discord.Embed(
                title="Welcome Message Configured",
                description=message,
                color=discord.Color.green(),
            )
        )

    @_mod_link.command(name="botdetect", aliases=["bot"])
    async def _toggle_bot_detection(self, ctx: commands.Context):
        """Toggle bot detection on or off"""
        bd = await self._get_bot_detection(ctx.guild)
        bd ^= True  # Flip boolean with xor
        await self._save_bot_detection(ctx.guild, bd)

        # Update self.bot_detection and reload data
        self.bot_detection[ctx.guild] = bd
        if bd:
            await self._pre_load_data()
        else:
            self.cancel_all_tasks(ctx.guild)

        await ctx.send(
            embed=discord.Embed(
                title="Bot Detection Toggled",
                description=f"Bot detection is now **{'enabled' if bd else 'disabled'}**",
                color=discord.Color.green(),
            )
        )

    @_mod_link.command(name="events", aliases=["eventchannel"])
    async def _set_event_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Configure the event channel"""
        await self._save_event_log_channel(ctx.guild, channel.id)
        await ctx.send(
            embed=discord.Embed(
                title="Event Channel Configured",
                description=f"Event channel is now set to {channel.mention}",
                color=discord.Color.green(),
            )
        )

    @_mod_link.command(name="sharedroles", aliases=["sroles"])
    async def _set_shared_roles(self, ctx: commands.Context, *roles: discord.Role):
        """Configure the shared roles across guilds"""
        rnames = [r.name for r in roles]
        log.debug(rnames)
        await self._save_shared_roles(ctx.guild, rnames)
        format_roles = "\n".join([r.mention for r in roles])
        await ctx.send(
            embed=discord.Embed(
                title="Shared Roles Configured",
                description=f"Updated shared roles to the following.\n\n{format_roles}",
                color=discord.Color.green(),
            )
        )

    @_mod_link.group(name="unset")
    async def _mod_link_unset(self, ctx: commands.Context):
        """Remove a mod link configuration option"""
        pass

    @_mod_link_unset.command(name="modrole", aliases=["mrole"])
    async def _clear_mod_role(self, ctx: commands.Context):
        """Remove the moderator role"""
        await self._save_mod_role(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Moderator Role Removed",
                description=f"Moderator role has been removed.",
                color=discord.Color.orange(),
            )
        )

    @_mod_link_unset.command(name="welcome", aliases=["welcomemsg"])
    async def _clear_welcome_msg(self, ctx: commands.Context):
        """Remove the welcome message"""
        await self._save_welcome_message(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Welcome Message Removed",
                description=f"Welcome message has been removed.",
                color=discord.Color.orange(),
            )
        )

    @_mod_link_unset.command(name="events", aliases=["eventchannel"])
    async def _clear_event_channel(self, ctx: commands.Context):
        """Remove the event channel"""
        await self._save_event_log_channel(ctx.guild, None)
        await ctx.send(
            embed=discord.Embed(
                title="Event Channel Removed",
                description=f"Event channel has been removed.",
                color=discord.Color.orange(),
            )
        )

    @_mod_link_unset.command(name="sharedroles", aliases=["sroles"])
    async def _clear_shared_roles(self, ctx: commands.Context):
        """Remove shared roles"""
        await self._save_shared_roles(ctx.guild, [])
        await ctx.send(
            embed=discord.Embed(
                title="Shared Roles Removed",
                description=f"Shared roles have been removed.",
                color=discord.Color.orange(),
            )
        )

    @commands.guild_only()
    @commands.command()
    async def whitelistUser(self, ctx, user_id: discord.User):
        """Allows a member to manually pass bot detection"""
        if not await self.has_perms(ctx.author):
            return
        self.whitelist.append(user_id.id)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    async def blacklistName(self, ctx, *, name: str):
        """Adds a name to the bot account blacklist"""
        if not await self.has_perms(ctx.author):
            return
        name = name.lower()
        blacklisted_names = await self._get_blacklisted_names(ctx.guild)
        if name not in blacklisted_names:
            blacklisted_names.append(name)
            await self._save_blacklisted_names(ctx.guild, blacklisted_names)

        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    async def getBlacklistedNames(self, ctx):
        """Gets all names in the bot name blacklist"""
        if not await self.has_perms(ctx.author):
            return
        blacklisted_names = await self._get_blacklisted_names(ctx.guild)
        blacklisted = "__Blacklisted Names:__\n - {}".format(
            "\n - ".join(blacklisted_names)
        )
        if blacklisted_names:
            return await ctx.send(blacklisted)
        return await ctx.send(":x: No names are currently blacklisted.")

    @commands.guild_only()
    @commands.command()
    async def getUserWhitelist(self, ctx):
        """Gets all user ids in the bot name whitelist"""
        if not await self.has_perms(ctx.author):
            return
        whitelisted_str = [str(w) for w in self.whitelist]
        whitelisted = "__Whitelisted User IDs:__\n - {}".format(
            "\n - ".join(whitelisted_str)
        )
        if self.whitelist:
            return await ctx.send(whitelisted)
        return await ctx.send(":x: No users are currently whitelisted.")

    @commands.guild_only()
    @commands.command(aliases=["recentJoins"])
    async def getRecentJoins(self, ctx):
        """Gets all recent member names being tracked"""
        if not await self.has_perms(ctx.author):
            return
        recent_joins = "__Recent Member Joins:__"
        tracked_joins = 0
        for name, join_data in self.recently_joined_members[ctx.guild].items():
            num_joins = len(join_data["members"])
            recent_joins += f"\n - {name} ({num_joins})"
            tracked_joins += num_joins

        if tracked_joins:
            return await ctx.send(recent_joins)
        minutes = NEW_MEMBER_JOIN_TIME // 60
        return await ctx.send(
            f":x: No members have joined in the past {minutes} minutes."
        )

    @commands.guild_only()
    @commands.command()
    async def unblacklistName(self, ctx, *, name: str):
        """Removes a name to the bot account blacklist"""
        if not await self.has_perms(ctx.author):
            return
        blacklisted_names = await self._get_blacklisted_names(ctx.guild)
        if name.lower() in blacklisted_names:
            blacklisted_names.remove(name.lower())
            await self._save_blacklisted_names(ctx.guild, blacklisted_names)
            return await ctx.send("Done")
        else:
            await ctx.send(f":x: **{name}** is not a blacklisted name.")

    @commands.guild_only()
    @commands.command()
    async def unwhitelistUser(self, ctx, user_id: discord.User):
        """Removes a name to the bot account blacklist"""
        if not await self.has_perms(ctx.author):
            return
        if user_id.id in self.whitelist:
            self.whitelist.remove(user_id.id)
            return await ctx.send("Done")
        return await ctx.send(f":x: User ID {user_id} was not whitelisted.")

    # League Awards
    @commands.guild_only()
    @commands.command(aliases=["champion", "assignTrophy", "awardTrophy"])
    async def addTrophy(self, ctx, *userList):
        """Adds a trophy to each user passed in the userList"""
        if not await self.has_perms(ctx.author):
            return
        await self.award_players(ctx, self.TROPHY_EMOJI, userList)

    @commands.guild_only()
    @commands.command(aliases=["allstar", "assignStar", "awardStar"])
    async def addStar(self, ctx, *userList):
        """Adds a star to each user passed in the userList"""
        if not await self.has_perms(ctx.author):
            return
        await self.award_players(ctx, self.STAR_EMOJI, userList)

    @commands.guild_only()
    @commands.command()
    async def removeStar(self, ctx, *userList: discord.Member):
        """Removes a star from each user passed in the userList"""
        if not await self.has_perms(ctx.author):
            return
        for user in userList:
            new_name = user.nick.replace(self.STAR_EMOJI, "")
            await user.edit(nick=new_name)
        await ctx.send(f"Removed stars from **{len(userList)} player(s)**.")

    @commands.guild_only()
    @commands.command(aliases=["assignMedal", "awardMedal"])
    async def addMedal(self, ctx, *userList):
        """Adds a first place medal to each user passed in the userList"""
        if not await self.has_perms(ctx.author):
            return
        await self.award_players(ctx, self.FIRST_PLACE_EMOJI, userList)

    @commands.guild_only()
    @commands.command(aliases=["clearAllStars"])
    @checks.admin_or_permissions(manage_guild=True)
    async def removeAllStars(self, ctx):
        """Removes the Star Emoji from all discord members who have it."""
        all_stars = []
        for member in ctx.guild.members:
            if member.nick:
                if self.STAR_EMOJI in member.nick:
                    all_stars.append(member)

        successes = []
        failures = []
        for member in all_stars:
            try:
                new_name = member.nick.replace(self.STAR_EMOJI, "")
                await member.edit(nick=new_name)
                successes.append(member)
            except:
                failures.append(member)

        msg = ""
        if successes:
            msg = "{} award removed from **{} members**:\n - {}".format(
                self.STAR_EMOJI,
                len(successes),
                "\n - ".join(member.mention for member in successes),
            )
        if failures:
            msg += "\n{} award could not be removed from **{} members**:\n - {}".format(
                self.STAR_EMOJI,
                len(failures),
                "\n - ".join(member.mention for member in failures),
            )

        if msg:
            return await ctx.send(msg)
        await ctx.send(
            f":x: No members have been awarded with the {self.STAR_EMOJI} emoji."
        )

    # Ban/Unban
    # @commands.guild_only()
    # @commands.command()
    # @checks.admin_or_permissions(manage_guild=True)
    # async def ban(self, ctx, user: discord.User, *, reason=None):
    #     await ctx.guild.ban(user, reason=reason, delete_message_days=0)
    #     await ctx.send("Done.")

    # @commands.guild_only()
    # @commands.command()
    # @checks.admin_or_permissions(manage_guild=True)
    # async def unban(self, ctx, user: discord.User, *, reason=None):
    #     await ctx.guild.unban(user, reason=reason)
    #     await ctx.send("Done.")

    # Events
    @commands.Cog.listener("on_user_update")
    async def on_user_update(self, before: discord.Member, after: discord.Member):
        """Catches when a user changes their discord name or discriminator. [Not yet supported]"""
        if before.name != after.name:
            pass
        if before.discriminator != after.discriminator:
            pass

    @commands.Cog.listener("on_member_update")
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Processes updates for roles or nicknames, and shares them across the guild network."""

        # If roles updated:
        if before.roles != after.roles:
            await self._process_role_update(before, after)

        # If nickname changed:
        try:
            before_name = before.nick
        except:
            before_name = before.name
        try:
            after_name = after.nick
        except:
            after_name = after.name

        seconds_in_server = (discord.utils.utcnow() - before.joined_at).seconds
        if before_name != after_name and seconds_in_server > 120:
            await self._process_nickname_update(before, after)

    @commands.Cog.listener("on_member_ban")
    async def on_member_ban(
        self, guild: discord.Guild, user: Union[discord.Member, discord.User]
    ):
        """Upon a member ban, members in the guild network will be banned automatically."""
        if not await self._event_log_channel(guild):
            return

        # Iterate RSC related servers and take the same action.
        for linked_guild in self.bot.guilds:
            # Check guild is available and if we have ban permissions.
            if (
                linked_guild.unavailable
                or not linked_guild.me.guild_permissions.ban_members
            ):
                log.warning(
                    f"Unable to propagate ban action to {linked_guild.name}. Bot does not have ban_members permission or guild unavailable."
                )
                continue

            linked_guild_log = await self._event_log_channel(linked_guild)
            is_banned = False
            async for ban in linked_guild.bans():
                if ban.user == user:
                    is_banned = True
                    break

            if linked_guild_log and not is_banned:
                await linked_guild.ban(
                    user,
                    reason=f"Banned from {guild.name}.",
                    delete_message_seconds=0,
                )
                await linked_guild_log.send(
                    f"**{user.name}** (id: {user.id}) has been banned. [initiated from **{guild.name}**]"
                )

    @commands.Cog.listener("on_member_unban")
    async def on_member_unban(
        self, guild: discord.Member, user: Union[discord.Member, discord.User]
    ):
        """Upon a member unban, members in the guild network will be unbanned automatically."""
        if not await self._event_log_channel(guild):
            return

        # Iterate RSC related servers and take the same action.
        for linked_guild in self.bot.guilds:
            # Check guild is available and if we have ban permissions.
            if (
                linked_guild.unavailable
                or not linked_guild.me.guild_permissions.ban_members
            ):
                log.warning(
                    f"Unable to propagate unban action to {linked_guild.name}. Bot does not have ban_members permission or guild unavailable."
                )
                continue

            linked_guild_log = await self._event_log_channel(linked_guild)
            is_banned = False
            async for ban in linked_guild.bans():
                if ban.user == user:
                    is_banned = True
                    break

            if linked_guild_log and is_banned:
                await linked_guild.unban(user, reason=f"Unbanned from {guild.name}.")
                await linked_guild_log.send(
                    f"**{user.mention}** (id: {user.id}) has been unbanned. [initiated from **{guild.name}**]"
                )

    @commands.Cog.listener("on_member_join")
    async def on_member_join(self, member: discord.Member):
        """Processes events for when a member joins the guild such as welcome messages and
        nickname standardization, and bot purging."""

        # Run bot detection if enabled
        if self.bot_detection[member.guild]:
            # Do not process member standardization if member has been detected as a bot
            if await self.run_bot_detection(member):
                return

        event_log_channel = await self._event_log_channel(member.guild)
        if event_log_channel:
            await self.process_member_standardization(member)

        # Send welcome message if one exists
        await self.maybe_send_welcome_message(member)

    # Helper Functions
    async def process_member_standardization(self, member):
        mutual_guilds = await self._member_mutual_guilds(member)
        shared_role_names = await self._get_shared_role_names(member.guild)
        event_log_channel = await self._event_log_channel(member.guild)
        mutual_guilds.remove(member.guild)
        for guild in mutual_guilds:
            guild_event_log_channel = await self._event_log_channel(guild)
            if guild_event_log_channel:
                guild_member = await self._guild_member_from_id(guild, member.id)
                guild_prefix, guild_nick, guild_awards = self._get_name_components(
                    guild_member
                )

                if guild_nick != member.name:
                    await member.edit(nick=guild_nick)
                    await event_log_channel.send(
                        f"{member.mention} (**{member.name}**, id: {member.id}) has had thier nickname set to **{guild_nick}** upon joining the server [discovered from **{guild.name}**]"
                    )

                if shared_role_names:
                    # if member has shared role
                    member_shared_roles = []
                    for guild_member_role in guild_member.roles:
                        if guild_member_role.name in shared_role_names:
                            sis_role = await self._guild_sister_role(
                                member.guild, guild_member_role
                            )
                            if sis_role:
                                member_shared_roles.append(sis_role)

                    if member_shared_roles:
                        await member.add_roles(*member_shared_roles)
                        await event_log_channel.send(
                            "{} had one or more shared roles assigned upon joining this server: {} [discovered from **{}**]".format(
                                member.mention,
                                ", ".join(role.mention for role in member_shared_roles),
                                guild.name,
                            )
                        )

                    return

    async def maybe_send_welcome_message(self, member: discord.Member) -> None:
        guild = member.guild
        welcome_msg = await self._get_welcome_message(guild)
        channel = guild.system_channel
        if channel and welcome_msg:
            try:
                await channel.send(
                    content=welcome_msg.format(member=member, guild=guild.name),
                    allowed_mentions=discord.AllowedMentions.all,
                )
            except Exception as exc:
                log.error(
                    f"Error sending welcome message: {type(exc)} {exc} - Guild: {guild.name}"
                )

    # region bot detection
    async def has_perms(self, member: discord.Member):
        if member.guild_permissions.administrator:
            return True
        helper_role = await self._mod_role(member.guild)
        if helper_role and helper_role in member.roles:
            return True

    async def create_invite(self, channel: discord.TextChannel, retry=0, retry_max=3):
        try:
            return await channel.create_invite(
                temporary=True
            )  # , max_uses=1, ) # max_age=86400)
        except discord.HTTPException:
            # Try x more times
            if retry <= retry_max:
                return await self.create_invite(channel, retry + 1, retry_max)
            else:
                return None

    async def run_bot_detection(self, member):
        # IGNORE WHITELISTED MEMBERS
        if member.id in self.whitelist:
            return False

        # SPAM JOIN PREVENTION
        repeat_recent_name = self.track_member_join(member)

        ## Kick/Ban first member when subsequent member flagged as bot
        if (
            repeat_recent_name
            and len(self.recently_joined_members[member.guild][member.name]["members"])
            == 2
        ):
            first_member = self.recently_joined_members[member.guild][member.name][
                "members"
            ][0]
            await self.process_bot_member_kick(
                first_member, reason=(SPAM_JOIN_BT + " - catch first")
            )

        ## Kick/ban newly joined member
        if repeat_recent_name:
            await self.process_bot_member_kick(member, reason=SPAM_JOIN_BT)
            # TODO: save bot name as blacklisted name?
            return True

        # SUSPICIOUS NEW ACCOUNTS
        for blacklist_name in await self._get_blacklisted_names(
            member.guild
        ):  # await self._get_name_blacklist():
            account_age = (discord.utils.utcnow() - member.created_at).seconds
            if (
                blacklist_name in member.name.lower()
                and account_age <= ACC_AGE_THRESHOLD + 10
            ):
                await self.process_bot_member_kick(member, reason=SUS_NEW_ACC_BT)
                return True
        return False

    async def _pre_load_data(self):
        await self.bot.wait_until_ready()
        self.whitelist = []
        self.bot_detection = {}
        self.recently_joined_members = {}
        for guild in self.bot.guilds:
            self.recently_joined_members[guild] = {}
            self.bot_detection[guild] = await self._get_bot_detection(guild)

    def track_member_join(self, member: discord.Member):
        member_join_data = self.recently_joined_members[member.guild].setdefault(
            member.name, {"members": [], "timeout": None}
        )

        # cover case where member leaves, rejoins
        repeat_member = member.id in [m.id for m in member_join_data["members"]]
        if repeat_member:
            if len(member_join_data["members"]) == 1:
                return False
            return True

        # add member to recent joins
        member_join_data["members"].append(member)
        if member_join_data["timeout"]:
            member_join_data["timeout"].cancel()

        member_join_data["timeout"] = asyncio.create_task(
            self.schedule_new_member_name_clear(member)
        )
        self.recently_joined_members[member.guild][member.name] = member_join_data
        repeat_recent_name = len(member_join_data["members"]) > 1

        return repeat_recent_name

    async def schedule_new_member_name_clear(
        self, member: discord.Member, time_sec: int = None
    ):
        if not time_sec:
            time_sec = NEW_MEMBER_JOIN_TIME
        await asyncio.sleep(time_sec)
        self.recently_joined_members[member.guild][member.name]["timeout"].cancel()
        del self.recently_joined_members[member.guild][member.name]

    async def process_bot_member_kick(
        self, member: discord.Member, reason=None, ban=False
    ):
        guild = member.guild
        channel = guild.system_channel
        owner = guild.owner
        if channel:
            invite = await self.create_invite(channel)
        else:
            invite = None

        action = "banned" if ban else "kicked"
        message = (
            "You have been flagged as a bot account and **{}** from **{}**. "
            + "\n\nIf this was a mistake or the issue persists, please send a message to **{}#{}**."
        )
        message = message.format(action, guild.name, owner.name, owner.discriminator)

        # TODO: save invite as "trusted" invite
        if invite:
            message += f" Alternatively, you can wait 5 minutes, then [Click Here]({invite.url}) to rejoin the guild!"
        message += "\n\nWe aplogize for the inconvenience."

        embed = discord.Embed(
            title=f"Message from {guild.name}",
            color=discord.Color.red(),
            description=message,
        )
        embed.set_thumbnail(url=guild.icon.url)

        # Send message to kicked/banned member
        try:
            await member.send(embed=embed)
        except:
            pass

        reason_note = "suspected bot"
        if reason:
            reason_note += f": {reason}"

        # Kick or Ban members, log if even log channel is set
        event_log_channel = await self._event_log_channel(member.guild)
        try:
            if ban:
                await member.ban(reason=reason_note, delete_message_seconds=7 * 86400)
            else:
                await member.kick(reason=reason_note)
            if event_log_channel:
                await event_log_channel.send(
                    f"**{member.name}** (id: {member.id}) has been flagged as a bot account and **{action}** from the server (Reason: {reason})."
                )
        except:
            if event_log_channel:
                current_action_word = "banning" if action == "banned" else "kicked"
                await event_log_channel.send(
                    f"**{member.name}** (id: {member.id}) has been flagged as a bot account, but an error ocurred when **{action}ing** from the server (Reason: {reason})."
                )

    def cancel_all_tasks(self, guild=None):
        guilds = [guild] if guild else self.bot.guilds
        for guild in guilds:
            for name, join_data in self.recently_joined_members[guild].items():
                join_data["timeout"].cancel()
            self.recently_joined_members[guild] = {}

    # endregion bot detection

    # region general helpers
    async def _process_role_update(self, before: discord.Member, after: discord.Member):

        event_log_channel = await self._event_log_channel(before.guild)

        if not event_log_channel:
            return False

        removed_roles = list(set(before.roles) - set(after.roles))
        added_roles = list(set(after.roles) - set(before.roles))

        other_guilds = before.mutual_guilds
        other_guilds.remove(before.guild)

        if not removed_roles and not added_roles:
            return
        elif added_roles:
            await self._process_role_addition(added_roles, other_guilds, before)
        elif removed_roles:
            await self._process_role_removal(removed_roles, other_guilds, before)


    async def _process_role_addition(self, added_roles, other_guilds, before: discord.Member):

        # # this will try to add a role from one guild to another. TODO: get matching role from each guild as well.
        shared_role_names = await self._get_shared_role_names(before.guild)

        log.debug("Processing shared role addition.")
        log.debug(f"Shared Roles: {shared_role_names}")
        log.debug(f"Added Roles: {added_roles}")

        # Process Role Additions
        role_assign_msg = "Shared role {} added to {} [initiated from **{}**]"

        for role in added_roles:
            if role.name in shared_role_names:
                log.debug(f"Role {role.name} is a shared role")
                for guild in other_guilds:
                    log.debug(f"Adding role {role.name} in guild {guild}")
                    guild_role = await self._guild_sister_role(guild, role)
                    guild_member = await self._guild_member_from_id(guild, before.id)
                    channel = await self._event_log_channel(guild_member.guild)
                    if guild_role and guild_role not in guild_member.roles and channel:
                        await guild_member.add_roles(
                            guild_role
                        )  # This was sometimes None? added 'guild_role and' to condition
                        await channel.send(
                            role_assign_msg.format(
                                guild_role.mention, guild_member.mention, before.guild.name
                            )
                        )

    async def _process_role_removal(self, removed_roles, other_guilds, before: discord.Member):
                
        # # this will try to add a role from one guild to another. TODO: get matching role from each guild as well.
        shared_role_names = await self._get_shared_role_names(before.guild)

        log.debug("Processing shared role removal.")
        log.debug(f"Shared Roles: {shared_role_names}")
        log.debug(f"Removed Roles: {removed_roles}")

        # Process Role Removals
        role_removal_msg = "Shared role {} removed from **{}** [initiated from **{}**]"
    
        for role in removed_roles:
            if role.name in shared_role_names:
                log.debug(f"Role {role.name} is a shared role")
                for guild in other_guilds:
                    log.debug(f"Removing role {role.name} in guild {guild}")
                    guild_role = await self._guild_sister_role(guild, role)
                    guild_member = await self._guild_member_from_id(guild, before.id)
                    channel = await self._event_log_channel(guild_member.guild)
                    if guild_role in guild_member.roles and channel:
                        await guild_member.remove_roles(guild_role)
                        await channel.send(
                            role_removal_msg.format(
                                guild_role.mention, guild_member.mention, before.guild.name
                            )
                        )


    async def _guild_member_from_id(self, guild, member_id):
        return guild.get_member(member_id)

    def _guild_role_from_name(self, guild, role_name):
        for role in guild.roles:
            if role.name == role_name:
                return role

    async def _member_mutual_guilds(self, member: discord.Member):
        mutual_guilds = []
        for guild in self.bot.guilds:
            if member in guild.members:
                mutual_guilds.append(guild)
        return mutual_guilds

    async def _guild_sister_role(self, guild, sister_role):
        for role in guild.roles:
            if role.name == sister_role.name and role != sister_role:
                return role
        return None

    # endregion general helpers

    # region nickname mgmt
    async def award_players(self, ctx, award, userList):
        found = []
        notFound = []
        success_count = 0
        failed = 0
        for user in userList:
            try:
                member = await commands.MemberConverter().convert(ctx, user)
                if member in ctx.guild.members:
                    found.append(member)
            except:
                notFound.append(user)

        for player in found:
            prefix, nick, awards = self._get_name_components(player)
            awards += award
            new_name = self._generate_new_name(prefix, nick, awards)
            try:
                await player.edit(nick=new_name)
                success_count += 1
            except:
                failed += 1

        message = ""
        if success_count:
            message = f":white_check_mark: Trophies have been added to **{success_count} player(s)**."

        if notFound:
            message += f"\n:x: {len(notFound)} members could not be found."

        if failed:
            message += f"\n:x: Nicknames could not be changed for {failed} members."

        if message:
            message += "\nDone"
        else:
            message = "No members changed."

        await ctx.send(message)

    async def _process_nickname_update(self, before, after):
        b_prefix, b_nick, b_awards = self._get_name_components(before)
        a_prefix, a_nick, a_awards = self._get_name_components(after)
        event_log_channel = await self._event_log_channel(before.guild)

        if b_nick == a_nick or not event_log_channel:
            return

        mutual_guilds = await self._member_mutual_guilds(
            before
        )  # before.mutual_guilds not working
        mutual_guilds.remove(before.guild)

        for guild in mutual_guilds:
            channel = await self._event_log_channel(guild)
            if channel:
                guild_member = await self._guild_member_from_id(guild, before.id)
                guild_prefix, guild_nick, guild_awards = self._get_name_components(
                    guild_member
                )
                try:
                    if guild_nick != a_nick:
                        new_guild_name = self._generate_new_name(
                            guild_prefix, a_nick, guild_awards
                        )
                        await guild_member.edit(nick=new_guild_name)
                        await channel.send(
                            f"{guild_member.mention} has changed their name from **{guild_nick}** to **{a_nick}** [initiated from **{before.guild.name}**]"
                        )
                except:
                    pass

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
        new_name = f"{prefix} | {name}" if prefix else name
        if awards:
            awards = "".join(sorted(awards))
            new_name += f" {awards}"
        return new_name

    # endregion nickname mgmt

    # region json data
    async def _get_bot_detection(self, guild: discord.Guild) -> bool:
        return await self.config.guild(guild).BotDetection()

    async def _save_bot_detection(self, guild: discord.Guild, bot_detection: bool):
        await self.config.guild(guild).BotDetection.set(bot_detection)

    async def _get_welcome_message(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).WelcomeMessage()

    async def _save_welcome_message(self, guild: discord.Guild, message: str):
        await self.config.guild(guild).WelcomeMessage.set(message)

    async def _get_blacklisted_names(self, guild: discord.Guild) -> Optional[str]:
        return await self.config.guild(guild).BlacklistedNames()

    async def _save_blacklisted_names(self, guild: discord.Guild, name: str):
        await self.config.guild(guild).BlacklistedNames.set(name)

    async def _save_event_log_channel(self, guild: discord.Guild, event_channel: int):
        await self.config.guild(guild).EventLogChannel.set(event_channel)
        # await self.config.guild(ctx.guild).TransChannel.set(trans_channel)

    async def _event_log_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        return guild.get_channel(await self.config.guild(guild).EventLogChannel())

    async def _save_mod_role(self, guild: discord.Guild, mod_role: int):
        await self.config.guild(guild).ModeratorRole.set(mod_role)

    async def _mod_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        return guild.get_role(await self.config.guild(guild).ModeratorRole())

    async def _save_shared_roles(
        self, guild: discord.Guild, shared_role_names: List[str]
    ):
        await self.config.guild(guild).SharedRoles.set(shared_role_names)

    async def _get_shared_role_names(self, guild: discord.Guild) -> List[str]:
        return await self.config.guild(guild).SharedRoles()

    # endregion json data
