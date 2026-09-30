import discord


class TimeoutEmbed(discord.Embed):
    """Timeout Embed for Views"""

    def __init__(self, author: discord.Member | discord.User, **kwargs):
        super().__init__(
            title="Timed out",
            description=f"{author.mention} Sorry, you didn't respond quick enough. Please try again.",
            color=discord.Colour.orange(),
            **kwargs,
        )
