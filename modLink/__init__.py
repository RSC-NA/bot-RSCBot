from .modLink import ModeratorLink

async def setup(bot):
    await bot.add_cog(ModeratorLink(bot))
