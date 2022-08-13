
import discord
from redbot.core import commands, Config, checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

from datetime import datetime
import asyncio
import logging

log : logging.Logger = logging.getLogger("red.RSCBot.dmHelper")

dm_sleep_time = 0.5
verify_timeout = 30

# role for "Needs to DM Bot"
global_defaults = {"FailedUserMessages": {}}
guild_defaults = {"DMNotifyChannel": None, "DMNotifyRole": None}

DONE = "Done"

# TODO: Changes/additions
# Send previously failed messages
# Sync roles on server join

class DMHelper(commands.Cog):
    """Controls Bot-to-member Direct Messages (DMs) with code to prevent rate limiting."""

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=1234567895, force_registration=True)
        self.config.register_global(**global_defaults)
        self.config.register_guild(**guild_defaults)
        
        self.bot = bot
        self.message_queue : list = []
        self.priority_message_queue : list = []
        self.errored_message_queue : list = [] # used to store DMs that were unable to be delivered
        self.actively_sending = False
        # self.task = asyncio.create_task(self.process_dm_queues())  # TODO: protect queue from bot crashes -- json?
    
# region Admin config commands
    # CHANNEL
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setNeedsToDMBotChannel(self, ctx, channel: discord.TextChannel):
        """Sets the channel where all members who need to DM the bot will be pinged"""
        await self._save_needs_to_dm_channel(ctx.guild, channel)
        await ctx.reply(DONE)

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getNeedsToDMBotChannel(self, ctx):
        """Gets the channel currently assigned as the transaction channel"""
        try:
            await ctx.reply(f"Needs to DM Bot channel set to: {(await self._get_needs_to_dm_channel(ctx.guild)).mention}")
        except:
            await ctx.reply(":x: Needs to DM Bot Channel not set.")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetNeedsToDMBotChannel(self, ctx):
        await self._save_needs_to_dm_channel(ctx.guild, None)
        await ctx.reply(DONE)

    # ROLE
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setNeedsToDMBotRole(self, ctx, role: discord.Role):
        """Sets the channel where all members who need to DM the bot will be pinged"""
        await self._save_needs_to_dm_role(ctx.guild, role)
        await ctx.reply(DONE)

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getNeedsToDMBotRole(self, ctx):
        """Gets the channel currently assigned as the transaction channel"""
        try:
            await ctx.reply(f"Needs to DM Bot role set to: {(await self._get_needs_to_dm_role(ctx.guild))}")
        except:
            await ctx.reply(":x: Needs to DM Bot role not set")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetNeedsDMToDMBotRole(self, ctx):
        await self._save_needs_to_dm_role(ctx.guild, None)
        await ctx.reply(DONE)

# endregion

