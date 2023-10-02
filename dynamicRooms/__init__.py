from .dynamicRooms import DynamicRooms


async def setup(bot):
    await bot.add_cog(DynamicRooms(bot))
