from .teamManager import TeamManager

async def setup(bot):
    await bot.add_cog(TeamManager(bot))
