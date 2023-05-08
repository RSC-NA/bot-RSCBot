from .prefixManager import PrefixManager

async def setup(bot):
    await bot.add_cog(PrefixManager())