import discord
import logging

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

from faCheckIn.views import AuthorOnlyView, ConfirmButton, DeclineButton

from typing import Optional, NoReturn

log = logging.getLogger("red.RSCBot.faCheckIn")

defaults = {"CheckIns": {}}
verify_timeout = 30


class FaCheckIn(commands.Cog):
    def __init__(self, bot):
        self.config = Config.get_conf(
            self, identifier=1234567894, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.team_manager_cog = bot.get_cog("TeamManager")
        self.match_cog = bot.get_cog("Match")
        self.bot = bot

    @commands.guild_only()
    @commands.command(aliases=["ci"])
    async def checkIn(self, ctx):
        user = ctx.message.author

        match_day = await self._get_match_day(ctx)
        if not match_day:
            log.warning(f"Unable to fetch current match day for guild: {ctx.guild}")
            await ctx.send(":x: Unable to fetch current match day.")
            return

        tier = await self._find_tier_from_fa_role(ctx, user)

        # await ctx.message.delete()

        if tier is not None:
            tier_data = await self._tier_data(ctx, match_day, tier)
            if user.id not in tier_data:
                await self._send_check_in_message(ctx, user, match_day, tier)
            else:
                await ctx.send(
                    "You've already checked in. If you want to check out, use the `{0}checkOut` command.".format(
                        ctx.prefix
                    )
                )
        else:
            await ctx.send(
                "Only free agents are allowed to check in. If you are a free agent and are unable to check in please message an admin."
            )

    @commands.guild_only()
    @commands.command(aliases=["co"])
    async def checkOut(self, ctx):
        user = ctx.message.author

        match_day = await self._get_match_day(ctx)
        if not match_day:
            log.warning(f"Unable to fetch current match day for guild: {ctx.guild}")
            await ctx.send(":x: Unable to fetch current match day.")
            return

        tier = await self._find_tier_from_fa_role(ctx, user)
        if tier is None:
            tier = await self.team_manager_cog.get_current_tier_role(ctx, user)

        await ctx.message.delete()

        if tier is not None:
            tier_data = await self._tier_data(ctx, match_day, tier)
            if user.id in tier_data:
                await self._send_check_out_message(ctx, user, match_day, tier)
            else:
                await ctx.send(
                    "You aren't currently checked in. If you want to check in, use the `{0}checkIn` command.".format(
                        ctx.prefix
                    )
                )
        else:
            await ctx.send(
                "Your tier could not be determined. If you are in the league please contact an admin for help."
            )

    @commands.guild_only()
    @commands.command(aliases=["ca"])
    async def checkAvailability(self, ctx, tier_name: str, match_day: str = None):
        """Check availability for Free Agents in a specific tier"""
        if not match_day:
            match_day = await self._get_match_day(ctx)
            if not match_day:
                log.warning(f"Unable to fetch current match day for guild: {ctx.guild}")
                await ctx.send(":x: Unable to fetch current match day.")
                return

        tier = await self.team_manager_cog._match_tier_name(ctx, tier_name)
        if tier is None:
            await ctx.send("No tier with name: `{0}`".format(tier_name))
            return

        tier_list = await self._tier_data(ctx, match_day, tier)
        perm_fa_role = self.team_manager_cog._find_role_by_name(
            ctx, self.team_manager_cog.PERM_FA_ROLE
        )

        message = ""
        for user in tier_list:
            member = ctx.guild.get_member(user)
            if (
                member is not None
                and await self._find_tier_from_fa_role(ctx, member) is not None
            ):
                message += "\n{0}".format(member.display_name)
                if perm_fa_role is not None and perm_fa_role in member.roles:
                    message += " (Permanent FA)"

        color = discord.Colour.blue()
        for role in ctx.guild.roles:
            if role.name.lower() == tier_name.lower():
                color = role.color
        embed = discord.Embed(
            title="Availability for {0} tier on match day {1}:".format(tier, match_day),
            color=color,
            description=message,
        )
        embed.set_thumbnail(url=ctx.guild.icon.url)

        await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearAvailability(self, ctx, tier: str = None, match_day: str = None):
        """Clear Free Agent availability in a tier"""
        if not match_day:
            match_day = await self._get_match_day(ctx)
            if not match_day:
                log.warning(f"Unable to fetch current match day for guild: {ctx.guild}")
                await ctx.send(":x: Unable to fetch current match day.")
                return

        if tier is None:
            await self._save_match_data(ctx, match_day, {})
        else:
            await self._save_tier_data(ctx, match_day, tier, [])
        await ctx.send("Done.")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearAllAvailability(self, ctx):
        await self._save_check_ins(ctx, {})
        await ctx.send("Done.")

    async def _get_match_day(self, ctx) -> Optional[str]:
        """Returns the current match day for a specific guild."""
        if not self.match_cog:
            self.match_cog = self.bot.get_cog("Match")

        try:
            return await self.match_cog._match_day(ctx)
        except Exception as exc:
            log.error(
                f"Error getting match day. Guild: {ctx.guild} - {type(exc)} {exc}"
            )
            return None

    async def _send_check_in_message(self, ctx, user, match_day, tier) -> NoReturn:
        embed = discord.Embed(
            title="Check In",
            description="By checking in you are letting GMs know that you are available to play on the following match day in the following tier.",
            colour=discord.Colour.blue(),
        )
        embed.add_field(name="Match Day", value=match_day, inline=True)
        embed.add_field(name="Tier", value=tier, inline=True)

        success = discord.Embed(
            title="Checked In",
            description=f"{user.mention} Thank you for checking in! GMs will now be able to see that you're available.",
            colour=discord.Colour.green(),
        )

        fail = discord.Embed(
            title="Unlucky...",
            description=f"{user.mention} Not checked in. If you wish to check in, use the command again.",
            colour=discord.Colour.red(),
        )

        async def check_in(inter: discord.Interaction):
            await self._register_user(ctx, user, match_day, tier)
            await inter.response.edit_message(embed=success, view=None)
            checkView.stop()

        async def quit(inter: discord.Interaction):
            await inter.response.edit_message(embed=fail, view=None)
            checkView.stop()

        confirmed = ConfirmButton(callback=check_in)
        declined = DeclineButton(callback=quit)

        checkView: discord.ui.View = AuthorOnlyView(user)
        checkView.add_item(confirmed)
        checkView.add_item(declined)

        checkView.message = await ctx.send(embed=embed, view=checkView)

    async def _send_check_out_message(self, ctx, user, match_day, tier) -> NoReturn:
        embed = discord.Embed(
            title="Check Out",
            description="You are currently checked in as available for the following match day and tier.\n\nDo you wish to take yourself off the availability list?",
            colour=discord.Colour.blue(),
        )
        embed.add_field(name="Match Day", value=match_day, inline=True)
        embed.add_field(name="Tier", value=tier, inline=True)

        success = discord.Embed(
            title="Checked Out",
            description=f"{user.mention} You have been removed from the list. Thank you for updating your availability!",
            colour=discord.Colour.green(),
        )

        fail = discord.Embed(
            title="Great news!",
            description=f"{user.mention} You are still checked in. If you wish to check out, use the command again.",
            colour=discord.Colour.red(),
        )

        async def check_out(inter: discord.Interaction):
            await self._unregister_user(ctx, user, match_day, tier)
            await inter.response.edit_message(embed=success, view=None)
            checkView.stop()

        async def quit(inter: discord.Interaction):
            await inter.response.edit_message(embed=fail, view=None)
            checkView.stop()

        confirmed = ConfirmButton(callback=check_out)
        declined = DeclineButton(callback=quit)

        checkView = AuthorOnlyView(user, timeout=5)
        checkView.add_item(confirmed)
        checkView.add_item(declined)

        checkView.message = await ctx.send(embed=embed, view=checkView)

    async def _register_user(self, ctx, user, match_day, tier):
        tier_list = await self._tier_data(ctx, match_day, tier)
        tier_list.append(user.id)
        await self._save_tier_data(ctx, match_day, tier, tier_list)

    async def _unregister_user(self, ctx, user, match_day, tier):
        tier_list = await self._tier_data(ctx, match_day, tier)
        tier_list.remove(user.id)
        await self._save_tier_data(ctx, match_day, tier, tier_list)

    async def _find_tier_from_fa_role(self, ctx, user: discord.Member):
        tiers = await self.team_manager_cog.tiers(ctx)
        for tier in tiers:
            fa_role = self.team_manager_cog._find_role_by_name(ctx, tier + "FA")
            if fa_role in user.roles:
                return tier
        return None

    async def _save_tier_data(self, ctx, match_day, tier, tier_data):
        check_ins = await self._check_ins(ctx)
        match_data = check_ins.setdefault(match_day, {})
        match_data[tier] = tier_data
        await self._save_check_ins(ctx, check_ins)

    async def _save_match_data(self, ctx, match_day, match_data):
        check_ins = await self._check_ins(ctx)
        check_ins[match_day] = match_data
        await self._save_check_ins(ctx, check_ins)

    async def _tier_data(self, ctx, match_day, tier):
        match_data = await self._match_data(ctx, match_day)
        tier_data = match_data.setdefault(tier, [])
        return tier_data

    async def _match_data(self, ctx, match_day):
        check_ins = await self._check_ins(ctx)
        match_data = check_ins.setdefault(match_day, {})
        return match_data

    async def _check_ins(self, ctx):
        return await self.config.guild(ctx.guild).CheckIns()

    async def _save_check_ins(self, ctx, check_ins):
        await self.config.guild(ctx.guild).CheckIns.set(check_ins)
