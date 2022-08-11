
import discord
from redbot.core import commands, Config, checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

from datetime import datetime
import asyncio
import logging

log : logging.Logger = logging.getLogger("red.RSCBot.dmHelper")

dm_sleep_time = 0.5 # seconds, right?
verify_timeout = 30

# role for "Needs to DM Bot"
needs_to_dm_bot_role = 1007395860151271455
channel_to_notify = 978653830608744499 # #development-committee

DONE = "Done"

class DMHelper(commands.Cog):
    """Controls Bot-to-member Direct Messages (DMs) with code to prevent rate limiting."""

    def __init__(self, bot):
        self.bot = bot
        self.message_queue : list = []
        self.priority_message_queue : list = []
        self.errored_message_queue : list = [] # used to store DMs that were unable to be delivered
        self.actively_sending = False
        # self.task = asyncio.create_task(self.process_dm_queues())  # TODO: protect queue from bot crashes -- json?
    
    @commands.Cog.listener('on_message')
    async def _message_listener(self, message: Discord.Message)
        if message.channel.id == message.author.dm_channel.id:
            # 0. ignore pre-existing commands?
            # 1. Remove the role from all RSC guilds?
            # HELP NULL
            # 2. Say hello
            await message.author.send('Hello!')

            # 3. Move private messages from errored_message_queue into message_queue
            for message_data in self.errored_message_queue:
                if message_data.send_to.id == message.author.id:
                    self.message_queue.append(message_data)
                    self.errored_message_queue.remove(message_data)

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
        await ctx.reply("All DMs have been queued.") # TODO: move after, may need to add async.to_thread
        
    # Helper functions - open to external cogs
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

    # Automated Processes
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
            if self.priority_message_queue:
                message_data = self.priority_message_queue.pop(0)
            elif self.message_queue:
                message_data = self.message_queue.pop(0)
            
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
            
            if content or embed:
                try:
                    await recipient.send(content=content, embed=embed)
                except Exception as e:
                    message_data['exception'] = e
                    failed_msg_buffer.append(message_data)
                    log.debug(f"DM to recipient \"{recipient.name}\" failed due to Exception: {e}")
                    
                    # 1. apply the "needs to dm bot role 1007395860151271455"
                    try:
                        await message_data.send_to.add_roles(role)
                    except:
                        pass
                    
                    # 2. Notify user in channel that they need to DM bot
                    channel = self.bot.get_channel(channel_to_notify)
                    await channel.send(f"{message_data.send_to.mention}: I have a message for you! Please DM me to receive it.")

                    # 3. Move DM to a "long queue" waiting for DM
                    self.errored_message_queue.append(message_data)


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
