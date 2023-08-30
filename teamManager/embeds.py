import discord

from typing import Union

class ErrorEmbed(discord.Embed):
    """ Generic Error Embed """
    def __init__(self, **kwargs):
        super().__init__(
            title = "Error",
            color = discord.Color.red(),
            **kwargs
        )


class TimeoutEmbed(discord.Embed):
    """ Timeout Embed for Views """
    def __init__(self, author: Union[discord.Member, discord.User], **kwargs):
        super().__init__(
            title = "Timed out",
            description = f"{author.mention} Sorry, you didn't respond quick enough. Please try again.",
            color = discord.Colour.orange(),
            **kwargs
        )