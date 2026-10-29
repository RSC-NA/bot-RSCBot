import logging
import sys
import traceback
from collections import Counter
from datetime import UTC, datetime
from types import FrameType

import discord
from discord.ext import tasks
from discord.ext.commands.bot import BotBase
from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import box, pagify

log = logging.getLogger("red.RSCBot.cogWatch")

STACK_LIMIT = 12
CONTENT_LIMIT = 200
FLUSH_MINUTES = 10
DM_KEY = "dm"

defaults = {
    "AlertChannel": None,
    # {guild_id or "dm": {cog_name: {command_name: count}}}
    "CommandUsage": {},
    "UsageSince": None,
}


class CogWatch(commands.Cog):
    """Logs who or what unloads cogs, and counts command usage per guild."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567898, force_registration=True
        )
        self.config.register_global(**defaults)

        # Usage counts are kept in memory and written to disk every FLUSH_MINUTES,
        # so a busy channel doesn't rewrite the config file on every command.
        self._pending_usage: Counter[tuple[str, str, str]] = Counter()

        # Every unload path (core commands, Downloader, RPC, other cogs) goes
        # through bot.unload_extension, so wrap it on the instance.
        self._original_unload = bot.unload_extension
        bot.unload_extension = self._watched_unload

    async def cog_load(self) -> None:
        if await self.config.UsageSince() is None:
            await self.config.UsageSince.set(datetime.now(UTC).isoformat())
        self._flush_loop.start()

    async def cog_unload(self) -> None:
        """Restore unload_extension, unless something else has wrapped it since."""
        if self.bot.unload_extension == self._watched_unload:
            self.bot.unload_extension = self._original_unload
        self._flush_loop.cancel()
        await self._flush_usage()

    # Commands

    @commands.group(name="cogwatch")
    @checks.is_owner()
    async def _cog_watch(self, ctx: commands.Context) -> None:
        """Configure cog unload alerts and view command usage."""

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

    @_cog_watch.command(name="usage")
    async def _cog_watch_usage(self, ctx: commands.Context) -> None:
        """Show how often each command has been used, by cog and guild."""
        await self._flush_usage()
        usage = await self.config.CommandUsage()
        since = await self.config.UsageSince()
        await ctx.send_interactive(
            pagify(self._format_usage(usage, since), page_length=1900), box_lang=""
        )

    @_cog_watch.command(name="resetusage")
    async def _cog_watch_reset_usage(self, ctx: commands.Context) -> None:
        """Clear all command usage counts and start counting again from now."""
        self._pending_usage.clear()
        await self.config.CommandUsage.set({})
        await self.config.UsageSince.set(datetime.now(UTC).isoformat())
        await ctx.send("Command usage counts cleared.")

    # Usage tracking

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        if not ctx.command:
            return
        guild = str(ctx.guild.id) if ctx.guild else DM_KEY
        cog = ctx.command.cog_name or "No Cog"
        self._pending_usage[(guild, cog, ctx.command.qualified_name)] += 1

    @tasks.loop(minutes=FLUSH_MINUTES)
    async def _flush_loop(self) -> None:
        await self._flush_usage()

    async def _flush_usage(self) -> None:
        if not self._pending_usage:
            return
        pending, self._pending_usage = self._pending_usage, Counter()
        try:
            async with self.config.CommandUsage() as usage:
                for (guild, cog, command), count in pending.items():
                    commands_used = usage.setdefault(guild, {}).setdefault(cog, {})
                    commands_used[command] = commands_used.get(command, 0) + count
        except Exception:
            log.exception("Failed to save command usage; will retry next flush.")
            self._pending_usage.update(pending)

    def _guild_name(self, guild_key: str) -> str:
        if guild_key == DM_KEY:
            return "DMs"
        guild = self.bot.get_guild(int(guild_key))
        return guild.name if guild else f"Unknown guild {guild_key}"

    def _format_usage(self, usage: dict, since: str | None) -> str:
        # Regroup as {cog: {command: {guild_key: count}}} for the report
        by_cog: dict[str, dict[str, Counter[str]]] = {}
        for guild_key, cogs in usage.items():
            for cog, commands_used in cogs.items():
                for command, count in commands_used.items():
                    by_cog.setdefault(cog, {}).setdefault(command, Counter())[
                        guild_key
                    ] += count

        started = since[:16].replace("T", " ") + " UTC" if since else "unknown"
        lines = [f"Command usage since {started}", ""]

        def total(guilds: Counter[str]) -> int:
            return sum(guilds.values())

        cog_totals = {
            cog: sum(total(g) for g in cmds.values()) for cog, cmds in by_cog.items()
        }
        for cog in sorted(by_cog, key=lambda c: cog_totals[c], reverse=True):
            lines.append(f"{cog} ({cog_totals[cog]})")
            cmds = by_cog[cog]
            for command in sorted(cmds, key=lambda c: total(cmds[c]), reverse=True):
                per_guild = ", ".join(
                    f"{self._guild_name(g)} {n}" for g, n in cmds[command].most_common()
                )
                lines.append(f"  {command:<28} {total(cmds[command]):>6}  {per_guild}")
            lines.append("")

        unused = sorted(
            name
            for name, cog in self.bot.cogs.items()
            if name not in by_cog and cog.get_commands()
        )
        if unused:
            lines.append("Loaded cogs with no command usage: " + ", ".join(unused))
        if not by_cog:
            lines.append("No commands recorded yet.")
        return "\n".join(lines)

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
