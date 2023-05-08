from .faCheckIn import FaCheckIn

async def setup(bot):
    await bot.add_cog(FaCheckIn(bot))
