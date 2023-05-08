from .match import Match

async def setup(bot):
    await bot.add_cog(Match(bot))