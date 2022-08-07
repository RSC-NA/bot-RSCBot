
import discord
from redbot.core import Config
from redbot.core import commands
from redbot.core import checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

from datetime import datetime
import asyncio
import logging

log : logging.Logger = logging.getLogger("red.RSCBot.dmHelper")

defaults = {
    
}

dm_sleep_time = 0.5 # seconds, right?
verify_timeout = 30
DONE = "Done"

class DMHelper(commands.Cog):
    """Controls Bot-to-member Direct Messages (DMs) with code to prevent rate limiting."""

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=1234567893, force_registration=True)
        self.config.register_guild(**defaults)

        self.bot = bot
        self.message_queue : list = []
        self.priority_message_queue : list = []
        self.actively_sending = False
        # self.task = asyncio.create_task(self.process_dm_queues())  # TODO: protect queue from bot crashes -- json?
    
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
        
        
    async def add_message_players_to_dm_queue(self, members: list, content: str, ctx=None):
        for member in members:
            await self.add_to_dm_queue(member, content=content, ctx=ctx)

    async def process_dm_queues(self):
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
                recepient: discord.User = message_data['send_to'] # TODO: is there any way to strongly type as member and user (union)?
                content: str = message_data.get("content", None)
                embed: discord.Embed = message_data.get("embed", None)
                req_ctx: commands.Context = message_data.get("request_ctx")
            except Exception as e:
                message_data['exception'] = e
                log.debug(f"Parsing message data failed due to an exception. Message Data: {message_data}")
                failed_msg_buffer.append(message_data)
                req_ctx: commands.Context = message_data.get("request_ctx")
                if req_ctx:
                    await req_ctx.reply(f"Direct Message to {recepient.mention} has failed.")
            
            if content or embed:
                try:
                    await recepient.send(content=content, embed=embed)
                except Exception as e:
                    message_data['exception'] = e
                    failed_msg_buffer.append(message_data)
                    log.debug(f"DM to recepient \"{recepient.name}\" failed due to Exception: {e}")

            await asyncio.sleep(dm_sleep_time)
        
        self.actively_sending = False
        if failed_msg_buffer:
            await self.send_failed_msg_report(failed_msg_buffer)

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
            await self.process_dm_queues()

    async def send_failed_msg_report(self, failed_msg_buffer):
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
            embed.add_field(name="Receipient", value='\n'.join([r.display_name for r in data['recipients']]), inline=True)
            embed.add_field(name="Sender", value='\n'.join([r.display_name for r in data['senders']]), inline=True)
            embed.add_field(name="Source", value='\n'.join(data.get('ctx_links_list', '--')), inline=True)

            await channel.send(content=f"{' '.join([sender.mention for sender in data['all_senders']])}", embed=embed)
