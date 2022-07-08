from tokenize import group
from .config import config
import requests
import tempfile
import discord
import asyncio
import ballchasing

from teamManager import TeamManager

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions
from datetime import datetime, timezone


defaults = {
    "AuthToken": config.auth_token,
    "TopLevelGroup": config.top_level_group,
    "ReplayDumpChannel": None
}

verify_timeout = 30

class BCManager(commands.Cog):
    """Manages aspects of Ballchasing Integrations with RSC"""

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=1234567893, force_registration=True)
        self.config.register_guild(**defaults)
        self.team_manager_cog : TeamManager = bot.get_cog("TeamManager")
        self.match_cog = bot.get_cog("Match")
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
        api = ballchasing.Api(auth_token)
        if api:
            self.ballchasing_api[ctx.guild] = api
            await self._save_auth_token(ctx.guild, auth_token)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setTopLevelGroup(self, ctx, top_level_group):
        """Sets the Top Level Ballchasing Replay group for saving match replays.
        Note: Auth Token must be generated from the Ballchasing group owner
        """
        
        bapi : ballchasing.Api = self.ballchasing_api[ctx.guild] 
        data = bapi.get_group(top_level_group)

        
        group_set = await self._save_top_level_group(ctx, top_level_group)
        if group_set:
            await ctx.send("Done.")
        else:
            await ctx.send(":x: Error setting top level group.")

# endregion 

# region player commands 
    @commands.command(aliases=['bcr', 'bcpull'])
    @commands.guild_only()
    async def bcreport(self, ctx, team_name=None, match_day=None):
        """Finds match games from recent public uploads, and adds them to the correct Ballchasing subgroup
        """

        # TODO: do not allow players to report replays for teams they are not a part of (unless admin or GM)
        # Get match information
        member = ctx.message.author
        match = await self.get_match(ctx, member, team_name, match_day)

        if not match:
            await ctx.send(":x: No match found.")
            return False

        # Get team/tier information
        match_day = match['matchDay']
        franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, match['home'])
        emoji_url = ctx.guild.icon_url

        embed = discord.Embed(
            title="Match Day {}: {} vs {}".format(match_day, match['home'], match['away']),
            description="Searching https://ballchasing.com for publicly uploaded replays of this match...",
            color=tier_role.color
        )
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)
        bc_status_msg = await ctx.send(embed=embed)
        

        # Find replays from ballchasing
        replays_found = await self._find_match_replays(ctx, member, match)

        ## Not found:
        if not replays_found:
            embed.description = ":x: No matching replays found on ballchasing."
            await bc_status_msg.edit(embed=embed)
            return False
        
        ## Found:
        replay_ids, summary, winner = replays_found
        
        if winner:
            franchise_role, tier_role = await self.team_manager_cog._roles_for_team(ctx, winner)
            emoji = await self.team_manager_cog._get_franchise_emoji(ctx, franchise_role)
            emoji_url = emoji.url
        

        # Prepare embed edits for score confirmation
        prompt_embed = discord.Embed.from_dict(embed.to_dict())
        prompt_embed.description = "Match summary:\n{}".format(summary)
        prompt_embed.set_thumbnail(url=emoji_url)
        prompt_embed.description += "\n\nPlease react to confirm the score summary for this match."

        success_embed = discord.Embed.from_dict(prompt_embed.to_dict())
        success_embed.description = "Match summary:\n{}".format(summary)
        success_embed.description += "\n\n:signal_strength: Results confirmed. Creating a ballchasing replay group. This may take a few seconds..." # "\U0001F4F6"

        reject_embed = discord.Embed.from_dict(prompt_embed.to_dict())
        reject_embed.description = "Match summary:\n{}".format(summary)
        reject_embed.description += "\n\n:x: Ballchasing upload has been cancelled."
        
        if not await self._embed_react_prompt(ctx, prompt_embed, existing_message=bc_status_msg, success_embed=success_embed, reject_embed=reject_embed):
            return False
        
        # Find or create ballchasing subgroup
        match_subgroup_id = await self._get_replay_destination(ctx, match)

        # Download and upload replays
        tmp_replay_files = await self._download_replays(ctx, replay_ids)
        uploaded_ids = await self._upload_replays(ctx, match_subgroup_id, tmp_replay_files)
        # await ctx.send("replays in subgroup: {}".format(", ".join(uploaded_ids)))
        
        renamed = await self._rename_replays(ctx, uploaded_ids)

        embed.description = "Match summary:\n{}\n\nView the ballchasing group: https://ballchasing.com/group/{}\n\n:white_check_mark: Done".format(summary, match_subgroup_id)
        embed.set_thumbnail(url=emoji_url)
        await bc_status_msg.edit(embed=embed)
     
    @commands.command(aliases=['bcGroup', 'ballchasingGroup', 'bcg'])
    @commands.guild_only()
    async def bcgroup(self, ctx):
        """Links to the top level ballchasing group for the current season."""
        group_code = await self._get_top_level_group(ctx)
        url = "https://ballchasing.com/group/{}".format(group_code)
        if group_code:
            await ctx.send("See all season replays in the top level ballchasing group: {}".format(url))
        else:
            await ctx.send(":x: A ballchasing group has not been set for this season yet.")

    @commands.command(aliases=['accs', 'myAccounts', 'registeredAccounts'])
    @commands.guild_only()
    async def accounts(self, ctx):
        """View all accounts that have been registered to with your discord account in this guild."""
        return
        member = ctx.message.author
        accounts = await self._get_member_accounts(member)
        if not accounts:
            await ctx.send("{}, you have not registered any accounts.".format(member.mention))
            return

        show_accounts = "{}, you have registered the following accounts:\n - ".format(member.mention) + "\n - ".join("{}: {}".format(acc[0], acc[1]) for acc in accounts)
        await ctx.send(show_accounts)

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
        for guild in self.bot.guilds:
            token = self._get_auth_token(guild)
            if token:
                self.ballchasing_api[guild] = ballchasing.Api(token)

# region json

    async def _get_auth_token(self, guild):
        return await self.config.guild(guild).AuthToken()
    
    async def _save_auth_token(self, guild, token):
        await self.config.guild(guild).AuthToken.set(token)


# endregion

