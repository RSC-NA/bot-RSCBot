import logging
import sys
import traceback
from types import FrameType

import discord
from discord.ext.commands.bot import BotBase
from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import box

log = logging.getLogger("red.RSCBot.cogWatch")

STACK_LIMIT = 12
CONTENT_LIMIT = 200

defaults = {
    "AlertChannel": None,
}


class CogWatch(commands.Cog):
    """Logs who or what unloads cogs, and optionally alerts a channel."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567898, force_registration=True
        )
        self.config.register_global(**defaults)

        # Every unload path (core commands, Downloader, RPC, other cogs) goes
        # through bot.unload_extension, so wrap it on the instance.
        self._original_unload = bot.unload_extension
        bot.unload_extension = self._watched_unload

    def cog_unload(self):
        """Restore unload_extension, unless something else has wrapped it since."""
        if self.bot.unload_extension == self._watched_unload:
            self.bot.unload_extension = self._original_unload

    # Commands

    @commands.group(name="cogwatch")
    @checks.is_owner()
    async def _cog_watch(self, ctx: commands.Context) -> None:
        """Configure cog unload alerts."""

    @_cog_watch.command(name="channel")
    async def _cog_watch_channel(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None
    ) -> None:
        """Set the channel for unload alerts. Leave blank to turn alerts off."""
        if channel is None:
            await self.config.AlertChannel.set(None)
            await ctx.send("Unload alerts turned off. Unloads are still logged.")
            return
        await self.config.AlertChannel.set(channel.id)
        await ctx.send(f"Unload alerts will be sent to {channel.mention}.")

    # Unload tracking

    async def _watched_unload(self, name: str, *, package: str | None = None) -> None:
        # Inspect the call stack before unloading; the caller's frames are live here.
        frame = sys._getframe(1)
        ctx, shutting_down = self._find_caller(frame)
        stack = "".join(traceback.format_stack(frame, limit=STACK_LIMIT))

        await self._original_unload(name, package=package)

        # Bot.close() unloads every extension on shutdown; that isn't worth reporting.
        if shutting_down:
            return

        if ctx:
            where = f"#{ctx.channel} ({ctx.guild})" if ctx.guild else "DMs"
            content = ctx.message.content[:CONTENT_LIMIT]
            log.warning(
                'Cog %s unloaded by %s (%s) in %s: "%s"',
                name,
                ctx.author,
                ctx.author.id,
                where,
                content,
            )
            await self._alert(
                f"`{name}` was unloaded by {ctx.author.mention} ({ctx.author}) "
                f"in {where}:\n{box(content)}"
            )
        else:
            log.warning("Cog %s unloaded outside a command:\n%s", name, stack)
            await self._alert(
                f"`{name}` was unloaded outside a command. Call stack:\n"
                f"{box(stack[-1800:], lang='py')}"
            )

    @staticmethod
    def _find_caller(frame: FrameType | None) -> tuple[commands.Context | None, bool]:
        """Walk the call stack for the invoking command's ctx, or a shutdown."""
        while frame:
            if frame.f_code is BotBase.close.__code__:
                return None, True
            ctx = frame.f_locals.get("ctx")
            if isinstance(ctx, commands.Context):
                return ctx, False
            frame = frame.f_back
        return None, False

    async def _alert(self, message: str) -> None:
        channel_id = await self.config.AlertChannel()
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.warning("Unload alert channel %s not found.", channel_id)
            return
        try:
            await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Failed to send unload alert to %s.", channel_id)
