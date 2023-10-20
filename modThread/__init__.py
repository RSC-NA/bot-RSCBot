from .modThread import ModThread

async def setup(bot):
    await bot.add_cog(ModThread(bot))
