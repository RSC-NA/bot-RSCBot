from .transactions import Transactions

async def setup(bot):
    await bot.add_cog(Transactions(bot))
