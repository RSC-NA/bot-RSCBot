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
        self.config = Config.get_conf(self, identifier=12345678921337, force_registration=True)
        self.config.register_guild(**defaults)

# region commands
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def assign(self, ctx, role: str):
        """Assigns the current channel to role and moves channel"""
        mentionRole = None 
        if role == 'rules':
            category = await self._rules_category(ctx)
            mentionRole = await self._rules_role(ctx)
            await ctx.channel.move(end=True, category=category, sync_permissions=True)
        elif role == 'numbers':
            category = await self._numbers_category(ctx)
            mentionRole = await self._numbers_role(ctx)
            await ctx.channel.move(end=True, category=category, sync_permissions=True)
        elif role == 'mods':
            category = await self._mods_category(ctx)
            mentionRole = await self._mods_role(ctx)
            await ctx.channel.move(end=True, category=category, sync_permissions=True)
        else:
            await ctx.send("Whoops, the role must be 'rules', 'numbers', or 'mods'")
            return False

        if mentionRole:
            await ctx.send("This ticket has been assigned to {0}".format(mentionRole.mention))
        else: 
            await ctx.send("This ticket has been assigned to {0}".format(role))
        return True

    ### Rules Category
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setRulesRole(self, ctx, rules_role: discord.Role):
        await self.__save_rules_role(ctx, rules_role.id)
        await ctx.send('Done')

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setRulesCategory(self, ctx, rules_category: discord.CategoryChannel):
        """Sets the category where all rules threads will be moved"""
        await self._save_rules_category(ctx, rules_category.id)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getRulesCategory(self, ctx):
        """Gets the category currently assigned as the rules category"""
        try:
            await ctx.send("Rules Thread category set to: {0}".format((await self._rules_category(ctx)).mention))
        except:
            await ctx.send(":x: Rules Thread category not set")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetRulesCategory(self, ctx):
        """Unsets the rules category. Thread will not be moved if no rules category is set"""
        await self._save_rules_category(ctx, None)
        await ctx.send("Done")
    ### End Rules Category

    ### Numbers Category
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setNumbersRole(self, ctx, numbers_role: discord.Role):
        await self.__save_numbers_role(ctx, numbers_role.id)
        await ctx.send('Done')

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setNumbersCategory(self, ctx, numbers_category: discord.CategoryChannel):
        """Sets the category where all numbers threads will be moved"""
        await self._save_numbers_category(ctx, numbers_category.id)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getNumbersCategory(self, ctx):
        """Gets the category currently assigned as the numbers category"""
        try:
            await ctx.send("Numbers Thread category set to: {0}".format((await self._numbers_category(ctx)).mention))
        except:
            await ctx.send(":x: Numbers Thread category not set")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetNumbersCategory(self, ctx):
        """Unsets the numbers category. Thread will not be moved if no numbers category is set"""
        await self._save_numbers_category(ctx, None)
        await ctx.send("Done")
    ### End Numbers Category

    ### Mods Category
    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setModsRole(self, ctx, mods_role: discord.Role):
        await self.__save_numbers_role(ctx, mods_role.id)
        await ctx.send('Done')

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setModsCategory(self, ctx, mods_category: discord.CategoryChannel):
        """Sets the category where all transaction messages will be posted"""
        await self._save_mods_category(ctx, mods_category.id)
        await ctx.send("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getModsCategory(self, ctx):
        """Gets the category currently assigned as the transaction category"""
        try:
            await ctx.send("Mod Thread category set to: {0}".format((await self._mods_category(ctx)).mention))
        except:
            await ctx.send(":x: Mod Thread category not set")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def unsetModsCategory(self, ctx):
        """Unsets the mod category. Thread will not be moved if no mod category is set"""
        await self._save_mods_category(ctx, None)
        await ctx.send("Done")
    ### End Mod Category

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
    async def _rules_category(self, ctx):
        return ctx.guild.get_channel(await self.config.guild(ctx.guild).RulesCategory())

    async def _save_rules_category(self, ctx, rules_category):
        await self.config.guild(ctx.guild).RulesCategory.set(rules_category)
    
    async def _numbers_category(self, ctx):
        return ctx.guild.get_channel(await self.config.guild(ctx.guild).NumbersCategory())

    async def _save_numbers_category(self, ctx, numbers_category):
        await self.config.guild(ctx.guild).NumbersCategory.set(numbers_category)

    async def _mods_category(self, ctx):
        return ctx.guild.get_channel(await self.config.guild(ctx.guild).ModsCategory())

    async def _save_mods_category(self, ctx, mods_category):
        await self.config.guild(ctx.guild).ModsCategory.set(mods_category)

    async def _save_rules_role(self, ctx, rules_role):
        await self.config.guild(ctx.guild).RulesRole.set(rules_role)
    
    async def _rules_role(self, ctx):
        return ctx.guild.get_role(await self.config.guild(ctx.guild).RulesRole())

    async def _save_numbers_role(self, ctx, numbers_role):
        await self.config.guild(ctx.guild).NumbersRole.set(numbers_role)
    
    async def _numbers_role(self, ctx):
        return ctx.guild.get_role(await self.config.guild(ctx.guild).NumbersRole())

    async def _save_mods_role(self, ctx, mods_role):
        await self.config.guild(ctx.guild).ModsRole.set(mods_role)

    async def _mods_role(self, ctx):
        return ctx.guild.get_role(await self.config.guild(ctx.guild).ModsRole())

# endregion
