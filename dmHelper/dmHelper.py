
import discord
from redbot.core import Config
from redbot.core import commands
from redbot.core import checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

import asyncio

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
        self.failed_messages = []
        self.actively_sending = False
        # self.task = asyncio.create_task(self.process_dm_queues())  # TODO: protect queue from bot crashes -- json?
    
    @commands.command(aliases=['dmm'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def dmMember(self, ctx, member: discord.Member, *, message: str):
        """Sends a DM to member by adding them to the message queue"""
        await self.send_dm(member, content=message, ctx=ctx)
        await ctx.reply("Done")

    @commands.command(aliases=['dmr'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def dmRole(self, ctx, role: discord.Role, *, message: str):
        """Sends a DM to all members with the specified role by adding them to the message queue"""
        await ctx.reply("Queueing Messages.") # TODO: move after, may need to add async.to_thread()
        for member in role.members:
            await self.send_dm(member, content=message, ctx=ctx)
        

    async def process_dm_queues(self):
        # Message Data: 
        # {
        #   send_to: <member>,
        #   content: <string>,
        #   embed: <embed | None>,
        #   request_ctx: ctx
        #   priority: <bool>
        # }
        while self.priority_message_queue or self.message_queue:
            if self.priority_message_queue:
                message_data = self.priority_message_queue.pop(0)
            elif self.message_queue:
                message_data = self.message_queue.pop(0)
            
            try:
                recepient = message_data['send_to']
                content = message_data.get("content", None)
                embed = message_data.get("embed", None)
            except:
                self.failed_messages.append(message_data)
                req_ctx = message_data.get("request_ctx")
                if req_ctx:
                    await req_ctx.reply(f"Direct Message to {recepient.mention} has failed.")
            
            if content or embed:
                await recepient.send(content=content, embed=embed)

            asyncio.sleep(dm_sleep_time)
        
        self.actively_sending = False

    async def send_dm(self, member: discord.Member, content: str=None, embed: discord.Embed=None, ctx: commands.Context=None, priority: bool=False):
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
