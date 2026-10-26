from .cogWatch import CogWatch


async def setup(bot):
    await bot.add_cog(CogWatch(bot))
