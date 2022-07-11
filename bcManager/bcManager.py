from tkinter import Toplevel
from .bcConfig import bcConfig
import requests
import tempfile
import discord
import asyncio
import ballchasing

from teamManager import TeamManager
from match import Match

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions
from datetime import datetime, timezone


defaults = {
    "ReplayDumpChannel": None,
    "AuthToken": None,
    "TopLevelGroup": None
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
        
        if 'group/' in top_level_group:
            top_level_group = top_level_group.split('group/')[-1]

        bapi : ballchasing.Api = self.ballchasing_api[ctx.guild]
        data = bapi.get_group(top_level_group)

        if bapi.ping().get("steam_id") != data.get("creator", {}).get("steam_id", {}):
            return await ctx.send(":x: Ballchasing group creator must be consistent with the registered auth token.")

        await self._save_top_level_group(ctx.guild, top_level_group)

        bapi.patch_group(top_level_group, shared=True)

        await ctx.send(DONE)

# endregion 

# region player commands 
    @commands.command(aliases=['bcr', 'bcpull'])
    @commands.guild_only()
    async def bcreport(self, ctx): # , team_name=None, match_day=None):
        """Finds match games from recent public uploads, and adds them to the correct Ballchasing subgroup
        """        
        await self.process_bcreport(ctx)
        
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

# region helper commands

    # region ballchasing commands
    async def _bc_get_request(self, ctx, endpoint, params=[], auth_token=None):
        if not auth_token:
            auth_token = await self._get_auth_token(ctx.guild)
        
        url = 'https://ballchasing.com/api'
        url += endpoint
        params = '&'.join(params)
        if params:
            url += "?{}".format(params)
        
        return requests.get(url, headers={'Authorization': auth_token})

    async def _bc_post_request(self, ctx, endpoint, params=[], auth_token=None, json=None, data=None, files=None):
        if not auth_token:
            auth_token = await self._get_auth_token(ctx.guild)
        
        url = 'https://ballchasing.com/api'
        url += endpoint
        params = '&'.join(params)
        if params:
            url += "?{}".format(params)
        
        return requests.post(url, headers={'Authorization': auth_token}, json=json, data=data, files=files)

    async def _bc_patch_request(self, ctx, endpoint, params=[], auth_token=None, json=None, data=None):
        if not auth_token:
            auth_token = await self._get_auth_token(ctx.guild)

        url = 'https://ballchasing.com/api'
        url += endpoint
        params = '&'.join(params)
        if params:
            url += "?{}".format(params)
        
        return requests.patch(url, headers={'Authorization': auth_token}, json=json, data=data)
    
    # endregion

    async def pre_load_data(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            token = await self._get_auth_token(guild)
            if token:
                self.ballchasing_api[guild] = ballchasing.Api(token)

    # region primary helpers

    async def process_bcreport(self, ctx):
        # Step 0: Constants
        

        SEARCHING = "Searching https://ballchasing.com for publicly uploaded replays of this match..."
        FOUND_AND_UPLOADING = "\n\n:signal_strength: Results confirmed. Creating a ballchasing replay group. This may take a few seconds..."
        SUCCESS_EMBED = "Match summary:\n{}\n\nView the ballchasing group: https://ballchasing.com/group/{}"

        # Step 1: Find Match
        player = ctx.author
        match = await self.get_match(ctx, player)
        if not match:
            return await ctx.send(":x: No match found.")
        

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
        bc_status_msg = await ctx.send(embed=embed)


        # Step 3: Search for replays on ballchasing
        discovery_data = await self.find_match_replays(ctx, match, player) #, matched_replays)

        ## Not found:
        if not discovery_data.get("is_valid_set", False):
            embed.description = discovery_data['summary']
            return await bc_status_msg.edit(embed=embed)

        ## Found:
        # discovery_data = {
        #     "is_valid_set": False,
        #     "summary": None,
        #     "match_replay_ids": [],
        #     "latest_replay_end": None,
        #     "winner": None,
        #     "accounts_searched": [],
        #     "players_searched": []
        # }
        # replay_ids, summary, winner = replays_found

        winner = discovery_data.get('winner')
        if winner:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, winner)
            emoji = await self.team_manager_cog._get_franchise_emoji(ctx, franchise_role)
            embed.set_thumbnail(url=emoji.url)
        
        # Step 4: Send updated embed (Status: found, uploading)
        embed.description = "Match summary:\n{}\n\n{}".format(discovery_data.get('summary'), FOUND_AND_UPLOADING)
        await bc_status_msg.edit(embed=embed)

        # TODO: continue here: download, upload to correct subgroup, etc

        # Step X: Group created, Finalize embed
        embed.description = SUCCESS_EMBED.format(discovery_data.get('summary'), None) # match_subgroup_id)
        await bc_status_msg.edit(embed=embed)

    async def get_match(self, ctx, member, team=None, match_day=None, match_index=0):
        return (await self.get_matches(ctx, member, team, match_day))[match_index]

    async def get_matches(self, ctx, member, team=None, match_day=None):
        if not match_day:
            match_day = await self.match_cog._match_day(ctx)
        if not team:
            team = (await self.team_manager_cog.teams_for_user(ctx, member))[0]
        
        matches = await self.match_cog.get_team_matches(ctx, team, match_day)
        
        return matches

    async def find_match_replays(self, ctx, match, member=None):
        match['format'] = '4-GS'
        all_players = await self.get_all_match_players(ctx, match)

        # All of this data should be tracked to optimize the search and validation
        discovery_data = {
            "is_valid_set": False,
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
        match_date = datetime.strptime(match['matchDate'], '%B %d, %Y').strftime('%Y-%m-%d')
        match_start_dt = bcConfig.START_MATCH_DT_TMPLT.format(match_date, bcConfig.ZONE_ADJ)
        match_end_dt = bcConfig.END_MATCH_DT_TMPLT.format(match_date, bcConfig.ZONE_ADJ)

        # Search all players in game for replays until match is found
        
        for player in all_players:
            for steam_id in (await self.get_steam_ids(ctx.guild, player)):

                data = bapi.get_replays(
                    playlist=bcConfig.PLAYLIST,
                    sort_by=bcConfig.SORT_BY,
                    sort_dir=bcConfig.SORT_DIR,
                    replay_after=match_start_dt,
                    replay_before=match_end_dt,
                    uploader=steam_id
                )

                # checks for MATCHing ;) replays
                for replay in data: #.get('list', []):
                    if self.is_valid_match_replay(match, replay):
                        # replay_ids.append(replay['id'])
                        replay_hash = self.generate_replay_hash(replay)
                        if replay_hash not in discovery_data['replay_hashes']:
                            discovery_data['replay_hashes'].append(replay_hash)
                            discovery_data['match_replay_ids'].append(replay['id'])
                        
                            # NEW: update search range to avoid duplicate replays added - TODO: rethink this. maybe hashing is enough
                            # match_start_dt = replay['created']

                            if (replay.get('blue', {}).get('name', 'blue').lower() in match.get('home', '').lower()
                                or replay.get('orange', {}).get('name', 'orange').lower() in match.get('away', '').lower()):
                                home = 'blue'
                                away = 'orange'
                            elif (replay.get('orange', {}).get('name', 'orange').lower() in match.get('away', '').lower()
                                or replay.get('blue', {}).get('name', 'blue').lower() in match.get('home', '').lower()):
                                home = 'orange'
                                away = 'blue'
                            
                            home_goals = replay[home].get('goals', 0)
                            away_goals = replay[away].get('goals', 0)
                            if home_goals > away_goals:
                                discovery_data['home_wins'] += 1
                            else:
                                discovery_data['away_wins'] += 1

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

        home_team_found = replay_teams.get('blue', {}).get('name', '').lower() in home_team.lower() or replay_teams.get('orange', {}).get('name', '').lower() in home_team.lower()
        away_team_found = replay_teams.get('blue', {}).get('name', '').lower() in away_team.lower() or replay_teams.get('orange', {}).get('name', '').lower() in away_team.lower()

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
        match_format = discovery_data.get('format', '4-gs').lower()
        format_components = match_format.split('-')

        for component in format_components:
            if component.isdigit():
                num_games = int(component)
                format_components.remove(str(num_games))
                break
        
        format_type = component[0]

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

    def get_replay_teams_and_players(self, replay):
        
        blue_name = replay.get('blue', {}).get('name', 'Blue').title()
        orange_name = replay.get('orange', {}).get('name', 'Orange').title()

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

    async def get_steam_ids(self, guild, player: discord.Member):
        # TODO: update to lookup request
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

    async def get_tier_group_name(self, guild, target_tier_name):
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

    def is_captain(self, player):
        for role in player.roles:
            if role.name.lower() == "captain":
                return True
        return False
        

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
    


# endregion

