
from .dmHelper import DMHelper

async def setup(bot):
    await bot.add_cog(DMHelper(bot))