# region Commands
    @commands.command(aliases=['dmm'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def dmMember(self, ctx, member: discord.Member, *, message: str):
        """Sends a DM to member by adding them to the message queue"""
        await self.add_to_dm_queue(member, content=message, ctx=ctx)
        await ctx.reply("Done")

    @commands.command(aliases=['dmr'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def dmRole(self, ctx: commands.Context, role: discord.Role, *, message: str):
        """Sends a DM to all members with the specified role by adding them to the message queue"""
        asyncio.create_task(self.add_message_players_to_dm_queue(members=role.members, content=message, ctx=ctx))
        await ctx.reply("All DMs have been queued.")
    
# endregion

# region Listeners
    @commands.Cog.listener('on_member_join')
    async def on_member_join(self, member: discord.Member):
        dm_bot_role: discord.Role = await self._get_needs_to_dm_role(member.guild)
        await member.add_roles(dm_bot_role)

    @commands.Cog.listener('on_message_without_command')
    async def _message_listener(self, message: discord.Message):
        if not isinstance(message.channel, discord.DMChannel):
            return
        # await message.channel.send('hello')
        await self._process_dms_unlocked(message)
    
# endregion

# region Helper functions - open to external cogs
    async def add_message_players_to_dm_queue(self, members: list, content: str, ctx=None):
        for member in members:
            await self.add_to_dm_queue(member, content=content, ctx=ctx)

    async def add_to_dm_queue(self, member: discord.Member, content: str=None, embed: discord.Embed=None, ctx: commands.Context=None, priority: bool=False):
        # Message Data: 
        msg_data = {
          "send_to": member,
          "content": content,
          "embed": embed,
          "request_ctx": ctx
        }
        if priority:
            self.priority_message_queue.append(msg_data)
        else:
            self.message_queue.append(msg_data)
        
        if not self.actively_sending:
            self.actively_sending = True
            await self._process_dm_queues()

    # region Automated Processes
    async def _process_dm_queues(self):
        # Message Data: 
        # {
        #   send_to: <member>,
        #   content: <string>,
        #   embed: <embed | None>,
        #   request_ctx: ctx
        #   priority: <bool>
        # }
        failed_msg_buffer = []
        while self.priority_message_queue or self.message_queue:
            # Grab next message
            if self.priority_message_queue:
                message_data = self.priority_message_queue.pop(0)
            elif self.message_queue:
                message_data = self.message_queue.pop(0)
            
            # Grabs next message
            try:
                recipient: discord.User = message_data['send_to'] # TODO: is there any way to strongly type as member and user (union)?
                content: str = message_data.get("content", None)
                embed: discord.Embed = message_data.get("embed", None)
                req_ctx: commands.Context = message_data.get("request_ctx")
            except Exception as e:
                message_data['exception'] = e
                log.debug(f"Parsing message data failed due to an exception. Message Data: {message_data}")
                failed_msg_buffer.append(message_data)
                req_ctx: commands.Context = message_data.get("request_ctx")
                if req_ctx:
                    await req_ctx.reply(f"Direct Message to {recipient.mention} has failed.")
            
            # Sends next message
            if content or embed:
                try:
                    await recipient.send(content=content, embed=embed)
                    # TODO: add code to remove needs DM role if member has it
                    try:
                        guild: discord.Guild = message_data.get("request_ctx").guild
                        dm_bot_role = await self._get_needs_to_dm_role(guild)
                        member: discord.Member = guild.get_member(recipient.id)
                        if dm_bot_role in member.roles:
                            await member.remove_roles(dm_bot_role)
                    except:
                        pass 
                except Exception as e:
                    message_data['exception'] = e
                    failed_msg_buffer.append(message_data)
                    log.debug(f"DM to recipient \"{recipient.name}{recipient.discriminator}\" failed due to Exception: {e}")
                    
                    # add needs to dm bot where applicable
                    for guild in recipient.mutual_guilds:
                        guild: discord.Guild
                        # 1. apply the "needs to dm bot role"
                        needs_dm_role: discord.Role = await self._get_needs_to_dm_role(guild)
                        
                        if needs_dm_role:
                            recipient_as_member: discord.Member = guild.get_member(recipient.id)
                            recipient_as_member.add_roles(needs_dm_role)
                        
                            # 2. Notify user in channel that they need to DM bot
                            await self._ghost_ping_in_needs_dm_channel(recipient)

                        # 3. Move DM to a "long queue" waiting for DM
                        # self.errored_message_queue.append(message_data) # INSTEAD:
                        # TODO: await self._save_failed_message(member, content, embed)


            await asyncio.sleep(dm_sleep_time)
        
        self.actively_sending = False
        if failed_msg_buffer:
            await self._send_failed_msg_report(failed_msg_buffer)

    async def _send_failed_msg_report(self, failed_msg_buffer):
        # organize reports based on shared channel, ping sender - Feedback

        fmbc = {} # failed_messages_by_channel
        for failed_msg in failed_msg_buffer:
            recipient: discord.Member = failed_msg['send_to']
            ctx: commands.Context = failed_msg['request_ctx']
            channel: discord.TextChannel = ctx.channel
            sender: discord.Member = ctx.author
            jump_url = ctx.message.jump_url

            if channel not in fmbc:
                # Embed List Info
                fmbc[channel] = {}
                fmbc[channel]['recipients'] = []
                fmbc[channel]['senders'] = []
                fmbc[channel]['ctx_links_list'] = []

                # Extra Embed Info
                fmbc[channel]['oldest_msg_req'] = ctx.message.created_at
                fmbc[channel]['all_senders'] = []
            
            # List Data
            fmbc[channel]['recipients'].append(recipient)
            fmbc[channel]['senders'].append(sender)
            fmbc[channel]['ctx_links_list'].append(f"[ctx link]({jump_url})")
            
            # Failed Since <datetime>, ping all senders
            oldest = fmbc[channel]['oldest_msg_req']
            if oldest < ctx.message.created_at:
                oldest = ctx.message.created_at
                fmbc[channel]['oldest_msg_req'] = oldest
            
            if sender not in fmbc[channel]['all_senders']:
                fmbc[channel]['all_senders'].append(sender)
        
        for channel, data in fmbc.items():
            embed = discord.Embed(title="Failed Direct Messages", color=discord.Color.red())

            embed.description = f"Failed DMs since {data['oldest_msg_req']}"
            embed.add_field(name="Recipient", value='\n'.join([r.display_name for r in data['recipients']]), inline=True)
            embed.add_field(name="Sender", value='\n'.join([r.display_name for r in data['senders']]), inline=True)
            embed.add_field(name="Source", value='\n'.join(data.get('ctx_links_list', '--')), inline=True)

            await channel.send(content=f"{' '.join([sender.mention for sender in data['all_senders']])}", embed=embed)

    async def _process_dms_unlocked(self, dm: discord.Message):
        guild: discord.Guild = self.get_main_guild()
        remove_needs_dm_role: discord.Role = self._get_needs_to_dm_role(guild)
        user: discord.User = guild.get_member(dm.author.id)
        # await dm.channel.send("Thank you for messaging the bot")
        
        # Remove role from mutual servers where applicable
        was_locked = False
        for guild in user.mutual_guilds:
            remove_needs_dm_role: discord.Role = self._get_needs_to_dm_role(guild)
            if not remove_needs_dm_role:
                continue
            member: discord.Member = guild.get_member(user.id)
            if needs_to_dm_bot_role in member.roles:
                member.remove_roles(needs_to_dm_bot_role)
                was_locked = True
        
        if not was_locked:
            return None

        # Sends old failed messages
        unlock_msg = (
            f"Hi {member.name}. Thanks for sending us a DM! The bot can now send you DMs! "
            "If you run into any further issues, please open a ModMail!"
        )
        await self.add_to_dm_queue(member, content=unlock_msg)

        failed_messages = await self._pop_failed_user_messages(user)
        
        if not failed_messages:
            return None 
        
        msg = "It looks like you have some old failed DMs. Here's what you've missed..."
        await self.add_message_players_to_dm_queue(member, msg)
        for failed_message in failed_messages:
            await self.add_message_players_to_dm_queue(
                member,
                content=failed_message.get("content"),
                embed=failed_message.get("embed"),
                ctx=failed_message.get("req_ctx")
            )

    # endregion

    # DM member mgmt
    def get_main_guild(self) -> discord.Guild:
        for guild in self.bot.guilds:
            if guild.id == guild_id:
                return guild

    async def _ghost_ping_in_needs_dm_channel(self, member):
        channel = await self._get_needs_to_dm_channel(member.guild)
        ghost_msg : discord.Message = await channel.send(f"{member.mention}")
        await ghost_msg.delete()

# endregion

# region json
    # GET
    async def _get_needs_to_dm_role(self, guild: discord.Guild):
        return guild.get_role(await self.config.guild(guild).DMNotifyRole())

    async def _get_needs_to_dm_channel(self, guild: discord.Guild):
        return guild.get_channel(await self.config.guild(guild).DMNotifyChannel())

    # BOTH
    async def _pop_failed_user_messages(self, user: discord.User):
        failed_messages = await self.config.FailedUserMessages()
        failed_user_messages = failed_messages.get(user)
        if failed_user_messages:
            del failed_messages[user]
            await self._save_failed_user_messages(failed_messages)
            return failed_user_messages

    # SAVE
    async def _save_needs_to_dm_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.guild(guild).DMNotifyRole.set(role.id)

    async def _save_needs_to_dm_channel(self, guild: discord.Guild, channel: discord.TextChannel):
        await self.config.guild(guild).DMNotifyChannel.set(channel.id)
    
    async def _save_failed_user_messages(self, failed_messages: dict):
        await self.config.FailedUserMessages.set(failed_messages)
 
 # endregion
