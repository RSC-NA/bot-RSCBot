from .combineRooms import CombineRooms

async def setup(bot):
    await bot.add_cog(CombineRooms(bot))
