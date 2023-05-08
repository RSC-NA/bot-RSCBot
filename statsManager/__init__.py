from .statsManager import StatsManager

async def setup(bot):
    await bot.add_cog(StatsManager(bot))