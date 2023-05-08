
from .bcManager import BCManager

async def setup(bot):
    await bot.add_cog(BCManager(bot))
