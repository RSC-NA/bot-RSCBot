
from .bcConfig import bcConfig
from .bcManager import BCManager

def setup(bot):
    bot.add_cog(BCManager(bot))