from .mmrFetcher import MMRFetcher


async def setup(bot):
    await bot.add_cog(MMRFetcher())
