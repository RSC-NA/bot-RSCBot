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

import tempfile
import asyncio
from pytz import all_timezones_set, timezone, UTC
from datetime import datetime
import ballchasing

log = logging.getLogger("red.RSCBot.bcManager")

defaults = {
    "ReplayDumpChannel": None,
    "AuthToken": None,
    "TopLevelGroup": None,
    "TimeZone": 'America/New_York',
    "LogChannel": None
}

verify_timeout = 30
DONE = "Done"

class BCManager(commands.Cog):
    """Manages aspects of Ballchasing Integrations with RSC"""

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=1234567893, force_registration=True)
        self.config.register_guild(**defaults)

        self.bot = bot
        self.team_manager_cog : TeamManager = bot.get_cog("TeamManager")
        self.match_cog : Match = bot.get_cog("Match")
        self.ballchasing_api = {}
        self.task = asyncio.create_task(self.pre_load_data())

# region admin commands
   
    # region setup
    @commands.command(aliases=['setAuthKey'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setAuthToken(self, ctx, auth_token):
        """Sets the Auth Key for Ballchasing API requests.
        Note: Auth Token must be generated from the Ballchasing group owner
        """
        await ctx.message.delete()
        try:
            api = ballchasing.Api(auth_token)
        except ValueError:
            return await ctx.send(":x: The Auth Token you've provided is invalid.")

        if api:
            self.ballchasing_api[ctx.guild] = api
            await self._save_auth_token(ctx.guild, auth_token)

            if await self._get_top_level_group(ctx.guild):
                await self._save_top_level_group(ctx.guild, None)
                return await ctx.send(f":white_check_mark: {DONE}. Top Level Group has been cleared.")
            else:
                return await ctx.send(f":white_check_mark: {DONE}")

        await ctx.send(":x: The Auth Token you've provided is invalid.")

    @commands.command(aliases=['setLeagueSeasonGroup', 'stlg'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setTopLevelGroup(self, ctx, top_level_group):
        """Sets the Top Level Ballchasing Replay group for saving match replays.
        Note: Auth Token must be generated from the Ballchasing group owner
        """
        
        top_level_group = self.parse_group_code(top_level_group)

        bapi : ballchasing.Api = self.ballchasing_api[ctx.guild]
        data = bapi.get_group(top_level_group)

        if bapi.ping().get("steam_id") != data.get("creator", {}).get("steam_id", {}):
            return await ctx.send(":x: Ballchasing group creator must be consistent with the registered auth token.")

        await self._save_top_level_group(ctx.guild, top_level_group)

        bapi.patch_group(top_level_group, shared=True)

        await ctx.send(DONE)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setBCLogChannel(self, ctx, channel: discord.TextChannel=None):
        await self._save_log_channel(ctx.guild, channel)
        await ctx.send(DONE)
    
    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def getBCLogChannel(self, ctx):
        channel = await self._get_log_channel(ctx.guild)
        await ctx.reply(channel.mention)

    @commands.guild_only()
    @commands.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setTimeZone(self, ctx, time_zone):
        """Sets timezone for the guild. Valid time zone codes are listed in the "TZ database name" column of
         the following wikipedia page: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"""

        if time_zone not in all_timezones_set:
            wiki = 'https://en.wikipedia.org/wiki/List_of_tz_database_time_zones'

            msg = (f':x: **{time_zone}** is not a valid time zone code. Please select a time zone from the "TZ database name" column '
                   f'from this wikipedia page: {wiki}')

            return await ctx.send(msg)

        await self._save_time_zone(ctx.guild, time_zone)
        await ctx.reply("Done")

    # endregion

    # region normal use
    @commands.command(aliases=['reportAllMatches', 'ram'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def reportMatches(self, ctx, match_day: int=None):
        log.debug("Reporting matches...")
        if not match_day:
            match_day = await self.match_cog._match_day(ctx)
        
        match_day = str(match_day)
        
        tiers = await self.team_manager_cog.tiers(ctx)
        tier_roles = [self.team_manager_cog._get_tier_role(ctx, tier) for tier in tiers]
        tier_roles.sort(key=lambda role: role.position, reverse=True)

        schedule = await self.match_cog._schedule(ctx)

        all_missing_replays = {}

        # Prep Report Status Message
        log.debug(f"Tier Roles: {tier_roles}")
        bc_report_summary_json = {}
        for tier_role in tier_roles:
            bc_report_summary_json[tier_role] = {
                "role": tier_role,
                "index": 0,
                "success_count": 0,
                "bc_group_link": None,
                "total_matches": len(schedule.get(tier_role.name, {}).get(match_day, [])),
                "active": False
            }
        
        guild_emoji_url = ctx.guild.icon_url
        channels = list(set([ctx.channel, (await self._get_log_channel(ctx.guild))]))
        status_messages = await self.send_ram_message(channels, self.get_bc_match_day_status_report(match_day, bc_report_summary_json, guild_emoji_url))
        # TODO: remove: processing_status_msg = await ctx.send(embed=self.get_bc_match_day_status_report(match_day, bc_report_summary_json, guild_emoji_url))

        # Process/Report All Replays
        for tier_role in tier_roles:
            bc_report_summary_json[tier_role]['active'] = True
            missing_tier_replays = []
            tier_md_group_id = None
            tier_report_channel = await self.get_score_reporting_channel(tier_role)
            for match in schedule.get(tier_role.name, {}).get(match_day, []):
                match_group_info = {}
                # update status message
                # TODO: remove: await processing_status_msg.edit(embed=self.get_bc_match_day_status_report(match_day, bc_report_summary_json, guild_emoji_url))
                await self.update_messages(status_messages, embed=self.get_bc_match_day_status_report(match_day, bc_report_summary_json, guild_emoji_url))
                # update status embed
                bc_report_summary_json[tier_role]['index'] += 1
                
                if match.get("report", {}):
                    await self.send_match_summary(ctx, match, tier_report_channel)
                    bc_report_summary_json[tier_role]['success_count'] += 1
                else:
                    match_group_info = await self.process_match_bcreport(ctx, match, tier_md_group_code=tier_md_group_id, report_channel=tier_report_channel)
                    

                    if not tier_md_group_id and match_group_info.get('is_valid_set', False):
                        tier_md_group_id = match_group_info.get("tier_md_group_id")
                        tier_md_group_link = f"https://ballchasing.com/group/{tier_md_group_id}"
                        log.debug(f"MD Group ID: {tier_md_group_id}")
                        log.debug(f"BC Report Tier Role: {tier_role}")
                        log.debug(f"BC Report Summary JSON: {bc_report_summary_json[tier_role]}")
                        log.debug(f"BC Group Link: {bc_report_summary_json[tier_role]['bc_group_link']}")
                        bc_report_summary_json[tier_role]['bc_group_link'] = tier_md_group_link
                    
                    if not match_group_info.get('is_valid_set', False):
                        missing_tier_replays.append(match)
                    else:
                        bc_report_summary_json[tier_role]['success_count'] += 1
                
            if missing_tier_replays:
                all_missing_replays[tier_role.name] = missing_tier_replays
            
            bc_report_summary_json[tier_role]['active'] = False
        
        # update status message
        # TODO: remove: await processing_status_msg.edit(embed=self.get_bc_match_day_status_report(match_day, bc_report_summary_json, emoji_url=guild_emoji_url, complete=True))
        await self.update_messages(status_messages, embed=self.get_bc_match_day_status_report(match_day, bc_report_summary_json, emoji_url=guild_emoji_url, complete=True))     
    
    @commands.command(aliases=['rff', 'reportFF'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def reportForfeits(self, ctx, match_day, team_a, team_b):
        match = await self.get_matchup(ctx, match_day, team_a, team_b)
        if not match:
            return await ctx.reply(f":x: No match could be found for **{team_a} vs {team_b}** on match day {match_day}.")
        
        deep_match_report, embed = await self.get_score_deep_summary_and_embed(ctx, match)
        message = await ctx.reply(embed=embed)

    @commands.command(aliases=['mmr'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def missingMatchReport(self, ctx):
        await self.process_missing_replays(ctx) #, all_missing_replays)  

    @commands.command(aliases=['mrm', 'manuallyUpdateMatch', 'mum'])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def manualReport(self, ctx, match_day: int, bc_match_link_or_id):
        match_code = self.parse_group_code(bc_match_link_or_id)
        
        bapi : ballchasing.Api = self.ballchasing_api[ctx.guild]

        data = bapi.get_group(match_code)
        name = data.get("name")
        teams = name.split(" vs ")

        match = None
        matches = await self.match_cog.get_team_matches(ctx, teams[0], str(match_day))
        for m in matches:
            match_teams = [m['home'], m['away']]
            if set(teams) == set(match_teams):
                match = m
                break
        
        if not match:
            return await ctx.reply(":x: No match could be found in association with this match day and group.")
        
        destination_data = await self.get_replay_destination(ctx, match)

        if destination_data['id'] != match_code:
            return await ctx.reply(":x: Something went wrong.")
        
        tier_role : discord.Role = (await self.team_manager_cog._roles_for_team(ctx, teams[0]))[1]


        discovery_data = {
            "winner": None,
            "home_wins": 0,
            "away_wins": 0,
            "summary": None,
        }
        bc_group_data = {
            "id": match_code,
            "ballchasing_link": f"https://ballchasing.com/group/{match_code}"
        }


        replays = bapi.get_replays(group_id=match_code)

        for replay in replays:

            home_goals, away_goals = self.get_home_away_goals(match, replay)

            if home_goals > away_goals:
                discovery_data['home_wins'] += 1
            else:
                discovery_data['away_wins'] += 1
            
        discovery_data['summary'] = f"**{match['home']}** {discovery_data['home_wins']} - {discovery_data['away_wins']} **{match['away']}**"

        if discovery_data['home_wins'] > discovery_data['away_wins']:
            discovery_data['winner'] = match['home']
        elif discovery_data['away_wins'] > discovery_data['home_wins']:
            discovery_data['winner'] = match['away']

        match = await self.update_match_info(ctx, tier_role.name, match, discovery_data, bc_group_data)
        sr_channel = await self.get_score_reporting_channel(tier_role)
        await self.send_match_summary(ctx, match, sr_channel)
        await ctx.reply(DONE)

    # endregion

# endregion 

# region player commands 
    @commands.command(aliases=['bcr', 'bcpull'])
    @commands.guild_only()
    async def bcreport(self, ctx, match_day: int=None): # , team_name=None, match_day=None):
        """Finds match games from recent public uploads, and adds them to the correct Ballchasing subgroup
        """        
        await self.process_bcreport(ctx, match_day=match_day)
    
    @commands.command(aliases=['fbcr', 'fbcpull'])
    @commands.guild_only()
    async def forcebcreport(self, ctx, match_day: int=None): # , team_name=None, match_day=None):
        """Finds match games from recent public uploads, and adds them to the correct Ballchasing subgroup
        """        
        await self.process_bcreport(ctx, True, match_day=match_day)
    
    @commands.command(aliases=['bcGroup', 'ballchasingGroup', 'bcg'])
    @commands.guild_only()
    async def bcgroup(self, ctx):
        """Links to the top level ballchasing group for the current season."""
        group_code = await self._get_top_level_group(ctx.guild)
        url = f"https://ballchasing.com/group/{group_code}"
        if group_code:
            await ctx.send(f"See all season replays in the top level ballchasing group: {url}")
        else:
            await ctx.send(":x: A ballchasing group has not been set for this season.")

    @commands.command(aliases=['accs', 'myAccounts', 'registeredAccounts'])
    @commands.guild_only()
    async def accounts(self, ctx):
        """View all accounts that have been registered to with your discord account in this guild."""
        await ctx.send("None lmao")

# endregion

# region helper functions
    
    # region primary helpers
    
    async def pre_load_data(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            token = await self._get_auth_token(guild)
            if token:
                self.ballchasing_api[guild] = ballchasing.Api(token)

    async def process_bcreport(self, ctx, force=False, match_day: int=None):
        # Step 1: Find Match
        player = ctx.author
        matches = await self.get_matches(ctx, player, match_day=match_day)
        if not matches:
            return await ctx.send(":x: No matches found.")
        
        for match in matches:
            if not match.get("report", {}) or force:
                await self.process_match_bcreport(ctx, match)
            else:
                await self.send_match_summary(ctx, match)
        
    async def process_match_bcreport(self, ctx, match, tier_md_group_code: str=None, report_channel: discord.TextChannel=None):
        # Step 0: Constants
        SEARCHING = "Searching https://ballchasing.com for publicly uploaded replays of this match..."
        FOUND_AND_UPLOADING = "\n:signal_strength: Results confirmed. Creating a ballchasing replay group. This may take a few seconds..."
        SUCCESS_EMBED = "Match Summary:\n{}\n\n[Click to view the group on ballchasing!]({})"
        
        if not report_channel:
            report_channel = ctx.channel

        # Step 2: Send initial embed (Searching...)
        match_day = match['matchDay']
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, match['home'])
        emoji_url = ctx.guild.icon_url

        embed = discord.Embed(
            title=f"Match Day {match_day}: {match['home']} vs {match['away']}",
            description=SEARCHING,
            color=tier_role.color
        )
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)
        bc_status_msg = await report_channel.send(embed=embed)

        # Step 3: Search for replays on ballchasing
        discovery_data = await self.find_match_replays(ctx, match)

        ## Not found:
        if not discovery_data.get("is_valid_set", False):
            embed.description = discovery_data['summary']
            await bc_status_msg.delete()
            return {}

        ## Found:
        winner = discovery_data.get('winner')
        if winner:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, winner)
            emoji = await self.team_manager_cog._get_franchise_emoji(ctx, franchise_role)
            if emoji:
                embed.set_thumbnail(url=emoji.url)
        
        # Step 4: Send updated embed (Status: found, uploading)
        embed.description = "Match Summary:\n{}\n{}".format(discovery_data.get('summary'), FOUND_AND_UPLOADING)
        await bc_status_msg.edit(embed=embed)
        
        # Find or create ballchasing subgroup
        match_subgroup_json = await self.get_replay_destination(ctx, match, tier_md_group_code=tier_md_group_code)
        match_subgroup_id = match_subgroup_json.get('id')

        tmp_replay_files = await self.tmp_download_replays(ctx, discovery_data.get('match_replay_ids', []))
        uploaded_ids = await self.upload_replays(ctx, match_subgroup_id, tmp_replay_files)
        
        # renamed = await self._rename_replays(ctx, uploaded_ids)

        # Step 5: Group created, Finalize embed
        embed.description = SUCCESS_EMBED.format(discovery_data.get('summary'), match_subgroup_json.get('link'))
        await bc_status_msg.edit(embed=embed)

        # Step 6: Update match cog info
        await self.update_match_info(ctx, tier_role.name, match, discovery_data, match_subgroup_json)

        match_subgroup_json['is_valid_set'] = discovery_data['is_valid_set']

        return match_subgroup_json

    async def get_score_deep_summary_and_embed(self, ctx, match):
        title = f"Match Day {match['matchDay']}: {match['home']} vs {match['away']}"
        tier_role, match_emoji_url = await self.get_match_tier_role_and_emoji_url(ctx, match)
        
        home_franchise_role = (await self.team_manager_cog._roles_for_team(ctx, match['home']))[0]
        away_franchise_role = (await self.team_manager_cog._roles_for_team(ctx, match['away']))[0]
        home_emoji = await self.team_manager_cog._get_franchise_emoji(ctx, home_franchise_role)
        away_emoji = await self.team_manager_cog._get_franchise_emoji(ctx, away_franchise_role)

        bapi : ballchasing.Api = self.ballchasing_api[ctx.guild]

        replays = bapi.get_replays(group_id=match['report']['ballchasing_id'])

        description = "Match Summary\n" + match['report']['summary'] + "\n"
        description += "\n**Game Breakdown**"
        game_summaries = []
        for replay in replays:
            home_goals, away_goals = self.get_home_away_goals(match, replay)
            winner_emoji = home_emoji if home_goals > away_goals else away_emoji
            summary = f"{match['home']} {home_goals} - {away_goals} {match['away']} {winner_emoji}"
            game_summaries.append({
                "summary": summary,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "replay": replay
            })
            
            description += "\n" + summary 

        embed = discord.Embed(title=title, description=description, color=tier_role.color)
        if match_emoji_url:
            embed.set_thumbnail(url=match_emoji_url)

        deep_match_report = {
            "home_emoji": home_emoji,
            "away_emoji": away_emoji,
            "game_summaries": game_summaries
        }


        return deep_match_report, embed

    async def get_matchup(self, ctx, match_day, team_a, team_b):
        matches = await self.get_matches(ctx, team=team_a, match_day=match_day)
        search_teams = [team_a.lower(), team_b.lower()]
        for match in matches:
            match_teams = [match['home'].lower(), match['away'].lower()]
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
        all_players = await self.get_all_match_players(ctx, match)

        # All of this data should be tracked to optimize the search and validation
        discovery_data = {
            "is_valid_set": False,
            "match_format": match.get("format_type", "4-GS"),
            "summary": None,
            "match_replay_ids": [],
            "replay_hashes": [],
            "latest_replay_end": None,
            "home_wins": 0,
            "away_wins": 0,
            "winner": None,
            "accounts_searched": [],
            "players_searched": []
        }
        
        guild = ctx.guild
        try:
            bapi : ballchasing.Api = self.ballchasing_api[guild]
        except KeyError:
            error_str = ":x: A ballchasing token has not been set for this guild."
            discovery_data['summary'] = error_str 
            return discovery_data

        # Prep initial date search range
        # match_date = datetime.strptime(match['matchDate'], '%B %d, %Y').strftime('%Y-%m-%d')
        # match_start_dt = BCConfig.START_MATCH_DT_TMPLT.format(match_date, BCConfig.ZONE_ADJ)
        # match_end_dt = BCConfig.END_MATCH_DT_TMPLT.format(match_date, BCConfig.ZONE_ADJ)

        guild_timezone = await self._get_time_zone(ctx.guild)

        # Localized Datetime
        dt_match_start = datetime.strptime(f"{match['matchDate']} 9:00PM", '%B %d, %Y %I:%M%p').astimezone(timezone(guild_timezone))
        dt_match_end = datetime.strptime(f"{match['matchDate']} 11:59PM", '%B %d, %Y %I:%M%p').astimezone(timezone(guild_timezone))

        # RFC3339 Formatted UTC time
        utc_dt_open_search_range_str = dt_match_start.astimezone(UTC).strftime(BCConfig.utc_strftime_fmt)
        utc_dt_close_search_range_str = dt_match_end.astimezone(UTC).strftime(BCConfig.utc_strftime_fmt)

        # Search all players in game for replays until match is found
        
        for player in all_players:
            for steam_id in (await self.get_steam_ids(ctx.guild, player)):

                data = await asyncio.to_thread(
                    bapi.get_replays,
                    playlist=BCConfig.PLAYLIST,
                    sort_by=BCConfig.SORT_BY,
                    sort_dir=BCConfig.SORT_DIR,
                    replay_after=utc_dt_open_search_range_str,
                    replay_before=utc_dt_close_search_range_str,
                    uploader=steam_id
                )

                # checks for MATCHing ;) replays
                for replay in data:
                    if self.is_valid_match_replay(match, replay):
                        # replay_ids.append(replay['id'])
                        replay_hash = self.generate_replay_hash(replay)
                        if replay_hash not in discovery_data['replay_hashes']:
                            discovery_data['replay_hashes'].append(replay_hash)
                            discovery_data['match_replay_ids'].append(replay['id'])

                            home_goals, away_goals = self.get_home_away_goals(match, replay)

                            if home_goals > away_goals:
                                discovery_data['home_wins'] += 1
                            else:
                                discovery_data['away_wins'] += 1
                    else:
                        pass
                
                # update accounts searched to avoid duplicate searches (maybe not needed)
                discovery_data['accounts_searched'].append(steam_id)

                # see if replay set is valid
                is_valid_set = self.is_valid_replay_set(discovery_data)

                # Update disco data with current info
                discovery_data['is_valid_set'] = is_valid_set
                discovery_data['summary'] = f"**{match['home']}** {discovery_data['home_wins']} - {discovery_data['away_wins']} **{match['away']}**"
                # discovery_data['match_replay_ids'] = discovery_data.get('match_replay_ids', []) + replay_ids

                winner = None
                if discovery_data['home_wins'] > discovery_data['away_wins']:
                    winner = match['home']
                elif discovery_data['home_wins'] < discovery_data['away_wins']:
                    winner = match['away']

                discovery_data['winner'] = winner

                if discovery_data.get("is_valid_set", False):
                    return discovery_data
        
            # update players searched to avoid duplicate searches (maybe not needed)
            discovery_data['players_searched'].append(player)

        return discovery_data

    async def get_replay_destination(self, ctx, match, tier_md_group_code=None):
        
        # Ballchasing subgroup structure:
        # RSC/<top level group>/<match type>/<tier num><tier>/Match Day <match day>/<Home> vs <Away>
    
        if not tier_md_group_code:
            # The path to the match subgroup is unknown and must be discovered
            tier = (await self.team_manager_cog._roles_for_team(ctx, match['home']))[1].name  # Get tier role's name
            tier_group = await self.get_tier_subgroup_name(ctx.guild, tier)
            top_level_group = await self._get_top_level_group(ctx.guild)
            ordered_subgroup_names = [
                match.get("match_type", "Regular Season"),
                tier_group,
                f"Match Day {str(match['matchDay']).zfill(2)}",
                f"{match['home']} vs {match['away']}"
            ]
            
        else:
            # The parent group for the match group has already been determined
            top_level_group = tier_md_group_code
            ordered_subgroup_names = [
                f"{match['home']} vs {match['away']}".title()
            ]

        # Begin Ballchasing Group Mgmt
        bapi : ballchasing.Api = self.ballchasing_api[ctx.guild]
        data = bapi.get_groups(group=top_level_group)

        # Dynamically create sub-group
        current_subgroup_id = top_level_group
        next_subgroup_id = None
        for next_group_name in ordered_subgroup_names:
            if next_subgroup_id:
                current_subgroup_id = next_subgroup_id
            next_subgroup_id = None 

            # Check if next subgroup exists
            for data_subgroup in data:
                if data_subgroup['name'] == next_group_name:
                    next_subgroup_id = data_subgroup['id']
                    break
            
            # Prepare & Execute  Next request:
            # ## Next subgroup found: request its contents
            if next_subgroup_id:
                data = bapi.get_groups(group=next_subgroup_id)

            # ## Creating next sub-group
            else:
                data = bapi.create_group(name=next_group_name, parent=current_subgroup_id,
                                    player_identification=BCConfig.player_identification,
                                    team_identification=BCConfig.team_identification)
                
                next_subgroup_id = data['id']

                if next_group_name is not ordered_subgroup_names[-1]:
                    data = bapi.get_groups(group=next_subgroup_id)

        # After we create match subgroup
        return {
            "id": next_subgroup_id,
            "tier_md_group_id": current_subgroup_id,
            "link": f"https://ballchasing.com/group/{next_subgroup_id}"
        }

    async def upload_replays(self, ctx, subgroup_id, files_to_upload):
        replay_ids_in_group = []
        for replay_file in files_to_upload:
            replay_file.seek(0)
            files = {'file': replay_file}

            bapi : ballchasing.Api = self.ballchasing_api[ctx.guild]

            # bapi.upload_replay(replay_file, visibility=bcConfig.visibility, group=)
            try:
                data = bapi._request(f"/v2/upload", bapi._session.post, files=files,
                                    params={"group": subgroup_id, "visibility": BCConfig.visibility}).json()
                replay_ids_in_group.append(data.get('id', "FAILED"))
            except ValueError as e:
                if e.args[0].status_code == 409:
                    # duplicate replay
                    replay_id = e.args[1].get('id', "FAILED")
                    bapi.patch_replay(replay_id, group=subgroup_id)
                    replay_ids_in_group.append(replay_id)
            
        return replay_ids_in_group

    # TODO
    async def process_missing_replays(self, ctx): #, missing_replays: dict):
        # Step 0: Load old missing replays
        missing_matches = await self.match_cog.get_unreported_matches(ctx)

        # Step 1: search ballchasing for old missing replays, update old missing replays

        # Step 2: re-search missing replays, update new missing replays

        # Step 3: combine old and new missing replays data set

        # Step 4: generate missing replays report message
        missing_replays_report = await self.generate_missing_replays_msg(ctx.guild, missing_matches)

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
                if match['matchDay'].isdigit():
                    tier_str += f"{match['home']} vs {match['away']} - MD{match['matchDay']}"
                else:
                    tier_str += f"{match['home']} vs {match['away']} - MD-{match['matchDay']}"
                    mt = match.get('matchType')
                    if mt:
                        tier_str += f" ({mt})"

            tier_str += "\n```\n"

            tier_chunks.append(tier_str)
        
        report = ""
        report += "\n".join(tier_chunks)

        ballchasing_link = await self._get_top_level_group(guild)
        report += "\n"
        report += f"RSC Ballchasing group: <https://ballchasing.com/group/{ballchasing_link}>"
        report += "\nRSC Match Day Rules: <https://tinyurl.com/MatchDayRules>"
        
        return report

    # endregion

    # region validations

    def is_full_replay(self, replay_data):
        if replay_data['duration'] < 300:
            return False
        
        blue_goals = replay_data['blue']['goals'] if 'goals' in replay_data['blue'] else 0
        orange_goals = replay_data['orange']['goals'] if 'goals' in replay_data['orange'] else 0
        if blue_goals == orange_goals:
            return False
        for team in ['blue', 'orange']:
            for player in replay_data[team]['players']:
                if player['start_time'] == 0:
                    return True
        return False

    def is_valid_match_replay(self, match, replay_data):
        match_day = match['matchDay']   # match cog
        home_team = match['home']       # match cog
        away_team = match['away']       # match cog

        if not self.is_full_replay(replay_data):
            return False

        replay_teams = self.get_replay_teams_and_players(replay_data)

        home_team_found = replay_teams['blue']['name'].lower() in home_team.lower() or replay_teams['orange']['name'].lower() in home_team.lower()
        away_team_found = replay_teams['blue']['name'].lower() in away_team.lower() or replay_teams['orange']['name'].lower() in away_team.lower()

        return home_team_found and away_team_found

    def get_replay_team_data(self, replay):
        try:
            blue_name = replay.get('blue', {}).get('name', '').title()
        except:
            blue_name = "Blue"
        try:
            orange_name = replay.get('orange', {}).get('name', '').title()
        except:
            orange_name = "Orange"

        blue_players = []
        for player in replay.get('blue', {}).get('players', []):
            player_name = player.get('name')
            if player_name:
                blue_players.append(player_name)
        
        orange_players = []
        for player in replay.get('orange', {}).get('players', []):
            player_name = player.get('name')
            if player_name:
                orange_players.append(player_name)
        
        team_data = {
            'blue': {
                'name': blue_name,
                'players': blue_players
            },
            'orange': {
                'name': orange_name,
                'players': orange_players
            }
        }
        return team_data

    def is_valid_replay_set(self, discovery_data):
        match_format = discovery_data.get('match_format', '4-gs').lower()
        format_components = match_format.split('-')

        for component in format_components:
            if component.isdigit():
                num_games = int(component)
                break
        
        format_components.remove(str(num_games))
        format_type = format_components[0]

        if format_type == 'gs':
            gp = discovery_data.get('home_wins', 0) + discovery_data.get('away_wins', 0)
            return (gp == num_games)

        elif format_type == 'bo':
            winning_team_wins = int(num_games/2) + 1 
            return (
                discovery_data.get('home_wins', 0) == winning_team_wins
                or
                discovery_data.get('away_wins', 0) == winning_team_wins
            )
        
        return False

    # endregion 

    # region secondary helpers

    def get_home_away_goals(self, match, replay):
        if (replay.get('blue', {}).get('name', 'blue').lower() in match.get('home', '').lower()
            or replay.get('orange', {}).get('name', 'orange').lower() in match.get('away', '').lower()):
            home = 'blue'
            away = 'orange'
        elif (replay.get('orange', {}).get('name', 'orange').lower() in match.get('home', '').lower()
            or replay.get('blue', {}).get('name', 'blue').lower() in match.get('away', '').lower()):
            home = 'orange'
            away = 'blue'
        else:
            return None, None
        
        home_goals = replay[home].get('goals', 0)
        away_goals = replay[away].get('goals', 0)

        return home_goals, away_goals

    async def update_match_info(self, ctx, tier, match, discovery_data, bc_group_data):
        report = {
            "winner": discovery_data.get('winner'),
            "home_wins": discovery_data.get('home_wins'),
            "away_wins": discovery_data.get('away_wins'),
            "summary": discovery_data.get('summary'),
            "ballchasing_id": bc_group_data.get('id'),
            "ballchasing_link": bc_group_data.get('link', 
                f"https://ballchasing.com/group/{bc_group_data.get('id')}")
        }

        schedule = await self.match_cog._schedule(ctx)
        match_index = self.match_cog.get_match_index_in_day(schedule, tier, match)

        schedule[tier][match['matchDay']][match_index]['report'] = report

        await self.match_cog._save_schedule(ctx, schedule)
        
        match['report'] = report
        return match

    async def send_match_summary(self, ctx, match, report_channel: discord.TextChannel=None):
        title = f"Match day {match['matchDay']}: {match['home']} vs {match['away']}"

        if report_channel:
            description = "Match Summary:\n{}\n\n".format(match['report']['summary'])
        else:
            description = "This match has already been reported:\n{}\n\n".format(match['report']['summary'])
            report_channel = ctx.channel
        
        description += f"[Click here to view this group on ballchasing!]({match['report']['ballchasing_link']})"

        tier_role, emoji_url = await self.get_match_tier_role_and_emoji_url(ctx, match)
        embed = discord.Embed(title=title, description=description, color=tier_role.color)
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)
        
        await report_channel.send(embed=embed)
    
    def get_bc_match_day_status_report(self, match_day, report_summary_json: dict, emoji_url = None, complete=False):
        embed = discord.Embed(title=f"Replay Processing Report: Match Day {match_day}", color=discord.Color.blue())
        
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)
        # {
        #     "role": tier_role,
        #     "index": 0,
        #     "bc_group_link": None,
        #     "success_count": 0,
        #     "total_matches": len(schedule.get(tier_role.name, {}).get(match_day, [])),
        #     "active": False
        # }
        tier_summaries = []
        for tier_role, data in report_summary_json.items():
            # using standard strings
            tier_summary = f"{tier_role.mention} ({data['success_count']}/{data['total_matches']})"
            link = data.get('bc_group_link')
            if link:
                tier_summary += f" [View Group]({link})"  

            if data['active']:
                tier_summary = f"**{tier_summary} [Processing]**"
                embed.color = tier_role.color
            tier_summaries.append(tier_summary)

            # # using embed fields
            # value_str = f"Replay Processing Summary: {data['success_count']}/{data['total']}"
            # if data['active']:
            #     value_str = f"**{value_str}**"
            # embed.add_field(name=tier_role.name, value=value_str)
        
        description = '\n\n'.join(tier_summaries)

        if complete:
            description += "\n\n"
            success_count = sum(tier_data['success_count'] for tier_data in report_summary_json.values())
            total_count = sum(tier_data['total_matches'] for tier_data in report_summary_json.values())

            if success_count == total_count:
                description += f":white_check_mark: **All matches have been successfully reported! ({success_count}/{total_count})**"
                embed.color = discord.Color.green()
            else:
                embed.color = discord.Color.red()
                description += f":exclamation: **Some matches could not be found. (found {success_count}/{total_count})**"
            
        embed.description = description
        return embed

    async def tmp_download_replays(self, ctx, replay_ids):
        bapi : ballchasing.Api = self.ballchasing_api[ctx.guild]
        tmp_replay_files = []
        this_game = 1
        for replay_id in replay_ids[::-1]:
            endpoint = f"/replays/{replay_id}/file"

            r = bapi._request(endpoint, bapi._session.get)
            # replay_filename = f"{replay_id}.replay"
            
            tf = tempfile.NamedTemporaryFile()
            tf.name += ".replay"
            tf.write(r.content)
            tmp_replay_files.append(tf)
            this_game += 1

        return tmp_replay_files

    def get_replay_teams_and_players(self, replay):
        
        blue_name = replay.get('blue', {}).get('name', 'Blue').strip().title()
        orange_name = replay.get('orange', {}).get('name', 'Orange').strip().title()

        blue_players = []
        for player in replay.get('blue', {}).get('players', []):
            blue_players.append(player['name'])
        
        orange_players = []
        for player in replay.get('orange', {}).get('players', []):
            orange_players.append(player['name'])
        
        return {
            'blue': {
                'name': blue_name,
                'players': blue_players
            },
            'orange': {
                'name': orange_name,
                'players': orange_players
            }
        }
    
    async def send_ram_message(self, channels, embed: discord.Embed):
        messages = []
        for channel in channels:
            if channel:
                message = await channel.send(embed=embed)
                messages.append(message)
        return messages

    async def update_messages(self, messages, embed: discord.Embed):
        for message in messages:
            await message.edit(embed=embed)

    def parse_group_code(self, code_or_link: str):
        if 'group/' in code_or_link:
            code_or_link = code_or_link.split('group/')[-1]
        
        return code_or_link  # returns code

    # TODO: update to lookup request
    async def get_steam_ids(self, guild, player: discord.Member):    
        return ['76561198380344413', '76561199064986643']

    def generate_replay_hash(self, short_replay_json):
        # hash of replay file based on:
        # - date
        # - duration
        # - map
        # - blue, orange players
        # - blue, orange goals
        # - blue, orange pts (X - unneccessary)

        data = short_replay_json
        hash_input_str = f"{data.get('date')}-{data.get('duration')}-{data.get('map_code')}"
        hash_input_str += f"-{'-'.join(self.get_replay_player_names(data))}"
        hash_input_str += f"-{data.get('blue', {}).get('goals', 0)}"
        hash_input_str += f"-{data.get('orange', {}).get('goals', 0)}"

        return hash(hash_input_str)

    async def get_all_match_players(self, ctx, match_info):
        all_players = []
        
        for team_name in [match_info['home'], match_info['away']]:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, team_name)
            team_members = self.team_manager_cog.members_from_team(ctx, franchise_role, tier_role)
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
        search_teams = ['blue', 'orange'] if not team else [team]
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
        guild : discord.Guild = tier_role.guild
        CAT_NAME = "Score Reporting"
        tier_channel_name = f"{tier_role.name.lower()}-score-reporting"

        match_cat : discord.CategoryChannel = None
        for cat in guild.categories:
            if cat.name == CAT_NAME:
                match_cat = cat 
                break
        
        if not match_cat:
            match_cat = await guild.create_category(CAT_NAME)
        
        for tier_channel in match_cat.channels:
            if tier_channel.name == tier_channel_name:
                return tier_channel

        return await match_cat.create_text_channel(tier_channel_name, sync=True)

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

        return await ii_cat.create_text_channel(STATS_UPDATES_CHANNLE, sync=True)

    async def get_match_tier_role_and_emoji_url(self, ctx, match):
        if match['report'].get('winner'):
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, match['report']['winner'])
            emoji = await self.team_manager_cog._get_franchise_emoji(ctx, franchise_role)
        else:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, match['home'])
        
        emoji_url = None
        if emoji:
            emoji_url = emoji.url
        elif ctx.guild.icon_url:
            emoji_url = ctx.guild.icon_url
        
        return tier_role, emoji_url

    def is_captain(self, player):
        for role in player.roles:
            if role.name.lower() == "captain":
                return True
        return False
        
    # endregion

# endregion

# region json

    async def _get_auth_token(self, guild: discord.Guild):
        return await self.config.guild(guild).AuthToken()
    
    async def _save_auth_token(self, guild: discord.Guild, token):
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
    
    async def _save_log_channel(self, guild: discord.Guild, channel: discord.TextChannel):
        await self.config.guild(guild).LogChannel.set(channel.id)
    
# endregion
