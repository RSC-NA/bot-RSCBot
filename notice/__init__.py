from .notice import Notice


async def setup(bot):
    await bot.add_cog(Notice())
