from .bulkRoleManager import BulkRoleManager

async def setup(bot):
    await bot.add_cog(BulkRoleManager(bot))