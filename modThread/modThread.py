import discord

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

defaults = {
    "RulesCategory": 1116910594323382372,
    "RulesRole": None,
    "ModsCategory": 1116910419458662490,
    "ModsRole": None,
    "NumbersCategory": 1116910198406266890,
    "NumbersRole": None,
}


class ModThread(commands.Cog):
    """Used to move modmail channels to the correct category for processing by the right team."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567895, force_registration=True)
        self.config.register_guild(**defaults)

# region commands
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def assign(self, ctx, role: str):
        """Assigns the current channel to role and moves channel"""
        if role == 'rules':
            category = await self.getRulesChannel()
            await ctx.channel.move(end=True, category=category, sync_permission=True)
        elif role == 'numbers':
            category = await self.getNumbersChannel()
            await ctx.channel.move(end=True, category=category, sync_permission=True)
        elif role == 'mods':
            category = await self.getModsChannel()
            await ctx.channel.move(end=True, category=category, sync_permission=True)
        else:
            await ctx.send("Whoops, the role must be 'rules', 'numbers', or 'mods'")
            return False
            
        await ctx.send("This ticket has been assigned to {0}".format(role))
        return True

    ### Rules Channel
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setRulesChannel(self, ctx, rules_channel: discord.CategoryChannel):
        """Sets the channel where all transaction messages will be posted"""
        await self._save_rules_channel(ctx, rules_channel.id)
        await ctx.send("Done")

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def getRulesChannel(self, ctx):
        """Gets the channel currently assigned as the transaction channel"""
        try:
            await ctx.send("Rules Thread channel set to: {0}".format((await self._rules_channel(ctx)).mention))
        except:
            await ctx.send(":x: Rules Thread channel not set")

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetRulesChannel(self, ctx):
        """Unsets the rules channel. Thread will not be moved if no rules channel is set"""
        await self._save_rules_channel(ctx, None)
        await ctx.send("Done")
    ### End Rules Channel

    ### Numbers Channel
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setNumbersChannel(self, ctx, numbers_channel: discord.CategoryChannel):
        """Sets the channel where all transaction messages will be posted"""
        await self._save_numbers_channel(ctx, numbers_channel.id)
        await ctx.send("Done")

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def getNumbersChannel(self, ctx):
        """Gets the channel currently assigned as the transaction channel"""
        try:
            await ctx.send("Numbers Thread channel set to: {0}".format((await self._numbers_channel(ctx)).mention))
        except:
            await ctx.send(":x: Numbers Thread channel not set")

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetNumbersChannel(self, ctx):
        """Unsets the numbers channel. Thread will not be moved if no numbers channel is set"""
        await self._save_numbers_channel(ctx, None)
        await ctx.send("Done")
    ### End Numbers Channel

    ### Mod Channel
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setModsChannel(self, ctx, mods_channel: discord.CategoryChannel):
        """Sets the channel where all transaction messages will be posted"""
        await self._save_mods_channel(ctx, mods_channel.id)
        await ctx.send("Done")

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def getModsChannel(self, ctx):
        """Gets the channel currently assigned as the transaction channel"""
        try:
            await ctx.send("Mod Thread channel set to: {0}".format((await self._mods_channel(ctx)).mention))
        except:
            await ctx.send(":x: Mod Thread channel not set")

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetModsChannel(self, ctx):
        """Unsets the mod channel. Thread will not be moved if no mod channel is set"""
        await self._save_mods_channel(ctx, None)
        await ctx.send("Done")
    ### End Mod Channel

# endregion

# region helper functions
    # async def get_assign_embed(self, ctx: commands.Context, player: discord.Member, gm_name, franchise_name, team_name, tier):
    #     assign_message = await self._get_assign_message(ctx.guild)
    #     if not assign_message:
    #         return None

    #     assign_message = assign_message.format(
    #         player=player,
    #         franchise=franchise_name,
    #         gm=gm_name,
    #         team=team_name,
    #         tier=tier,
    #         guild=ctx.guild.name
    #     )
    #     embed = discord.Embed(
    #         title=f"Message from {ctx.guild.name}",
    #         description=cut_message,
    #         color=discord.Color.red()
    #     )
        
    #     try:
    #         embed.set_thumbnail(url=ctx.guild.icon.url)
    #     except:
    #         pass
        
    #     return embed
# endregion

# region json db
    async def _rules_channel(self, ctx):
        return ctx.guild.get_channel(await self.config.guild(ctx.guild).RulesChannel())

    async def _save_rules_channel(self, ctx, rules_channel):
        await self.config.guild(ctx.guild).RulesChannel.set(rules_channel)
    
    async def _numbers_channel(self, ctx):
        return ctx.guild.get_channel(await self.config.guild(ctx.guild).NumbersChannel())

    async def _save_numbers_channel(self, ctx, numbers_channel):
        await self.config.guild(ctx.guild).NumbersChannel.set(numbers_channel)

    async def _mods_channel(self, ctx):
        return ctx.guild.get_channel(await self.config.guild(ctx.guild).ModsChannel())

    async def _save_mods_channel(self, ctx, mods_channel):
        await self.config.guild(ctx.guild).ModsChannel.set(mods_channel)
# endregion
