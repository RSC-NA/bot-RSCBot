import discord
import logging
from redbot.core import Config
from redbot.core import commands
from redbot.core import checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

from .BCConfig import BCConfig
from teamManager import TeamManager
from match import Match

import random
import string
import struct
import tempfile
import asyncio
import aiohttp
from typing import List

from pytz import all_timezones_set, timezone, UTC
from datetime import datetime, timedelta
from urllib.parse import unquote

import ballchasing
import requests
import re

log = logging.getLogger("red.RSCBot.bcManager")

defaults = {
    "ReplayDumpChannel": None,
    "AuthToken": None,
    "TopLevelGroup": None,
    "TimeZone": "America/New_York",
    "LogChannel": None,
    "StatsManagerRole": None,
}
global_defaults = {}

verify_timeout = 30
BALLCHASING_URL = "https://ballchasing.com"
RSC_WEB_APP = "http://24.176.157.36:4443"
DONE = "Done"
WHITE_X_REACT = "\U0000274E"  # :negative_squared_cross_mark:
WHITE_CHECK_REACT = "\U00002705"  # :white_check_mark:
RSC_STEAM_ID = 76561199096013422
# RSC_STEAM_ID = 76561197960409023 # REMOVEME - my steam id for development


class BCManager(commands.Cog):
    """Manages aspects of Ballchasing Integrations with RSC"""

    def __init__(self, bot):
        self.config = Config.get_conf(
            self, identifier=1234567893, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.config.register_global(**global_defaults)
        self.bot = bot
        self.team_manager_cog: TeamManager = bot.get_cog("TeamManager")
        self.match_cog: Match = bot.get_cog("Match")
        self.ballchasing_api = {}
        self.rsc_api = {}
        self.task = asyncio.create_task(self.pre_load_data())
        self.ffp = {}  # forfeit processing

    # region admin commands

    # region setup
    # region admin only
    @commands.command(aliases=["setBCAuthKey"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setBCAuthToken(self, ctx, auth_token):
        """Sets the Auth Key for Ballchasing API requests.
        Note: Auth Token must be generated from the Ballchasing group owner
        """
        await ctx.message.delete()

        tlg = await self._get_top_level_group(ctx.guild)
        if tlg:
            bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]
            ping_data = await bapi.ping()

        try:
            api: ballchasing.Api = ballchasing.Api(auth_token)
        except ValueError:
            return await ctx.send(":x: The Auth Token you've provided is invalid.")

        change_action = "updated" if tlg else "set"
        success_msg = f":white_check_mark: Ballchasing token has been {change_action}."
        if api:
            self.ballchasing_api[ctx.guild]: ballchasing.Api = api
            bapi: ballchasing.Api = api
            await self._save_bc_auth_token(ctx.guild, auth_token)

            if tlg:
                group_data = await bapi.get_group(tlg)
                if group_data["creator"]["steam_id"] != ping_data["steam_id"]:
                    await self._save_top_level_group(ctx.guild, None)
                    return await ctx.send(
                        f"{success_msg}. Top Level Group has been cleared."
                    )

            return await ctx.send(success_msg)

        await ctx.send(":x: The Auth Token you've provided is invalid.")

    @commands.command(aliases=["tokencheck"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def tokenCheck(self, ctx):
        guild: discord.Guild = ctx.guild

        # BC token check
        bc_token = await self._get_bc_auth_token(guild)
        valid_bc_token = True if bc_token else False

        wcm = ":white_check_mark:"
        x = ":x:"

        output_parts = ["**RSC Guild Tokens Registered**"]
        output_parts += (
            [f"{wcm} Ballchasing"] if valid_bc_token else [f"{x} Ballchasing"]
        )
        output_str = "\n".join(output_parts)
        await ctx.send(output_str)

    @commands.command(aliases=["setLeagueSeasonGroup", "stlg"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setTopLevelGroup(self, ctx, top_level_group: str):
        """Sets the Top Level Ballchasing Replay group for saving match replays.

        Parameters:
            top_level_group -- Top Level Ballchasing Group (Ex: RSC3v3)

        Note: Auth Token must be generated from the Ballchasing group owner
        """

        top_level_group = self.parse_group_code(top_level_group)

        bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]
        try:
            data = await bapi.get_group(top_level_group)
        except ValueError as exc:
            # python-ballchasing raises a ValueError() that contains a `ClientResponse`. Print error and return.
            log.error(f"Error getting Ballchasing group: {top_level_group} -- {exc}")
            return await ctx.send(
                f"`Error fetching top level group. Status: {exc.args[0].status} {exc.args[0].reason}`"
            )

        # Validate that we actually own the Ballchasing group
        ping = await bapi.ping()
        if ping.get("steam_id") != data.get("creator", {}).get("steam_id", {}):
            return await ctx.send(
                ":x: Ballchasing group creator must be consistent with the registered auth token."
            )

        await self._save_top_level_group(ctx.guild, top_level_group)

        await bapi.patch_group(top_level_group, shared=True)

        await ctx.send(DONE)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setBCLogChannel(self, ctx, channel: discord.TextChannel):
        await self._save_log_channel(ctx.guild, channel)
        await ctx.send(DONE)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setStatsManagerRole(self, ctx, role: discord.Role):
        await self._save_stats_manager_role(ctx.guild, role)
        await ctx.send(DONE)

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setTimeZone(self, ctx, time_zone):
        """Sets timezone for the guild.

        Parameters:
            time_zone -- Time Zone (Default: America/New_York)

        Reference the following wikipedia page: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
        """

        if time_zone not in all_timezones_set:
            wiki = "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"

            msg = (
                f':x: **{time_zone}** is not a valid time zone code. Please select a time zone from the "TZ database name" column '
                f"from this wikipedia page: {wiki}"
            )

            return await ctx.send(msg)

        await self._save_time_zone(ctx.guild, time_zone)
        await ctx.reply("Done")

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def getTimeZone(self, ctx):
        """Gets the configured Time Zone code"""

        tz = await self._get_time_zone(ctx.guild)
        await ctx.reply(f"Current Time Zone code: `{tz}`")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def getBCLogChannel(self, ctx):
        if not await self.has_perms(ctx.author):
            return
        channel: discord.Channel = await self._get_log_channel(ctx.guild)
        if channel:
            await ctx.reply(channel.mention)
        else:
            await ctx.reply("Ballchasing log channel is not configured...")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def getStatsManagerRole(self, ctx):
        if not await self.has_perms(ctx.author):
            return
        role: discord.Role = await self._get_stats_manager_role(ctx.guild)
        if role:
            await ctx.reply(role.mention)
        else:
            await ctx.reply("Stats manager role is not configured...")

    # endregion

    # region normal use
    @commands.max_concurrency(1, per=commands.BucketType.guild)
    @commands.command(aliases=["rtier"])
    @commands.guild_only()
    async def reportTier(
        self, ctx: commands.Context, tier: discord.Role, match_day: int = None
    ):
        if not await self.has_perms(ctx.author):
            return

        # region setup
        log.debug(f"Reporting matches for {tier}")
        log.debug(f"{type(tier)}")
        if not match_day:
            match_day = await self.match_cog._match_day(ctx)

        match_day = str(match_day)

        tier_roles = await self.team_manager_cog.tier_roles(ctx)
        schedule = await self.match_cog._schedule(ctx)
        all_missing_replays = {}

        # endregion

        # region Prep Report Status Message
        log.debug(f"Tier Roles: {tier_roles}")
        if tier not in tier_roles:
            await ctx.send("Invalid tier name provided.")
            return None

        bc_report_summary_json = {}
        tier_md_bc_code = schedule.get(tier.name, {}).get("ballchasing_group_code", "")
        bc_report_summary_json[tier] = {
            "role": tier,
            "index": 0,
            "success_count": 0,
            "bc_group_link": None,
            "total_matches": len(schedule.get(tier.name, {}).get(match_day, [])),
            "bc_hyperlink": f"[View Group]({BALLCHASING_URL}/group/{tier_md_bc_code})"
            if tier_md_bc_code
            else "",
            "active": False,
            "active_match": None,
        }

        # endregion

        guild_emoji_url = ctx.guild.icon.url
        channels = list(set([ctx.channel, (await self._get_log_channel(ctx.guild))]))
        # start_time = ctx.message.created_at
        start_time = datetime.now()
        status_messages = await self.send_embed_to_channels(
            channels,
            self.get_bc_match_day_status_report(
                match_day,
                bc_report_summary_json,
                guild_emoji_url,
                start_time=start_time,
            ),
        )

        # Process/Report All Replays
        bc_report_summary_json[tier]["active"] = True
        missing_tier_replays = []
        tier_md_group_id = None
        tier_report_channel = await self.get_score_reporting_channel(tier)
        for match in schedule.get(tier.name, {}).get(match_day, []):
            log.debug(f"Looking for match: {match}")
            match_group_info = {}
            bc_report_summary_json[tier][
                "active_match"
            ] = f"{match['home']} vs {match['away']}"
            # update RAM status message
            await self.update_embed_in_messages(
                status_messages,
                embed=self.get_bc_match_day_status_report(
                    match_day,
                    bc_report_summary_json,
                    guild_emoji_url,
                    start_time=start_time,
                ),
            )

            # update status embed
            bc_report_summary_json[tier]["index"] += 1

            # if match report valid
            if match.get("report", {}).get("home_wins", 0) or match.get(
                "report", {}
            ).get("away_wins", 0):
                log.debug("Found valid match summary")
                await self.send_match_summary(ctx, match, tier_report_channel)
                bc_report_summary_json[tier]["success_count"] += 1
            else:
                log.debug("No match summary found.")
                match_group_info = await self.process_match_bcreport(
                    ctx,
                    match,
                    tier_md_group_code=tier_md_group_id,
                    score_report_channel=tier_report_channel,
                )

                if not tier_md_group_id and match_group_info.get("is_valid_set", False):
                    tier_md_group_id = match_group_info.get("tier_md_group_id")
                    # TODO: save tier_md_group_id to tier/md in schedule if not there (hyperlink not defined (transitive))
                    tier_md_group_link = f"{BALLCHASING_URL}/group/{tier_md_group_id}"
                    log.debug(f"MD Group ID: {tier_md_group_id}")
                    log.debug(f"BC Report Tier Role: {tier}")
                    log.debug(f"BC Report Summary JSON: {bc_report_summary_json[tier]}")
                    log.debug(
                        f"BC Group Link: {bc_report_summary_json[tier]['bc_group_link']}"
                    )
                    bc_report_summary_json[tier]["bc_group_link"] = tier_md_group_link

                if not match_group_info.get("is_valid_set", False):
                    missing_tier_replays.append(match)
                else:
                    bc_report_summary_json[tier]["success_count"] += 1

            bc_report_summary_json[tier]["active_match"] = None

            if missing_tier_replays:
                all_missing_replays[tier.name] = missing_tier_replays

            bc_report_summary_json[tier]["active"] = False

        # update status message
        await self.update_embed_in_messages(
            status_messages,
            embed=self.get_bc_match_day_status_report(
                match_day,
                bc_report_summary_json,
                emoji_url=guild_emoji_url,
                complete=True,
                start_time=start_time,
            ),
        )

    # region normal use
    @commands.max_concurrency(1, per=commands.BucketType.guild)
    @commands.command(aliases=["reportAllMatches", "ram"])
    @commands.guild_only()
    async def reportMatches(self, ctx: commands.Context, match_day: int = None):
        if not await self.has_perms(ctx.author):
            return

        # region setup
        log.debug("Reporting all matches...")
        if not match_day:
            match_day = await self.match_cog._match_day(ctx)

        match_day = str(match_day)

        tier_roles = await self.team_manager_cog.tier_roles(ctx)
        schedule = await self.match_cog._schedule(ctx)
        all_missing_replays = {}

        # endregion

        # region Prep Report Status Message
        log.debug(f"Tier Roles: {tier_roles}")
        bc_report_summary_json = {}
        for tier_role in tier_roles:
            tier_md_bc_code = schedule.get(tier_role.name, {}).get(
                "ballchasing_group_code", ""
            )
            bc_report_summary_json[tier_role] = {
                "role": tier_role,
                "index": 0,
                "success_count": 0,
                "bc_group_link": None,
                "total_matches": len(
                    schedule.get(tier_role.name, {}).get(match_day, [])
                ),
                "bc_hyperlink": f"[View Group]({BALLCHASING_URL}/group/{tier_md_bc_code})"
                if tier_md_bc_code
                else "",
                "active": False,
                "active_match": None,
            }

        # endregion

        guild_emoji_url = ctx.guild.icon.url
        channels = list(set([ctx.channel, (await self._get_log_channel(ctx.guild))]))
        # start_time = ctx.message.created_at
        start_time = datetime.now()
        status_messages = await self.send_embed_to_channels(
            channels,
            self.get_bc_match_day_status_report(
                match_day,
                bc_report_summary_json,
                guild_emoji_url,
                start_time=start_time,
            ),
        )

        # Process/Report All Replays
        for tier_role in tier_roles:
            bc_report_summary_json[tier_role]["active"] = True
            missing_tier_replays = []
            tier_md_group_id = None
            tier_report_channel = await self.get_score_reporting_channel(tier_role)
            for match in schedule.get(tier_role.name, {}).get(match_day, []):
                log.debug(f"Looking for match: {match}")
                match_group_info = {}
                bc_report_summary_json[tier_role][
                    "active_match"
                ] = f"{match['home']} vs {match['away']}"
                # update RAM status message
                await self.update_embed_in_messages(
                    status_messages,
                    embed=self.get_bc_match_day_status_report(
                        match_day,
                        bc_report_summary_json,
                        guild_emoji_url,
                        start_time=start_time,
                    ),
                )

                # update status embed
                bc_report_summary_json[tier_role]["index"] += 1

                # if match report valid
                if match.get("report", {}).get("home_wins", 0) or match.get(
                    "report", {}
                ).get("away_wins", 0):
                    log.debug("Found valid match summary")
                    await self.send_match_summary(ctx, match, tier_report_channel)
                    bc_report_summary_json[tier_role]["success_count"] += 1
                else:
                    log.debug("No match summary found.")
                    match_group_info = await self.process_match_bcreport(
                        ctx,
                        match,
                        tier_md_group_code=tier_md_group_id,
                        score_report_channel=tier_report_channel,
                    )

                    if not tier_md_group_id and match_group_info.get(
                        "is_valid_set", False
                    ):
                        tier_md_group_id = match_group_info.get("tier_md_group_id")
                        # TODO: save tier_md_group_id to tier/md in schedule if not there (hyperlink not defined (transitive))
                        tier_md_group_link = (
                            f"{BALLCHASING_URL}/group/{tier_md_group_id}"
                        )
                        log.debug(f"MD Group ID: {tier_md_group_id}")
                        log.debug(f"BC Report Tier Role: {tier_role}")
                        log.debug(
                            f"BC Report Summary JSON: {bc_report_summary_json[tier_role]}"
                        )
                        log.debug(
                            f"BC Group Link: {bc_report_summary_json[tier_role]['bc_group_link']}"
                        )
                        bc_report_summary_json[tier_role][
                            "bc_group_link"
                        ] = tier_md_group_link

                    if not match_group_info.get("is_valid_set", False):
                        missing_tier_replays.append(match)
                    else:
                        bc_report_summary_json[tier_role]["success_count"] += 1

                bc_report_summary_json[tier_role]["active_match"] = None

            if missing_tier_replays:
                all_missing_replays[tier_role.name] = missing_tier_replays

            bc_report_summary_json[tier_role]["active"] = False

        # update status message
        await self.update_embed_in_messages(
            status_messages,
            embed=self.get_bc_match_day_status_report(
                match_day,
                bc_report_summary_json,
                emoji_url=guild_emoji_url,
                complete=True,
                start_time=start_time,
            ),
        )

    @commands.max_concurrency(1, per=commands.BucketType.guild)
    @commands.command(aliases=["smm"])
    @commands.guild_only()
    async def scanMissingMatches(self, ctx: commands.Context, match_day: int = None):
        # For current match day
        # For each tier
        # For each unreported match
        # Check if games added
        # Update match results
        # OR
        # Add to missing match report
        if not await self.has_perms(ctx.author):
            return
        log.debug("Reporting all matches...")
        if not match_day:
            match_day = await self.match_cog._match_day(ctx)

        match_day = str(match_day)

        tier_roles = await self.team_manager_cog.tier_roles(ctx)
        schedule = await self.match_cog._schedule(ctx)

        # region Prep Report Status Message
        log.debug(f"Tier Roles: {tier_roles}")
        bc_scan_summary = {}
        for tier_role in tier_roles:
            tier_md_bc_code = schedule.get(tier_role.name, {}).get(
                "ballchasing_group_code", ""
            )
            bc_scan_summary[tier_role] = {
                "role": tier_role,
                "bc_group_link": tier_md_bc_code,
                "bc_hyperlink": f"[View Group]({BALLCHASING_URL}/group/{tier_md_bc_code})"
                if tier_md_bc_code
                else "",
                "total_matches": len(
                    schedule.get(tier_role.name, {}).get(match_day, [])
                ),
                "new_reports": [],
                "missing_reports": [],
                "status": "not searched",
                "active_match": None,
            }
        # endregion

        guild_emoji_url = ctx.guild.icon.url
        channels = list(set([ctx.channel, (await self._get_log_channel(ctx.guild))]))
        # start_time = ctx.message.created_at
        start_time = datetime.now()
        status_messages = await self.send_embed_to_channels(
            channels,
            self.get_bc_missing_match_scan_report_embed(
                match_day,
                bc_scan_summary,
                emoji_url=guild_emoji_url,
                start_time=start_time,
            ),
        )

        for tier_role in tier_roles:
            tier_scan_status = (
                "in progress"
                if bc_scan_summary[tier_role]["total_matches"]
                else "complete"
            )
            bc_scan_summary[tier_role]["status"] = tier_scan_status
            if tier_scan_status == "complete":
                continue
            tier_md_group_id = None
            tier_report_channel: discord.TextChannel = (
                await self.get_score_reporting_channel(tier_role)
            )
            for match in schedule.get(tier_role.name, {}).get(match_day, []):
                # If valid match replays not reported
                if not (
                    match.get("report", {}).get("home_wins", 0)
                    or match.get("report", {}).get("away_wins", 0)
                ):
                    active_match = f"{match['home']} vs {match['away']}"
                    bc_scan_summary[tier_role]["active_match"] = active_match
                    # update SMM status message
                    await self.update_embed_in_messages(
                        status_messages,
                        embed=self.get_bc_missing_match_scan_report_embed(
                            match_day,
                            bc_scan_summary,
                            emoji_url=guild_emoji_url,
                            start_time=start_time,
                        ),
                    )

                    # TODO: improve error handling. remove try/except after secondary team matching is added
                    try:
                        report = await self.update_match_report_from_bc(ctx, match)

                        tier_group_from_report = report.get("tier_md_group_id")
                        if not tier_md_group_id and tier_group_from_report:
                            tier_md_group_id = tier_group_from_report

                        if tier_group_from_report:
                            del report["tier_md_group_id"]

                        match["report"] = report
                        if self.match_has_valid_replay_set(match):
                            score_report_embed: discord.Embed = (
                                await self.get_match_report_embed(ctx, match)
                            )
                            match_report_message: discord.Message = (
                                await tier_report_channel.send(embed=score_report_embed)
                            )
                            match["report"][
                                "score_report_msg_id"
                            ] = match_report_message.id
                            bc_scan_summary[tier_role]["new_reports"].append(
                                f"[{active_match}]({match['report']['link']})"
                            )
                        else:
                            bc_scan_summary[tier_role]["missing_reports"].append(
                                active_match
                            )

                        await self.update_match_report(
                            ctx, tier_role.name, match, match["report"]
                        )
                        bc_scan_summary[tier_role][
                            "active_match"
                        ] = f"{match['home']} vs {match['away']}"
                    except:
                        pass

            bc_scan_summary[tier_role]["status"] = "complete"

        await self.update_embed_in_messages(
            status_messages,
            embed=self.get_bc_missing_match_scan_report_embed(
                match_day,
                bc_scan_summary,
                emoji_url=guild_emoji_url,
                start_time=start_time,
                complete=True,
            ),
        )

    @commands.command(aliases=["rff", "reportFF"])
    @commands.guild_only()
    async def reportForfeits(self, ctx, match_day, team_a, team_b):
        if not await self.has_perms(ctx.author):
            return
        match = await self.get_matchup(ctx, match_day, team_a, team_b)
        if not match:
            return await ctx.reply(
                f":x: No match could be found for **{team_a} vs {team_b}** on match day {match_day}."
            )

        if not match.get("report"):
            return await ctx.reply(":x: This match has not been reported.")
        elif not match["report"].get("ballchasing_id"):
            return await ctx.reply(":x: This match has no ballchasing ID.")

        deep_match_report, embed = await self.get_init_score_deep_summary_and_embed(
            ctx, match
        )
        message = await ctx.reply(embed=embed)

        msg_val = {
            "reporter": ctx.author,
            "message": message,
            "deep_match_report": deep_match_report,
            "match": match,
            "status": "active",
            "timeout": datetime.now() + timedelta(seconds=15),
            "ctx": ctx,
        }

        self.ffp.setdefault(ctx.guild, {}).setdefault(message, msg_val)

        await self.assign_ff_reactions(message, deep_match_report)

    @commands.command()
    @commands.guild_only()
    async def missingMatchReport(self, ctx):
        if not await self.has_perms(ctx.author):
            return
        await self.process_missing_replays(ctx)  # , all_missing_replays)

    @commands.command(aliases=["manuallyReportMatch"])
    @commands.guild_only()
    async def manualMatchReport(
        self, ctx, match_day: int, team_a, a_wins: int, team_b, b_wins: int
    ):
        """Submits a manual report for a match without performing ballchasing requests

        Example:
        [p]manualMatchReport 4 Gorillas 3 Peppermint 1
        """
        if not await self.has_perms(ctx.author):
            return
        match = await self.get_matchup(ctx, match_day, team_a, team_b)
        log.debug(f"Match: {match}")

        if not match:
            return await ctx.reply(":x: Match could not be found.")

        if match.get("report") and match["report"].get("winner"):
            return await ctx.reply(
                f"This match has already been reported:\n{match['report']['summary']}"
            )

        if match["home"].lower() == team_a.lower():
            home_wins = a_wins
            away_wins = b_wins
        else:
            home_wins = b_wins
            away_wins = a_wins

        tier_role = (await self.team_manager_cog._roles_for_team(ctx, match["home"]))[1]

        winner = None
        if home_wins != away_wins:
            winner = match["home"] if home_wins > away_wins else match["away"]

        report = {
            "match_format": match["matchFormat"],
            "winner": winner,
            "home_wins": home_wins,
            "away_wins": away_wins,
            "summary": f"**{match['home']}** {home_wins} - {away_wins} **{match['away']}**",
            "manual": True,
        }

        if not self.data_has_valid_replay_set(report):
            return await ctx.reply(
                f":x: This is not a valid result set for the format `{match['matchFormat']}`"
            )

        match = await self.update_match_report(ctx, tier_role.name, match, report)

        await ctx.reply(DONE)

    @commands.command(aliases=["mmu", "manuallyUpdateMatch", "mum"])
    @commands.guild_only()
    async def manualMatchUpdate(self, ctx, match_day: int, bc_match_link_or_id):
        if not await self.has_perms(ctx.author):
            return
        match_code = self.parse_group_code(bc_match_link_or_id)

        bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]

        data = await bapi.get_group(match_code)
        name = data.get("name")
        teams = name.split(" vs ")

        match = None
        matches = await self.match_cog.get_team_matches(ctx, teams[0], str(match_day))
        for m in matches:
            match_teams = [m["home"], m["away"]]
            if set(teams) == set(match_teams):
                match = m
                break

        if not match:
            return await ctx.reply(
                ":x: No match could be found in association with this match day and group."
            )

        destination_data = await self.get_replay_destination(ctx, match)

        if destination_data["id"] != match_code:
            return await ctx.reply(":x: Something went wrong.")

        tier_role: discord.Role = (
            await self.team_manager_cog._roles_for_team(ctx, teams[0])
        )[1]

        discovery_data = {
            "winner": None,
            "home_wins": 0,
            "away_wins": 0,
            "summary": f"{match['home']} {home_goals} - {away_goals} {match['away']}",
        }
        bc_group_data = {
            "id": match_code,
            "ballchasing_link": f"{BALLCHASING_URL}/group/{match_code}",
        }

        replays = bapi.get_replays(group_id=match_code)

        async for replay in replays:
            home_goals, away_goals = self.get_home_away_goals(match, replay)

            if home_goals > away_goals:
                discovery_data["home_wins"] += 1
            else:
                discovery_data["away_wins"] += 1

        discovery_data[
            "summary"
        ] = f"**{match['home']}** {discovery_data['home_wins']} - {discovery_data['away_wins']} **{match['away']}**"

        if discovery_data["home_wins"] > discovery_data["away_wins"]:
            discovery_data["winner"] = match["home"]
        elif discovery_data["away_wins"] > discovery_data["home_wins"]:
            discovery_data["winner"] = match["away"]

        match_report = {
            "winner": discovery_data.get("winner"),
            "home_wins": discovery_data.get("home_wins"),
            "away_wins": discovery_data.get("away_wins"),
            "summary": discovery_data.get("summary"),
            "ballchasing_id": bc_group_data.get("id"),
            "ballchasing_link": bc_group_data.get(
                "link", f"{BALLCHASING_URL}/group/{bc_group_data.get('id')}"
            ),
        }
        match = await self.update_match_report(ctx, tier_role.name, match, match_report)
        sr_channel = await self.get_score_reporting_channel(tier_role)
        await self.send_match_summary(ctx, match, sr_channel)
        await ctx.reply(DONE)

    # endregion

    # endregion

    # region player commands
    @commands.command(aliases=["bcr", "gg"])
    @commands.guild_only()
    async def bcreport(
        self, ctx, match_day: int = None
    ):  # , team_name=None, match_day=None):
        """Finds match games from recent public uploads, and adds them to the correct Ballchasing subgroup"""
        await self.process_bcreport(ctx, match_day=match_day)

    @commands.command(aliases=["bcGroup", "ballchasingGroup", "bcg", "gsg"])
    @commands.guild_only()
    async def bcgroup(self, ctx):
        """Links to the top level ballchasing group for the current season."""
        group_code = await self._get_top_level_group(ctx.guild)
        url = f"{BALLCHASING_URL}/group/{group_code}"
        if group_code:
            embed = discord.Embed(
                title="RSC Ballchasing Group",
                description=f"[Click to view]({url})",
                color=discord.Color.blue(),
            )

            if ctx.guild.icon.url:
                embed.set_thumbnail(url=ctx.guild.icon.url)

            await ctx.send(embed=embed)
        else:
            await ctx.send(":x: A ballchasing group has not been set for this season.")

    @commands.command(aliases=["clrcon, clrc"])
    @checks.is_owner()
    async def clear_console(self, ctx):
        """Clear console and makes it white. Developer only command."""
        [print("") for x in range(50)]
        print("\033[0;37;40m\nDone!")
        await ctx.send("Done.")

    @commands.command(aliases=["accs", "myAccounts", "registeredAccounts", "bcp"])
    @commands.guild_only()
    async def accounts(self, ctx, *, player: discord.Member = None):
        """View all accounts that have been registered to with your discord account in this guild."""
        if not player:
            player = ctx.author

        log.debug(f"Fetching player accounts for {player.name}")
        # Searching Embed Msg
        tier_role = await self.team_manager_cog.get_current_tier_role(ctx, player)
        franchise_role = self.team_manager_cog.get_current_franchise_role(player)
        log.debug(f"Tier Role: {tier_role} -- Franchise Role: {franchise_role}")
        accounts_embed = discord.Embed(
            title=f"{player.nick if player.nick else player.name}'s Accounts",
            color=discord.Color.blue(),
            description=f"Searching [RSC Tracker Links](https://tinyurl.com/TrackerLinks) for accounts registered to `{player.display_name}`...",
        )
        if tier_role:
            accounts_embed.color = tier_role.color

        # Thumnail
        if franchise_role:
            franchise_emoji_url = await self.team_manager_cog.get_franchise_emoji_url(
                ctx, franchise_role
            )

        log.debug(f"Franchise Emoji URL: {franchise_emoji_url}")
        log.debug(f"Guild Icon URL: {franchise_emoji_url}")
        if franchise_emoji_url:
            accounts_embed.set_thumbnail(
                url=(
                    await self.team_manager_cog.get_franchise_emoji_url(
                        ctx, franchise_role
                    )
                )
            )

        elif ctx.guild.icon_url:
            accounts_embed.set_thumbnail(url=ctx.guild.icon.url)

        # Footer with tracker link. Footer expects string and will not handle `NoneType`
        accounts_embed.set_footer(
            icon_url=ctx.guild.icon.url or "",
            text="RSC Tracker Links: https://tinyurl.com/TrackerLinks",
        )

        msg: discord.Message = await ctx.send(embed=accounts_embed)

        # Fetch player accounts
        linked_accounts = []
        for acc in await self.get_player_accounts(player):
            log.debug(f"Account found: {acc}")
            platform = acc.get("platform").lower()
            plat_id = acc.get("platform_id")
            plat_name = acc.get("name")

            # Find by plat_id (STEAM) or plat_name (OTHER)
            if plat_id:
                latest_replay = await self.get_latest_account_replay_by_plat_id(
                    ctx.guild, platform, plat_id
                )
                log.debug(f"Latest Replay: {latest_replay}")
                if latest_replay:
                    player_data = await self.get_player_data_from_replay_by_plat_id(
                        latest_replay, platform, plat_id
                    )
                    log.debug(f"Player Data (plat_id): {player_data}")
                    plat_name = player_data.get("name", plat_id)
            elif plat_name:
                player_data = await self.get_latest_player_data_by_platform_name(
                    ctx.guild, platform, plat_name
                )
                log.debug(f"Player Data (plat_name): {player_data}")
                plat_id = player_data.get("id", {}).get("id")

            if plat_id and plat_name:
                linked_accounts.append(
                    f"[{platform} | {unquote(plat_name)}]({BALLCHASING_URL}/player/{platform}/{plat_id})"
                )
            elif plat_name:
                linked_accounts.append(f"{platform} | {unquote(plat_name)}")

        all_accounts_linked = " - " + "\n - ".join(linked_accounts)
        accounts_embed.description = (
            all_accounts_linked
            if linked_accounts
            else "No accounts have been registered."
        )
        await msg.edit(embed=accounts_embed)

    # endregion

    # region helper functions

    # region listeners
    @commands.guild_only()
    @commands.Cog.listener("on_reaction_add")
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.id == self.bot.user.id:
            return
        await self.process_ff_reacts(reaction, user, True)

    @commands.guild_only()
    @commands.Cog.listener("on_reaction_remove")
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        if user.id == self.bot.user.id:
            return
        await self.process_ff_reacts(reaction, user, False)

    # Listener helpers
    def reaction_guild(self, reaction: discord.Reaction):
        try:
            return reaction.message.guild
        except:
            return None

    def get_channel(self, message: discord.Message):
        return message.channel

    async def process_ff_reacts(
        self, reaction: discord.Reaction, user: discord.User, added: bool
    ):
        try:
            message = reaction.message
            member = message.author
            guild = message.guild
            channel = message.channel
            ff_processing_data = self.ffp[guild][message]
            if user.id is not ff_processing_data["reporter"].id:
                return
        except:
            return

        ff_emojis = ff_processing_data["deep_match_report"]["ff_able_reacts"]

        if reaction.emoji not in ff_emojis:
            return await reaction.clear()

        now = datetime.now()
        if reaction.emoji in ff_emojis:  # and now <= ff_processing_data['timeout']:
            await self.update_deep_summary_and_message_embed(reaction, added)

    async def process_rff_timeout(self):
        pass

    # endregion

    # region primary helpers

    async def pre_load_data(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            bc_token = await self._get_bc_auth_token(guild)
            if bc_token:
                self.ballchasing_api[guild] = ballchasing.Api(bc_token)

    async def process_bcreport(self, ctx, force=False, match_day: int = None):
        # Step 1: Find Match
        player = ctx.author
        matches = await self.get_matches(ctx, player, match_day=match_day)
        if not matches:
            await ctx.send(":x: No matches found.")
            return None

        for match in matches:
            if not match.get("report", {}) or force or match["report"].get("summary"):
                await self.process_match_bcreport(ctx, match)
            else:
                await self.send_match_summary(ctx, match)

    async def process_match_bcreport(
        self,
        ctx,
        match,
        tier_md_group_code: str = None,
        score_report_channel: discord.TextChannel = None,
    ):
        log.debug(
            f"Processing BC report. Group: {tier_md_group_code} - Channel: {score_report_channel} - Match {match}"
        )
        # Step 0: Constants
        SEARCHING = f"Searching {BALLCHASING_URL} for publicly uploaded replays of this match..."
        FOUND_AND_UPLOADING = "\n:signal_strength: Results confirmed. Creating a ballchasing replay group. This may take a few seconds..."
        SUCCESS_EMBED = "Match Summary:\n{}\n\n[View group on ballchasing!]({})"

        # Step 2: Send initial embed (Searching...)
        match_day: int = match["matchDay"]
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
            ctx, match["home"]
        )
        log.debug(f"Franchise Role: {franchise_role}")
        log.debug(f"Tier Role: {tier_role}")
        emoji_url = ctx.guild.icon.url

        score_report_embed = discord.Embed(
            title=f"MD {match_day}: {match['home']} vs {match['away']}",
            description=SEARCHING,
            color=tier_role.color,
        )
        if emoji_url:
            score_report_embed.set_thumbnail(url=emoji_url)

        single_player_call = not score_report_channel
        score_report_channel = (
            score_report_channel
            if score_report_channel
            else await self.get_score_reporting_channel(tier_role)
        )
        log.debug(
            f"Single Player Call: {single_player_call} - Report Channel: {score_report_channel}"
        )

        if single_player_call:
            bc_status_msg: discord.Message = await ctx.reply(embed=score_report_embed)

        # Step 3: Search for replays on ballchasing
        discovery_data = await self.find_match_replays(ctx, match)
        log.debug(f"Discovery Data: {discovery_data}")

        ## Not found:
        valid_replay_set = discovery_data.get("is_valid_set", False)
        if not valid_replay_set:
            if single_player_call:
                replays_found = len(discovery_data.get("replay_hashes"))
                score_report_embed.description = (
                    ":x: A valid set of replays could not be found for this match."
                )
                score_report_embed.description += (
                    f" (only {replays_found} found)" if replays_found else " (0 found)"
                )
                await bc_status_msg.edit(embed=score_report_embed)
            # return {}

        ## Found:
        winner = discovery_data.get("winner", None)
        if winner and valid_replay_set:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, winner
            )
            emoji_url = await self.team_manager_cog.get_franchise_emoji_url(
                ctx, franchise_role
            )
            if emoji_url:
                score_report_embed.set_thumbnail(url=emoji_url)

        update_player_msg_embed = single_player_call and valid_replay_set

        # Step 4: Send updated embed (Status: found, uploading)
        score_report_embed.description = "Match Summary:\n{}\n{}".format(
            discovery_data.get("summary"), FOUND_AND_UPLOADING
        )
        if update_player_msg_embed:
            await bc_status_msg.edit(embed=score_report_embed)

        # Find or create ballchasing subgroup
        match_subgroup_json = await self.get_replay_destination(
            ctx, match, tier_md_group_code=tier_md_group_code
        )
        match_subgroup_id = match_subgroup_json.get("id")

        tmp_replay_files = await self.tmp_download_replays(
            ctx, discovery_data.get("match_replay_ids", [])
        )
        uploaded_ids = await self.upload_replays(
            ctx, match_subgroup_id, tmp_replay_files
        )

        # renamed = await self._rename_replays(ctx, uploaded_ids)

        # Step 5: Group created, Finalize embed
        score_report_embed.description = SUCCESS_EMBED.format(
            discovery_data.get("summary"), match_subgroup_json.get("link")
        )
        if update_player_msg_embed:
            await bc_status_msg.edit(embed=score_report_embed)

        if valid_replay_set:
            match_report_message = await score_report_channel.send(
                embed=score_report_embed
            )

            # Step 6: Update match cog info
            report = {
                "winner": discovery_data.get("winner"),
                "home_wins": discovery_data.get("home_wins"),
                "away_wins": discovery_data.get("away_wins"),
                "summary": discovery_data.get("summary"),
                "score_report_msg_id": match_report_message.id,
                "ballchasing_id": match_subgroup_json.get("id"),
                "ballchasing_link": match_subgroup_json.get(
                    "link", f"{BALLCHASING_URL}/group/{match_subgroup_json.get('id')}"
                ),
            }
        else:
            report = {
                "ballchasing_id": match_subgroup_json.get("id"),
                "ballchasing_link": match_subgroup_json.get(
                    "link", f"{BALLCHASING_URL}/group/{match_subgroup_json.get('id')}"
                ),
            }
        await self.update_match_report(
            ctx, tier_role.name, match, report
        )  # returns match

        match_subgroup_json["is_valid_set"] = discovery_data["is_valid_set"]

        return match_subgroup_json

    async def update_match_report_from_bc(self, ctx, match):
        report = match.get("report", {})
        if not report.get("id"):
            report = await self.get_replay_destination(ctx, match)

        bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]
        data = bapi.get_replays(group_id=report.get("id"))

        home_wins = 0
        away_wins = 0
        async for replay in data:
            home_goals, away_goals = self.get_home_away_goals(match, replay)
            if home_goals > away_goals:
                home_wins += 1
            elif home_goals < away_goals:
                away_wins += 1

        if not home_wins + away_wins:
            return report

        report[
            "summary"
        ] = f"**{match['home']}** {home_wins} - {away_wins} **{match['away']}**"
        report["home_wins"] = home_wins
        report["away_wins"] = away_wins

        if home_wins > away_wins:
            report["winner"] = match["home"]
        elif home_wins < away_wins:
            report["winner"] = match["away"]

        return report

    async def get_init_score_deep_summary_and_embed(self, ctx, match):
        title = (
            f"MD {match['matchDay']}: {match['home']} vs {match['away']} [FF Report]"
        )
        tier_role, match_emoji_url = await self.get_match_tier_role_and_emoji_url(
            ctx, match
        )

        home_franchise_role = (
            await self.team_manager_cog._roles_for_team(ctx, match["home"])
        )[0]
        away_franchise_role = (
            await self.team_manager_cog._roles_for_team(ctx, match["away"])
        )[0]
        home_emoji = await self.team_manager_cog._get_franchise_emoji(
            ctx, home_franchise_role
        )
        away_emoji = await self.team_manager_cog._get_franchise_emoji(
            ctx, away_franchise_role
        )
        log.debug(f"Match Report: {match['report']}")
        ballchasing_link = match["report"]["ballchasing_link"]

        bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]

        replays = bapi.get_replays(group_id=match["report"]["ballchasing_id"])

        description = "Match Summary\n" + match["report"]["summary"] + "\n"
        embed = discord.Embed(
            title=title, description=description, color=tier_role.color
        )

        # previously ff games
        forfeits = match["report"].get("forfeits")
        ff_indexes = [ff["game_num"] for ff in forfeits] if forfeits else []

        # valid games
        r_description = ""
        game_summaries = []
        ff_able_reacts = []
        gi = 1
        i = 0
        react_hex_code = 0x1F1E6  # A
        async for replay in replays:
            while gi in ff_indexes:
                gi += 1
                i += 1
            react_hex = hex(react_hex_code + i)
            react = self.get_select_reaction(int(react_hex, base=16))
            ff_able_reacts.append(react)
            home_goals, away_goals = self.get_home_away_goals(match, replay)
            winner_emoji = home_emoji if home_goals > away_goals else away_emoji
            summary = f"{react} **G{gi}:** {match['home']} {home_goals} - {away_goals} {match['away']}"
            if winner_emoji:
                summary += f" {winner_emoji}"

            game_summaries.append(
                {
                    "summary": summary,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "game_no": gi,
                    "react": react_hex,
                    "reaction_str": react,
                    "replay": replay,
                    "ff": False,
                }
            )
            r_description += "\n" + summary
            gi += 1
            i += 1

        # add fields
        embed.add_field(name="Game Breakdown", value=r_description, inline=True)

        if forfeits:
            embed.add_field(
                name="Forfeited Games",
                value="\n".join(
                    [f"{ff['ff_team']} FF Game {ff['game_num']}" for ff in forfeits]
                ),
                inline=True,
            )
        else:
            embed.add_field(name="Forfeited Games", value="[None]")

        embed.add_field(
            name="View in Ballchasing",
            value=f"[Click here to view the group]({ballchasing_link})",
            inline=False,
        )
        embed.add_field(
            name="Instructions",
            value="React to report match games as forfeited.\nReact with :white_check_mark: to confirm, or :negative_squared_cross_mark: to cancel.",
            inline=False,
        )

        if match_emoji_url:
            embed.set_thumbnail(url=match_emoji_url)

        deep_match_report = {
            "ff_able_reacts": ff_able_reacts + [WHITE_CHECK_REACT, WHITE_X_REACT],
            "home_emoji": home_emoji,
            "away_emoji": away_emoji,
            "game_summaries": game_summaries,
        }
        if forfeits:
            deep_match_report["ff_summaries"] = forfeits

        return deep_match_report, embed

    async def update_deep_summary_and_message_embed(
        self, reaction: discord.Reaction, added: bool
    ):
        # member: discord.Member = reaction.member
        message: discord.Message = reaction.message
        emoji: discord.Emoji = reaction.emoji
        guild = message.guild
        ff_processing_data = self.ffp[guild][message]
        match = ff_processing_data["match"]
        reporter: discord.Member = ff_processing_data["reporter"]

        if emoji == WHITE_X_REACT:
            return await self.finalize_ff_report(guild, message, emoji)

        # Capture previously ff games
        forfeits = match["report"].get("forfeits", [])
        if forfeits:
            locked_ffs = [
                f"{ff['ff_team']} FF Game {ff['game_num']}" for ff in forfeits
            ]
        else:
            locked_ffs = []

        # update and categorize FF'd games
        non_ff_games = []
        ff_games = []
        match_ffs_record = []
        home_w_adjust = 0
        for gs in self.ffp[guild][message]["deep_match_report"]["game_summaries"]:
            # Flip FFs

            # If reaction emoji is equal to the one assigned to this game summary
            if self.get_select_reaction(gs["react"]) == emoji:
                if gs["ff"]:
                    # old_ff = match['home'] if gs['ff'] == match['home'] else match['away']
                    # home_w_adjust += 1 if old_ff == match['home'] else -1
                    gs["ff"] = False
                else:
                    gs["ff"] = (
                        match["home"]
                        if gs["home_goals"] > gs["away_goals"]
                        else match["away"]
                    )

            if gs["ff"]:
                if gs["ff"] == match["home"]:
                    home_w_adjust -= 1
                elif gs["ff"] == match["away"]:
                    home_w_adjust += 1
                ff_games.append(gs["summary"])

                match_ffs_record.append(
                    {
                        "game_num": gs["game_no"],
                        "ff_team": gs["ff"],
                        "replay_id": gs["replay"]["id"],
                        "reason": f"Updated by {reporter.display_name}",
                        "reporter": f"{reporter.name}#{reporter.discriminator}",
                    }
                )
            else:
                non_ff_games.append(gs["summary"])

        home_wins = match["report"]["home_wins"]
        away_wins = match["report"]["away_wins"]
        description = message.embeds[0].description
        description_parts = description.split("\n")

        # ff_games = locked_ffs + ff_games
        if ff_games:  # away_w_adjust is zero-sum
            home_wins += home_w_adjust
            away_wins -= home_w_adjust
            if len(description_parts) == 2:
                if home_w_adjust:
                    description_parts[1] = f"~~{description_parts[1]}~~"
                    description_parts.append(
                        f"**{match['home']}** {home_wins} - {away_wins} **{match['away']}**"
                    )
                else:
                    description_parts = description_parts[:2]
                    description_parts[1] = description_parts[1].replace("~", "")

            elif len(description_parts) == 3:
                description_parts[
                    2
                ] = f"**{match['home']}** {home_wins} - {away_wins} **{match['away']}**"
        else:
            description_parts = description_parts[:2]
            description_parts[1] = description_parts[1].replace("~", "")

        description = "\n".join(description_parts)

        # Create Updated Embed
        embed = discord.Embed(
            title=message.embeds[0].title,
            description=description,
            color=message.embeds[0].color,
        )

        # add fields
        if non_ff_games:
            embed.add_field(
                name="Game Breakdown", value="\n".join(non_ff_games), inline=True
            )
        else:
            embed.add_field(
                name="Game Breakdown", value="ALL GAMES FF LOL", inline=True
            )

        # ff_games = locked_ffs + ff_games
        if ff_games or locked_ffs:
            embed.add_field(
                name="Forfeited Games", value="\n".join(locked_ffs + ff_games)
            )
        else:
            embed.add_field(name="Forfeited Games", value="[None]")

        embed.add_field(
            name="View in Ballchasing",
            value=f"[Click here to view the group]({match['report']['ballchasing_link']})",
            inline=False,
        )
        embed.add_field(
            name="Instructions",
            value="React to report match games as forfeited.\nReact with :white_check_mark: to confirm, or :negative_squared_cross_mark: to cancel.",
            inline=False,
        )

        # update thumbnail
        if home_wins > away_wins:
            winner = match["home"]
            home_emoji = self.ffp[guild][message]["deep_match_report"]["home_emoji"]
            if home_emoji:
                embed.set_thumbnail(url=home_emoji.url)
            else:
                embed.set_thumbnail(url=guild.icon.url)
        elif home_wins < away_wins:
            winner = match["away"]
            away_emoji = self.ffp[guild][message]["deep_match_report"]["away_emoji"]
            if away_emoji:
                embed.set_thumbnail(url=away_emoji.url)
            else:
                embed.set_thumbnail(url=guild.icon.url)
        else:
            winner = None
            embed.set_thumbnail(url=guild.icon.url)

        # update match info
        match["report"][
            "summary"
        ] = f"**{match['home']}** {home_wins} - {away_wins} **{match['away']}**"
        match["report"]["winner"] = winner
        if emoji == WHITE_CHECK_REACT:
            match["report"]["forfeits"] = (
                forfeits + match_ffs_record
            )  # WARNING: duplicate applied FF reports will override any preceeding ones
            match["report"]["home_wins"] = home_wins
            match["report"]["away_wins"] = away_wins
            return await self.finalize_ff_report(guild, message, emoji)
        self.ffp[guild][message]["match"] = match

        await message.edit(embed=embed)

    async def finalize_ff_report(
        self,
        guild: discord.Guild,
        message: discord.Message,
        emoji: discord.Emoji,
        reason="canceled",
    ):
        from pprint import pprint as pp

        embed_update = message.embeds[0]
        embed_update.remove_field(-1)

        if emoji == WHITE_CHECK_REACT:
            match = self.ffp[guild][message]["match"]
            ctx: commands.Context = self.ffp[guild][message]["ctx"]
            tier_role = (
                await self.team_manager_cog._roles_for_team(ctx, match["home"])
            )[1]
            ff_replay_ids = match.get("report", {}).get("forfeits", [])
            if ff_replay_ids:
                description = (
                    "The match info has been updated, and the replay has been "
                    + "removed from the ballchasing group (if applicable)."
                )
                for ff in ff_replay_ids:
                    replay_id = ff["replay_id"]
                    bapi: ballchasing.Api = self.ballchasing_api[guild]
                    await bapi.patch_replay(replay_id=replay_id, group="")
                await self.update_match_report(
                    ctx, tier_role.name, match, match["report"]
                )
            else:
                description = "No changes have been applied."

            embed_update.add_field(
                name=f"{WHITE_CHECK_REACT} This FF Report has been completed.",
                value=description,
                inline=False,
            )
        else:
            stop_reason = "been canceled" if reason == "canceled" else "timed out"
            embed_update.add_field(
                name=f"{WHITE_X_REACT} This FF Report has {stop_reason}.",
                value="If you wish to report a forfeit for this match, please try again.",
                inline=False,
            )

        await message.edit(embed=embed_update)
        del self.ffp[guild][message]

    async def get_matchup(self, ctx, match_day, team_a, team_b):
        """Get match data by day and team names

        Parameters:
        match_day -- Match Day (Ex: 1)
        team_a -- Team Name A
        team_b -- Team Name B
        """
        matches = await self.get_matches(ctx, team=team_a, match_day=match_day)
        search_teams = [team_a.lower(), team_b.lower()]
        for match in matches:
            match_teams = [match["home"].lower(), match["away"].lower()]
            if len(set(search_teams + match_teams)) == 2:
                return match
        return None

    async def get_match(self, ctx, member, team=None, match_day=None, match_index=0):
        return (await self.get_matches(ctx, member, team, match_day))[match_index]

    # this method got a little sloppy
    async def get_matches(self, ctx, member=None, team=None, match_day=None):
        if not match_day:
            match_day = await self.match_cog._match_day(ctx)
        if not team:
            team = (await self.team_manager_cog.teams_for_user(ctx, member))[0]
        if not team and not member:
            return None

        matches = await self.match_cog.get_team_matches(ctx, team, match_day)

        return matches

    async def find_match_replays(self, ctx, match):
        log.debug("Searching for match replays...")
        all_players = await self.get_all_match_players(ctx, match)
        log.debug(f"Players: {all_players}")

        # All of this data should be tracked to optimize the search and validation
        discovery_data = {
            "is_valid_set": False,
            "match_format": match.get("matchFormat", "4-GS"),
            "summary": None,
            "match_replay_ids": [],
            "replay_hashes": [],
            "latest_replay_end": None,
            "home_wins": 0,
            "away_wins": 0,
            "winner": None,
            "accounts_searched": [],
            "players_searched": [],
        }

        guild = ctx.guild
        try:
            bapi: ballchasing.Api = self.ballchasing_api[guild]
        except KeyError:
            error_str = ":x: A ballchasing token has not been set for this guild."
            discovery_data["summary"] = error_str
            return discovery_data

        # Prep initial date search range
        # match_date = datetime.strptime(match['matchDate'], '%B %d, %Y').strftime('%Y-%m-%d')
        # match_start_dt = BCConfig.START_MATCH_DT_TMPLT.format(match_date, BCConfig.ZONE_ADJ)
        # match_end_dt = BCConfig.END_MATCH_DT_TMPLT.format(match_date, BCConfig.ZONE_ADJ)

        guild_timezone = await self._get_time_zone(ctx.guild)

        # Localized Datetime
        dt_match_start = datetime.strptime(
            f"{match['matchDate']} 9:00PM", "%B %d, %Y %I:%M%p"
        ).astimezone(timezone(guild_timezone))
        dt_match_end = datetime.strptime(
            f"{match['matchDate']} 11:59PM", "%B %d, %Y %I:%M%p"
        ).astimezone(timezone(guild_timezone))
        log.debug(f"Search Start: {dt_match_start} - Match End: {dt_match_end}")

        # RFC3339 Formatted UTC time
        utc_dt_open_search_range_str = dt_match_start.astimezone(UTC).strftime(
            BCConfig.utc_strftime_fmt
        )
        utc_dt_close_search_range_str = dt_match_end.astimezone(UTC).strftime(
            BCConfig.utc_strftime_fmt
        )

        # Search all players in game for replays until match is found

        is_valid_set = False
        for player in all_players:
            for steam_id in await self.get_steam_ids(player):
                data = bapi.get_replays(
                    playlist=BCConfig.PLAYLIST,
                    sort_by=BCConfig.SORT_BY,
                    sort_dir=BCConfig.SORT_DIR,
                    replay_after=utc_dt_open_search_range_str,
                    replay_before=utc_dt_close_search_range_str,
                    uploader=steam_id,
                )

                min_games_required = self.get_min_replay_count(
                    discovery_data.get("match_format", "4-gs")
                )

                # checks for MATCHing ;) replays
                async for replay in data:
                    replay_hash = self.should_add_replay_to_set(
                        match, replay, discovery_data
                    )
                    if replay_hash:
                        discovery_data["replay_hashes"].append(replay_hash)
                        discovery_data["match_replay_ids"].append(replay["id"])

                        home_goals, away_goals = self.get_home_away_goals(match, replay)

                        if home_goals or away_goals:
                            if home_goals > away_goals:
                                discovery_data["home_wins"] += 1
                            else:
                                discovery_data["away_wins"] += 1
                        else:
                            continue

                        # see if replay set is valid
                        if len(discovery_data["replay_hashes"]) >= min_games_required:
                            is_valid_set = self.data_has_valid_replay_set(
                                discovery_data
                            )
                            discovery_data["is_valid_set"] = is_valid_set
                            if is_valid_set:
                                discovery_data = await self.set_series_winner(
                                    match, discovery_data
                                )
                                if discovery_data.get("is_valid_set", is_valid_set):
                                    discovery_data[
                                        "summary"
                                    ] = f"**{match['home']}** {discovery_data['home_wins']} - {discovery_data['away_wins']} **{match['away']}**"
                                    return discovery_data

                # update accounts searched to avoid duplicate searches (maybe not needed)
                discovery_data["accounts_searched"].append(steam_id)

            # update players searched to avoid duplicate searches (maybe not needed)
            discovery_data["players_searched"].append(player)

        return discovery_data

    async def set_series_winner(self, match, discovery_data):
        winner = None
        if discovery_data["home_wins"] > discovery_data["away_wins"]:
            winner = match["home"]
        elif discovery_data["home_wins"] < discovery_data["away_wins"]:
            winner = match["away"]

        discovery_data["winner"] = winner

        return discovery_data

    async def get_replay_destination(self, ctx, match, tier_md_group_code=None):
        # Ballchasing subgroup structure:
        # RSC/<top level group>/<match type>/<tier num><tier>/Match Day <match day>/<Home> vs <Away>

        if not tier_md_group_code:
            # The path to the match subgroup is unknown and must be discovered
            tier = (await self.team_manager_cog._roles_for_team(ctx, match["home"]))[
                1
            ].name  # Get tier role's name
            tier_group = await self.get_tier_subgroup_name(ctx.guild, tier)
            top_level_group = await self._get_top_level_group(ctx.guild)
            ordered_subgroup_names = [
                match.get("matchType", "Regular Season"),
                tier_group,
                f"Match Day {str(match['matchDay']).zfill(2)}",
                # f"{match['home']} vs {match['away']}"
                f"{match['away']} vs {match['home']}",
            ]

        else:
            # The parent group for the match group has already been determined
            top_level_group = tier_md_group_code
            ordered_subgroup_names = [
                # f"{match['home']} vs {match['away']}" # TODO: update again?
                f"{match['away']} vs {match['home']}"
            ]

        # Begin Ballchasing Group Mgmt
        bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]
        data = bapi.get_groups(group=top_level_group)

        # Dynamically create sub-group
        current_subgroup_id = top_level_group
        next_subgroup_id = None
        for next_group_name in ordered_subgroup_names:
            if next_subgroup_id:
                current_subgroup_id = next_subgroup_id
            next_subgroup_id = None

            # Check if next subgroup exists
            async for data_subgroup in data:
                if data_subgroup["name"] == next_group_name:
                    next_subgroup_id = data_subgroup["id"]
                    break

            # Prepare & Execute  Next request:
            # ## Next subgroup found: request its contents
            if next_subgroup_id:
                data = bapi.get_groups(group=next_subgroup_id)

            # ## Creating next sub-group
            else:
                data = await bapi.create_group(
                    name=next_group_name,
                    parent=current_subgroup_id,
                    player_identification=BCConfig.player_identification,
                    team_identification=BCConfig.team_identification,
                )

                next_subgroup_id = data["id"]

                if next_group_name is not ordered_subgroup_names[-1]:
                    data = bapi.get_groups(group=next_subgroup_id)

        # After we create match subgroup
        return {
            "id": next_subgroup_id,
            "tier_md_group_id": current_subgroup_id,
            "link": f"{BALLCHASING_URL}/group/{next_subgroup_id}",
        }

    async def upload_replays(self, ctx, subgroup_id, files_to_upload):
        """Upload replay bytes to ballchasing using random name."""
        replay_ids_in_group = []
        bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]
        for replay_file in files_to_upload:
            try:
                rname = f"{''.join(random.choices(string.ascii_letters + string.digits, k=64))}.replay"
                data = await bapi.upload_replay_from_bytes(
                    rname,
                    replay_file,
                    visibility=BCConfig.visibility,
                    group=subgroup_id,
                )
                replay_ids_in_group.append(data.get("id", "FAILED"))
            except ValueError as e:
                if e.args[0].status == 409:
                    # duplicate replay
                    err_info = await e.args[0].json()
                    log.debug(
                        f"Error uploading replay. {e.args[0].status} -- {err_info}"
                    )
                    replay_id = err_info.get("id", "FAILED")
                    await bapi.patch_replay(replay_id, group=subgroup_id)
                    replay_ids_in_group.append(replay_id)

        return replay_ids_in_group

    # TODO
    async def process_missing_replays(self, ctx):  # , missing_replays: dict):
        # Step 0: Load old missing replays
        missing_matches = await self.match_cog.get_unreported_matches(ctx)

        # Step 1: search ballchasing for old missing replays, update old missing replays

        # Step 2: re-search missing replays, update new missing replays

        # Step 3: combine old and new missing replays data set

        # Step 4: generate missing replays report message
        missing_replays_report = await self.generate_missing_replays_msg(
            ctx.guild, missing_matches
        )

        # Step 5: save all missing replay data to json

        # Step 6: send missing replays report to stats-updates channel
        # channel : discord.TextChannel = await self.get_stats_updates_channel(ctx.guild)
        channel = await self._get_log_channel(ctx.guild)
        await channel.send(missing_replays_report)

    async def generate_missing_replays_msg(self, guild, missing_matches):
        tier_chunks = []

        for tier, matches in missing_matches.items():
            tier_str = f"__{tier}__"
            tier_str += "\n```\n"

            for match in matches:
                tier_str += "\n"
                if match["matchDay"].isdigit():
                    tier_str += (
                        f"{match['home']} vs {match['away']} - MD{match['matchDay']}"
                    )
                else:
                    tier_str += (
                        f"{match['home']} vs {match['away']} - MD-{match['matchDay']}"
                    )
                    mt = match.get("matchType")
                    if mt:
                        tier_str += f" ({mt})"

            tier_str += "\n```\n"

            tier_chunks.append(tier_str)

        report = ""
        report += "\n".join(tier_chunks)

        ballchasing_link = await self._get_top_level_group(guild)
        report += "\n"
        report += f"RSC Ballchasing group: <{BALLCHASING_URL}/group/{ballchasing_link}>"
        report += "\nRSC Match Day Rules: <https://tinyurl.com/MatchDayRules>"

        return report

    # endregion

    # region validations

    def should_add_replay_to_set(self, match, replay, discovery_data):
        if self.is_valid_match_replay(match, replay):
            # replay_ids.append(replay['id'])
            replay_hash = self.generate_replay_hash(replay)
            if replay_hash not in discovery_data["replay_hashes"]:
                return replay_hash
        return False

    def is_full_replay(self, replay_data):
        if replay_data.get("duration", 0) < 300:
            return False

        blue_goals = (
            replay_data["blue"]["goals"] if "goals" in replay_data["blue"] else 0
        )
        orange_goals = (
            replay_data["orange"]["goals"] if "goals" in replay_data["orange"] else 0
        )
        if blue_goals == orange_goals:
            return False
        for team in ["blue", "orange"]:
            if not replay_data.get(team) or not replay_data[team].get("players"):
                return False
            for player in replay_data[team]["players"]:
                if player["start_time"] == 0:
                    return True
        return False

    def is_valid_match_replay(self, match, replay_data):
        match_day = match["matchDay"]  # match cog
        home_team = match["home"]  # match cog
        away_team = match["away"]  # match cog

        if not self.is_full_replay(replay_data):
            return False

        replay_teams = self.get_replay_teams_and_players(replay_data)

        home_team_found = re.sub(
            r"\W+", "", replay_teams["blue"]["name"].lower()
        ) in re.sub(r"\W+", "", home_team.lower()) or re.sub(
            r"\W+", "", replay_teams["orange"]["name"].lower()
        ) in re.sub(
            r"\W+", "", home_team.lower()
        )
        away_team_found = re.sub(
            r"\W+", "", replay_teams["blue"]["name"].lower()
        ) in re.sub(r"\W+", "", away_team.lower()) or re.sub(
            r"\W+", "", replay_teams["orange"]["name"].lower()
        ) in re.sub(
            r"\W+", "", away_team.lower()
        )

        return home_team_found and away_team_found

    def get_replay_team_data(self, replay):
        try:
            blue_name = replay.get("blue", {}).get("name", "").title()
        except:
            blue_name = "Blue"
        try:
            orange_name = replay.get("orange", {}).get("name", "").title()
        except:
            orange_name = "Orange"

        blue_players = []
        for player in replay.get("blue", {}).get("players", []):
            player_name = player.get("name")
            if player_name:
                blue_players.append(player_name)

        orange_players = []
        for player in replay.get("orange", {}).get("players", []):
            player_name = player.get("name")
            if player_name:
                orange_players.append(player_name)

        team_data = {
            "blue": {"name": blue_name, "players": blue_players},
            "orange": {"name": orange_name, "players": orange_players},
        }
        return team_data

    def get_min_replay_count(self, match_format: str):
        format_type, fmt_games = self.get_match_fmt_components(match_format)
        if format_type.lower() == "gs":
            return fmt_games
        return (fmt_games + 1) / 2

    def match_has_valid_replay_set(self, match):
        if not match.get("report", None):
            return False

        return self.is_valid_replay_set(
            match.get("match_format", "4-gs"),
            match.get("report", {}).get("home_wins", 0),
            match.get("report", {}).get("away_wins", 0),
        )

    def data_has_valid_replay_set(self, data):
        return self.is_valid_replay_set(
            data.get("match_format", "4-gs"),
            data.get("home_wins", 0),
            data.get("away_wins", 0),
        )

    def is_valid_replay_set(self, match_format, home_wins, away_wins):
        log.debug(f"is_valid_replay_set: {match_format}")
        format_type, fmt_games = self.get_match_fmt_components(match_format)
        log.debug(f"format_type: {format_type} - fmt_games: {fmt_games}")
        gp = home_wins + away_wins

        if format_type.lower() == "gs":
            return gp == fmt_games

        elif format_type.lower() == "bo":
            required_winning_team_wins = int(fmt_games / 2) + 1
            return gp <= fmt_games and required_winning_team_wins in [
                home_wins,
                away_wins,
            ]

        return False

    def get_match_fmt_components(self, match_format: str):
        log.debug(f"Match Format: {match_format}")
        format_components = match_format.split("-")

        for component in format_components:
            if component.isdigit():
                fmt_games = int(component)
                break

        format_components.remove(str(fmt_games))
        fmt_type = format_components[0]
        return fmt_type, fmt_games

    # endregion

    # region secondary helpers
    async def has_perms(self, member: discord.Member):
        if member.guild_permissions.administrator:
            return True
        stats_role = await self._get_stats_manager_role(member.guild)
        return stats_role and stats_role in member.roles

    def get_home_away_goals(self, match, replay):
        if (
            replay.get("blue", {}).get("name", "blue").lower()
            in match.get("home", "").lower()
            or replay.get("orange", {}).get("name", "orange").lower()
            in match.get("away", "").lower()
        ):
            home = "blue"
            away = "orange"
        elif (
            replay.get("orange", {}).get("name", "orange").lower()
            in match.get("home", "").lower()
            or replay.get("blue", {}).get("name", "blue").lower()
            in match.get("away", "").lower()
        ):
            home = "orange"
            away = "blue"
        else:
            return None, None

        home_goals = replay[home].get("goals", 0)
        away_goals = replay[away].get("goals", 0)

        return home_goals, away_goals

    async def update_match_report(self, ctx, tier, match, report):
        schedule = await self.match_cog._schedule(ctx)
        match_index = self.match_cog.get_match_index_in_day(schedule, tier, match)

        schedule[tier][match["matchDay"]][match_index]["report"] = report

        await self.match_cog._save_schedule(ctx, schedule)

        match["report"] = report
        return match

    async def get_match_report_embed(self, ctx, match):
        report = match["report"]
        winner = report.get("winner")
        if winner:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, winner
            )
            emoji_url = await self.team_manager_cog.get_franchise_emoji_url(
                ctx, franchise_role
            )
        else:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, match["home"]
            )
            emoji_url = ctx.guild.icon.url

        summary = f"**{match['home']}** {report.get('home_wins', 0)} - {report.get('away_wins', 0)} **{match['away']}**"
        SUCCESS_EMBED = "Match Summary:\n{}\n\n[View group on ballchasing!]({})"

        score_report_embed = discord.Embed(
            title=f"MD {match['matchDay']}: {match['home']} vs {match['away']}",
            description=SUCCESS_EMBED.format(summary, report.get("link")),
            color=tier_role.color,
        )

        if emoji_url:
            score_report_embed.set_thumbnail(url=emoji_url)

        return score_report_embed

    # TODO: UPDATE match summary (similar)
    # Note: if report_channel is NOT provided, then this is called from bcr
    async def send_match_summary(
        self, ctx, match, score_report_channel: discord.TextChannel = None
    ):
        title = f"MD {match['matchDay']}: {match['home']} vs {match['away']}"
        if not match.get("report", False):
            log.debug(f"Cannot post for unreported game, {title}")
            return

        log.debug(f"Match Data: {match}")
        tier_role, emoji_url = await self.get_match_tier_role_and_emoji_url(ctx, match)
        ballchasing_link = match["report"].get(
            "ballchasing_link", match["report"].get("link")
        )  # TODO: Standardize

        description = "Match Summary:\n{}\n\n".format(match["report"]["summary"])
        description += f"[View on ballchasing!]({ballchasing_link})"

        embed = discord.Embed(
            title=title, description=description, color=tier_role.color
        )
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)

        if not score_report_channel:
            await ctx.reply(embed=embed)

        if "score_report_msg_id" not in match["report"]:
            score_report_channel = (
                score_report_channel
                if score_report_channel
                else await self.get_score_reporting_channel(tier_role)
            )
            score_report_message = await score_report_channel.send(embed=embed)
            match["report"]["score_report_msg_id"] = score_report_message.id
            await self.update_match_report(ctx, tier_role.name, match, match["report"])

    def get_bc_match_day_status_report(
        self,
        match_day,
        report_summary_json: dict,
        emoji_url=None,
        complete=False,
        start_time: datetime = None,
    ):
        embed = discord.Embed(
            title=f"MD {match_day}: Replay Processing Report",
            color=discord.Color.blue(),
        )

        if emoji_url:
            embed.set_thumbnail(url=emoji_url)
        # {
        #     "role": tier_role,
        #     "index": 0,
        #     "bc_group_link": None,
        #     "success_count": 0,
        #     "total_matches": len(schedule.get(tier_role.name, {}).get(match_day, [])),
        #     "active": True | False
        #     "active_match": MATCHUP | None
        # }
        tier_summaries = []
        for tier_role, data in report_summary_json.items():
            # using standard strings
            tier_summary = (
                f"{tier_role.mention} ({data['success_count']}/{data['total_matches']})"
            )

            hyperlink = data.get("bc_hyperlink")
            if hyperlink:
                tier_summaries += f" {hyperlink}"
            else:
                link = data.get("bc_group_link")
                if link:
                    tier_summary += f" [View Group]({link})"

            if data["active"]:
                tier_summary = f"**{tier_summary} [Processing]**"
                active_match = data.get("active_match")
                if active_match:
                    tier_summary += "\n" + f"_Searching {active_match}..._"
                embed.color = tier_role.color
            tier_summaries.append(tier_summary)

        description = "\n".join(tier_summaries)

        if start_time:
            now = datetime.now()
            run_time_min = ((now - start_time).seconds) // 60
            run_time_sec = ((now - start_time).seconds) % 60
            run_time = f"{run_time_min}m {run_time_sec}s"

        if complete:
            description += "\n\n"
            success_count = sum(
                tier_data["success_count"] for tier_data in report_summary_json.values()
            )
            total_count = sum(
                tier_data["total_matches"] for tier_data in report_summary_json.values()
            )

            if success_count == total_count:
                description += f":white_check_mark: **All matches have been successfully reported! ({success_count}/{total_count})**"
                embed.color = discord.Color.green()
            else:
                embed.color = discord.Color.red()
                description += f":exclamation: **Some matches could not be found. (found {success_count}/{total_count})**"
            if start_time:
                embed.set_footer(text=f"Completed in {run_time}.")
        elif start_time:
            embed.set_footer(text=f"Run Time: {run_time}...")

        embed.description = description

        return embed

    def get_bc_missing_match_scan_report_embed(
        self,
        match_day,
        bc_scan_summary,
        start_time: datetime = None,
        emoji_url=None,
        complete=False,
    ):
        embed = discord.Embed(
            title=f"MD {match_day}: Replay Processing Report",
            color=discord.Color.blue(),
        )

        if emoji_url:
            embed.set_thumbnail(url=emoji_url)

        count_new = 0
        count_missing = 0
        # Constructs embed components for each tier
        description_components = []
        for tier_role, data in bc_scan_summary.items():
            status = data["status"]
            value = ""
            if status == "not searched":
                value = "[Pending Search]"
            elif status == "in progress":
                active_game = data["active_match"]
                value = "Searching: _{}..._\n".format(active_game)
                embed.color = tier_role.color
            if status in ["in progress", "complete"]:
                new_reports = "\n".join(data["new_reports"])
                if new_reports:
                    value += "**New Reports**\n{}\n\n".format(new_reports)

                value += "**Missing Reports**\n{}".format(
                    "\n".join(data["missing_reports"])
                    if data["missing_reports"]
                    else "[None]"
                )

            if complete:
                count_new += len(data["new_reports"])
                count_missing += len(data["missing_reports"])

            value += "\n"
            description_components.append("{}\n{}".format(tier_role.mention, value))

        if start_time:
            now = datetime.now()
            run_time_min = ((now - start_time).seconds) // 60
            run_time_sec = ((now - start_time).seconds) % 60
            run_time = f"{run_time_min}m {run_time_sec}s"

        if complete:
            total_count = sum(
                tier_data["total_matches"] for tier_data in bc_scan_summary.values()
            )

            scan_summary = "**Scan Complete**\nNew Reports Scanned: {}\nMatch Reports Missing: {}\nTotal Matches Reported: {}/{}".format(
                count_new, count_missing, total_count - count_missing, total_count
            )
            description_components.append(scan_summary)
            embed.color = (
                discord.Color.red() if count_missing else discord.Color.green()
            )

            if start_time:
                embed.set_footer(text=f"Completed in {run_time}.")

        elif start_time:
            embed.set_footer(text=f"Run Time: {run_time}...")

        embed.description = "\n".join(description_components)

        return embed

    async def tmp_download_replays(self, ctx, replay_ids) -> List[bytes]:
        """Download replay files and return list of byte objects"""
        bapi: ballchasing.Api = self.ballchasing_api[ctx.guild]
        tmp_replay_files = []
        for replay_id in replay_ids[::-1]:
            log.debug(f"Downloading replay: {replay_id}")

            replayData = await bapi.download_replay_content(replay_id)
            log.debug(f"Replay Data: {replayData.hex()[:50]}")

            tmp_replay_files.append(replayData)

        return tmp_replay_files

    def get_replay_teams_and_players(self, replay):
        blue_name = replay.get("blue", {}).get("name", "Blue").strip().title()
        orange_name = replay.get("orange", {}).get("name", "Orange").strip().title()

        blue_players = []
        for player in replay.get("blue", {}).get("players", []):
            blue_players.append(player["name"])

        orange_players = []
        for player in replay.get("orange", {}).get("players", []):
            orange_players.append(player["name"])

        return {
            "blue": {"name": blue_name, "players": blue_players},
            "orange": {"name": orange_name, "players": orange_players},
        }

    async def send_embed_to_channels(self, channels, embed: discord.Embed):
        messages = []
        for channel in channels:
            if channel:
                messages.append(await channel.send(embed=embed))
        return messages

    async def update_embed_in_messages(self, messages, embed: discord.Embed):
        for message in messages:
            await message.edit(embed=embed)

    def parse_group_code(self, code_or_link: str):
        if "group/" in code_or_link:
            code_or_link = code_or_link.split("group/")[-1]

        return code_or_link  # returns code

    async def get_player_accounts(self, player: discord.Member, platforms=[]):
        log.debug(f"Fetching player accounts for ID: {player.id}")
        url = f"{RSC_WEB_APP}/api/v1/members/{player.id}/accounts/"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
        log.debug(f"Player Account API Data: {data}")

        accounts = data.get("accounts", [])

        if not platforms:
            return accounts

        platforms = [platform.upper() for platform in platforms]
        filtered_accounts = []
        for account in accounts:
            if account.get("platform") in platforms:
                filtered_accounts.append(account)

        return filtered_accounts

    async def get_steam_ids(self, player: discord.Member):
        steam_accounts = await self.get_player_accounts(player, ["steam"])
        return [account["platform_id"] for account in steam_accounts]

    async def get_epic_ids(self, player: discord.Member):
        epic_accounts = await self.get_player_accounts(player, ["epic"])
        # Find BC epic account hash
        epic_hashes = []
        for account in epic_accounts:
            player_data = await self.get_latest_player_data_by_platform_name(
                ctx.guild, "epic", account["name"]
            )
            log.debug(f"Player Data (plat_name): {player_data}")
            plat_id = player_data.get("id", {}).get("id")
            epic_hashes.append(plat_id)
        return epic_hashes

    def generate_replay_hash(self, short_replay_json):
        # hash of replay file based on:
        # - date
        # - duration
        # - map
        # - blue, orange players
        # - blue, orange goals
        # - blue, orange pts (X - unneccessary)

        data = short_replay_json
        dt_from_replay = datetime.strptime(data.get("date"), "%Y-%m-%dT%H:%M:%S%z")
        dt_5min_hash = str(self.round_time_to_5min(dt_from_replay))
        hash_input_str = f"{dt_5min_hash}"
        hash_input_str += f"-{round(data.get('duration'), -1)}"
        hash_input_str += f"{data.get('map_code')}"
        hash_input_str += f"-{'-'.join(self.get_replay_player_names(data))}"
        hash_input_str += f"-{data.get('blue', {}).get('goals', 0)}"
        hash_input_str += f"-{data.get('orange', {}).get('goals', 0)}"

        return hash(hash_input_str)

    def round_time_to_5min(self, dt):
        seconds = (dt.replace(tzinfo=None) - dt.min).seconds
        roundUp = (seconds + 300 / 2) // 300 * 300
        return dt + timedelta(0, roundUp - seconds, -dt.microsecond)

    async def get_all_match_players(self, ctx, match_info):
        all_players = []

        for team_name in [match_info["home"], match_info["away"]]:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, team_name
            )
            team_members = self.team_manager_cog.members_from_team(
                ctx, franchise_role, tier_role
            )
            all_players += team_members

        # Put captains at beginning of list
        for player in all_players:
            if self.is_captain(player):
                all_players.remove(player)
                all_players.insert(0, player)

        return all_players

    def get_replay_player_names(self, short_replay_json, team=None):
        data = short_replay_json

        replay_players = []
        search_teams = ["blue", "orange"] if not team else [team]
        for replay_team in search_teams:
            for players in data.get(replay_team, []):
                replay_players += players

        replay_players.sort()

        return replay_players

    async def get_tier_subgroup_name(self, guild, target_tier_name):
        # self.team_manager_cog.tiers(ctx)
        tier_names = await self.team_manager_cog.config.guild(guild).Tiers()
        tier_names = [tier.lower() for tier in tier_names]

        # tier_roles = [self._get_tier_role(ctx, tier) for tier in tiers]
        target_tier_role = None
        tier_roles = []
        for role in guild.roles:
            if role.name.lower() in tier_names:
                tier_roles.append(role)
                if role.name.lower() == target_tier_name.lower():
                    target_tier_role = role
            if len(tier_roles) == len(tier_names):
                break

        tier_roles.sort(key=lambda role: role.position, reverse=True)

        return f"{tier_roles.index(target_tier_role)+1}{target_tier_name}"  # ie --> 1Premier

    # TODO: get/create channel in cat
    async def get_score_reporting_channel(self, tier_role: discord.Role):
        guild: discord.Guild = tier_role.guild
        CAT_NAME = "Score Reporting"
        tier_channel_name = f"{tier_role.name.lower()}-score-reporting"

        match_cat: discord.CategoryChannel = None
        for cat in guild.categories:
            if cat.name == CAT_NAME:
                match_cat = cat
                break

        if not match_cat:
            match_cat = await guild.create_category(CAT_NAME)

        for tier_channel in match_cat.channels:
            if tier_channel.name == tier_channel_name:
                return tier_channel

        return await match_cat.create_text_channel(tier_channel_name)

    async def get_stats_updates_channel(self, guild: discord.Guild):
        CAT_NAME = "IMPORTANT INFORMATION"
        STATS_UPDATES_CHANNLE = "stats-updates"

        important_info_cat = None
        for ii_cat in guild.categories:
            if ii_cat.name.lower() == CAT_NAME.lower():
                important_info_cat = ii_cat
                break

        for channel in important_info_cat.channels:
            if channel.name == STATS_UPDATES_CHANNLE:
                return channel

        return await ii_cat.create_text_channel(STATS_UPDATES_CHANNLE)

    async def get_match_tier_role_and_emoji_url(self, ctx, match):
        if match["report"].get("winner"):
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, match["report"]["winner"]
            )
            emoji_url = await self.team_manager_cog.get_franchise_emoji_url(
                ctx, franchise_role
            )
        else:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(
                ctx, match["home"]
            )
            emoji_url = ctx.guild.icon.url

        return tier_role, emoji_url

    async def assign_ff_reactions(self, message, deep_report):
        for react in deep_report["ff_able_reacts"]:
            await message.add_reaction(react)

    def get_select_reaction(self, int_or_hex):
        try:
            if type(int_or_hex) == int:
                return struct.pack("<I", int_or_hex).decode("utf-32le")
            if type(int_or_hex) == str:
                return struct.pack("<I", int(int_or_hex, base=16)).decode(
                    "utf-32le"
                )  # i == react_hex
        except:
            return None

    def is_captain(self, player):
        for role in player.roles:
            if role.name.lower() == "captain":
                return True
        return False

    async def get_latest_account_replay_by_plat_id(self, guild, platform, plat_id):
        """Get most recent replay by Platnium ID"""
        bapi: ballchasing.Api = self.ballchasing_api[guild]
        data = bapi.get_replays(
            player_id=f"{platform}:{plat_id}",
            sort_by="replay-date",
            sort_dir="desc",
            count=1,
        )
        async for r in data:
            return r  # Workaround `StopAsyncIteration` exception with `__anext__()` for one replay
        return None

    async def get_player_data_from_replay_by_plat_id(
        self, replay_json, platform, platform_id
    ):
        for team in ["blue", "orange"]:
            for player in replay_json[team].get("players", []):
                account_match = (
                    player.get("id", {}).get("platform", None) == platform
                    and player.get("id", {}).get("id", None) == platform_id
                )
                if account_match:
                    return player
        return {}

    async def get_latest_player_data_by_platform_name(self, guild, platform, plat_name):
        """Get latest player data by platform name"""
        bapi: ballchasing.Api = self.ballchasing_api[guild]

        data = bapi.get_replays(
            sort_by="replay-date",
            sort_dir="desc",
            player_name=plat_name,
            uploader=RSC_STEAM_ID,
            count=10,
        )

        async for replay in data:
            for team in ["blue", "orange"]:
                for player in replay[team].get("players", []):
                    account_match = (
                        player.get("id", {}).get("platform", None) == platform
                        and player.get("name", None) == plat_name
                    )
                    if account_match:
                        return player
        return {}

    async def iter_gather(result):
        """Gather async iterator into list and return"""
        final = []
        async for r in result:
            final.append(r)
        return final

    def admin_or_permissions():
        pass

    # endregion

    # endregion

    # region json db
    async def _get_bc_auth_token(self, guild: discord.Guild):
        return await self.config.guild(guild).AuthToken()

    async def _save_bc_auth_token(self, guild: discord.Guild, token):
        await self.config.guild(guild).AuthToken.set(token)

    async def _save_top_level_group(self, guild: discord.Guild, group_id):
        await self.config.guild(guild).TopLevelGroup.set(group_id)

    async def _get_top_level_group(self, guild: discord.Guild):
        return await self.config.guild(guild).TopLevelGroup()

    async def _save_time_zone(self, guild, time_zone):
        await self.config.guild(guild).TimeZone.set(time_zone)

    async def _get_time_zone(self, guild):
        return await self.config.guild(guild).TimeZone()

    async def _get_log_channel(self, guild: discord.Guild):
        return guild.get_channel(await self.config.guild(guild).LogChannel())

    async def _save_log_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ):
        await self.config.guild(guild).LogChannel.set(channel.id)

    async def _get_stats_manager_role(self, guild: discord.Guild):
        return guild.get_role(await self.config.guild(guild).StatsManagerRole())

    async def _save_stats_manager_role(self, guild: discord.Guild, role: discord.Role):
        await self.config.guild(guild).StatsManagerRole.set(role.id)


# endregion
