import traceback
import ast
import random
from datetime import datetime
import json
import discord
import logging
from .config import config

from redbot.core import Config, commands, checks

from teamManager import TeamManager

from typing import Optional,List

log = logging.getLogger("red.RSCBot.match")

defaults = {
    "MatchDay": 0,
    "Schedules": {},
    "Segment": "Regular Season",
    "Game": "Rocket League",
    "GameTeamSize": 3,
    "LobbyHashes": {},
}


class Match(commands.Cog):
    """Used to get the match information"""

    MATCHES_KEY = "Matches"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567893, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.team_manager: TeamManager = bot.get_cog("TeamManager")

        # TODO: Data Setup on startup - guild[field] = x -> match dates, time zone, gameTeamSize, SeriesType

    # Admin Configuration
    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setMatchDay(self, ctx, day: str):
        """Sets the active match day to the specified day.

        This match day is used when accessing the info in the !match command.
        """
        await self._save_match_day(ctx, str(day))
        await ctx.send("Done")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addMatches(self, ctx, *matches):
        """Add the matches provided to the schedule.

        Arguments:

        matches -- One or more matches in the following format:

        "['<matchDay>','<matchDate>','<home>','<away>','<matchType>','<matchFormat>']"

        Each match should be separated by a space. Also, matchDate should be
        formatted with the full month name, day of month and 4-digit year.
        The room name and password are optional. They will be generated if
        absent. Note that the placment of the double versus single quotes is
        important, as is the comma after the day of month.

        Examples:

        [p]addMatches "['1','September 10, 2020','Fire Ants','Leopards','Regular Season','4-GS']"
        [p]addMatches "['1','September 10, 2018','Fire Ants','Leopards','Regular Season','4-GS']" "['2','September 13, 2018','Leopards','Fire Ants''Regular Season','4-GS']"
        [p]addMatches "['12','September 10, 2020','Fire Ants','Leopards','Wildcard','BO-5']" "['12','September 13, 2018','Leopards','Fire Ants''Finals','BO-7']"
        """
        addedCount = 0
        try:
            for matchStr in matches:
                match = ast.literal_eval(matchStr)
                resultMatch = await self._add_match(ctx, *match)
                if resultMatch:
                    addedCount += 1
        except Exception as e:
            await ctx.send(e)
        finally:
            await ctx.send("Added {0} match(es).".format(addedCount))

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addMatch(
        self, ctx, match_day, match_date, home, away, match_type, match_format
    ):
        """Adds a single match to the schedule.

        Arguments:
            ctx -- the bot context
            match_day -- the match_day to add the match to
            match_date -- the date the match should be played
            home -- the home team
            away -- the away team
            match_type -- the match format (i.e. "Regular Season", "Wildcard", "Finals")
            match_format -- the match format (i.e. "4-GS", "BO-5", "BO-7")
        Note: Match format must be represented as "GS" (game series) or "BO" (best of) and an integer, separated by a dash

        Example:
            [p]addMatch 4 "May 25, 2022" Thermal Gorillas "Regular Season" 4-gs
        """
        match = await self._add_match(
            ctx, match_day, match_date, home, away, match_type, match_format
        )
        if match:
            await ctx.send("Done")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearSchedule(self, ctx):
        """Clear all scheduled matches."""
        await self._save_lobby_hashes(ctx.guild, {})
        await self._save_schedule(ctx, {})
        await ctx.send("Done.")

    # region match settings
    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def printScheduleData(self, ctx):
        """Print all raw schedule data.

        Note: In the real server, this will likely fail just due to the amount
        of data. Intended for use in debugging on test servers. Basically,
        when there are only a handful of matches total.

        TODO: Might even comment this out in prod.
        """
        schedule = await self._schedule(ctx)
        dump = json.dumps(schedule, indent=4, sort_keys=True)
        try:
            await ctx.send(
                "Here is all of the schedule data in JSON format.\n```json\n{0}\n```".format(
                    dump
                )
            )
        except discord.errors.HTTPException as exc:
            httpErrorEmbed = discord.Embed(
                title="Discord HTTP Error",
                description=f"{exc.text}",
                colour=discord.Colour.red(),
            )
            httpErrorEmbed.add_field(name="Status", value=f"{exc.status}", inline=True)
            httpErrorEmbed.add_field(name="Code", value=f"{exc.code}", inline=True)
            await ctx.send(embed=httpErrorEmbed)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setGame(self, ctx, *, game):
        """Sets the game for the guild. The game determines the match info provided.

        Supported games: Rocket League, CSGO
        """
        msg = "Done"
        if game.title() == "Rocket League":
            await self._save_guild_game(ctx.guild, "Rocket League")
        elif game.upper() == "CSGO" or game.title() == "Counter-Strike":
            await self._save_guild_game(ctx.guild, "CSGO")
        else:
            msg = "**{}** is not a supported game, but it has been saved.".format(game)
            await self._save_guild_game(ctx.guild, game)
        await ctx.send(msg)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setGameTeamSize(self, ctx, num_players: int):
        """Sets the number of players on each team in matches (Default: 3)"""
        await self._save_game_team_size(ctx.guild, num_players)
        await ctx.send("Done")

    # endregion

    # General Info Commands
    @commands.command(aliases=["gmd"])
    @commands.guild_only()
    async def getMatchDay(self, ctx):
        """Gets the currently active match day."""
        match_day = await self._match_day(ctx)
        if match_day:
            await ctx.send("Current match day is: {0}".format(match_day))
        else:
            await ctx.send(":x: Match day not set. Set with setMatchDay command.")

    # Player Commands
    @commands.command()
    @commands.guild_only()
    async def match(self, ctx, match_day: int=None, *teams: str):
        """Get match info.

        If no arguments are provided, retrieve the match info for the
        server's currently active match day for the requesting user's
        team or teams. This will fail if the user has no team role or if
        the match day is not set.

        If one argument is provided, it must be the match day to retrieve. If
        more than one argument is provided, the first must be the match day
        followed by a list of teams for which the match info should be
        retrieved.

        Example: `[p]match 1 derechos "killer bees"`

        Note: If no team names are sent, GMs (or anyone with multiple team
        roles) will get matchups for all their teams. User's without a team
        role will get nothing.
        """
        if not match_day:
            match_day = await self._match_day(ctx)
        if not match_day:
            await ctx.reply(embed=discord.Embed(
                title="Match Error",
                description="Match day not provided and not configured in the server.",
                color=discord.Color.red(),
            ))
            return

        if not teams:
            teams = await self.team_manager.teams_for_user(ctx, ctx.message.author)

        if not teams:
            await ctx.reply(embed=discord.Embed(
                title="Match Error",
                description="No teams found. If you provided teams, "
                "check the spelling. If not, you do not have "
                "roles corresponding to a team.",
                color=discord.Color.red(),
            ))
            return

        franchise_role = self.team_manager.get_current_franchise_role(
            ctx.message.author
        )
        send_to_channel = await self.get_franchise_match_channel(franchise_role)

        for team_name in teams:
            try:
                team_matches = await self.get_team_matches(ctx, team_name, str(match_day))
            except LookupError as exc:
                await ctx.reply(embed=discord.Embed(
                    title="Match Error",
                    description=f"**{team_name}** is not a valid team name. Please check the spelling.",
                    color=discord.Color.red(),
                ))
                return

            for match in team_matches:
                embed = await self._format_match_embed(ctx, match, team_name)
                await send_to_channel.send(ctx.author.mention, embed=embed)

            if not team_matches:
                # await ctx.message.author.send("No matches on day {0} for {1}".format(match_day, team_name))
                await send_to_channel.send(
                    f"{ctx.author.mention}, No matches on day {match_day} for {team_name}"
                )

        await ctx.message.delete()

    # # Player Commands
    # @commands.command()
    # @commands.guild_only()
    # async def match(self, ctx, *args):
    #     """Get match info.

    #     If no arguments are provided, retrieve the match info for the
    #     server's currently active match day for the requesting user's
    #     team or teams. This will fail if the user has no team role or if
    #     the match day is not set.

    #     If one argument is provided, it must be the match day to retrieve. If
    #     more than one argument is provided, the first must be the match day
    #     followed by a list of teams for which the match info should be
    #     retrieved.

    #     Example: `[p]match 1 derechos "killer bees"`

    #     Note: If no team names are sent, GMs (or anyone with multiple team
    #     roles) will get matchups for all their teams. User's without a team
    #     role will get nothing.
    #     """
    #     match_day = args[0] if args else await self._match_day(ctx)
    #     if not match_day:
    #         await ctx.send("Match day not provided and not set for " "the server.")
    #         return
    #     team_names = []

    #     team_names_provided = len(args) > 1
    #     if team_names_provided:
    #         team_names = args[1:]
    #     else:
    #         team_names = await self.team_manager.teams_for_user(ctx, ctx.message.author)

    #     if not team_names:
    #         await ctx.send(
    #             "No teams found. If you provided teams, "
    #             "check the spelling. If not, you do not have "
    #             "roles corresponding to a team."
    #         )
    #         return

    #     franchise_role = self.team_manager.get_current_franchise_role(
    #         ctx.message.author
    #     )
    #     send_to_channel = await self.get_franchise_match_channel(franchise_role)

    #     on_mobile = ctx.message.author.is_on_mobile()
    #     for team_name in team_names:
    #         team_matches = await self.get_team_matches(ctx, team_name, str(match_day))
    #         for match in team_matches:
    #             if on_mobile:
    #                 message = await self._format_match_message(ctx, match, team_name)
    #                 # await ctx.message.author.send(message)
    #                 await send_to_channel.send(ctx.author.mention)
    #                 await send_to_channel.send(message)
    #             else:
    #                 embed = await self._format_match_embed(ctx, match, team_name)
    #                 # await ctx.message.author.send(embed=embed)
    #                 await send_to_channel.send(ctx.author.mention, embed=embed)

    #         if not team_matches:
    #             # await ctx.message.author.send("No matches on day {0} for {1}".format(match_day, team_name))
    #             await send_to_channel.send(
    #                 f"{ctx.author.mention}, No matches on day {match_day} for {team_name}"
    #             )

    #     await ctx.message.delete()

    @commands.command(aliases=["lobbyup", "up", "ready"])
    @commands.guild_only()
    async def lobbyready(self, ctx):
        """Informs players of the opposing team that the private match lobby is ready and joinable."""
        match_day = await self._match_day(ctx)
        team_size = await self._get_game_team_size(ctx.guild)
        if team_size not in [3]:
            await ctx.message.add_reaction("\U0000274C")
            return await ctx.send(
                ":x: This command is not supported for this game mode."
            )

        teams = await self.team_manager.teams_for_user(ctx, ctx.author)

        if not (match_day and teams):
            return await ctx.message.add_reaction("\U0000274C")

        team_name = teams[0]

        match_data = await self.get_team_matches(ctx, team_name, match_day)

        # TODO: handle more gracefully for 2s league, simplify logic
        if not match_data:
            await ctx.message.add_reaction("\U0000274C")
            return await ctx.send(":x: Match could not be found")

        match_data = match_data[0]

        opposing_team = (
            match_data["home"]
            if team_name == match_data["away"]
            else match_data["away"]
        )

        opp_franchise_role, tier_role = await self.team_manager._roles_for_team(
            ctx, opposing_team
        )
        opposing_roster = await self.team_manager.members_from_team(
            opp_franchise_role, tier_role
        )

        if not opposing_roster:
            await ctx.message.add_reaction("\U0000274C")
            await ctx.send(":x: No roster found for the **{}**".format(opposing_team))

        message = "Please join your match against the **{}** with the following lobby information:".format(
            opposing_team
        )
        message += "\n\n**Name:** {}".format(match_data["roomName"])
        message += "\n**Password:** {}".format(match_data["roomPass"])

        embed = discord.Embed(
            title="Your RSC Opponents are ready!",
            color=tier_role.color,
            description=message,
        )

        for opponent in opposing_roster:
            if not self.team_manager.is_subbed_out(opponent):
                await opponent.send(embed=embed)

        await ctx.message.add_reaction("\U00002705")

    # Helper Functions
    async def _add_match(
        self, ctx, match_day, match_date, home, away, match_type, match_format
    ):
        """Does the actual work to save match data."""
        # Process inputs to normalize the data (e.g. convert team names to roles)
        match_date_error = None
        try:
            datetime.strptime(match_date, "%B %d, %Y").date()
        except Exception as err:
            match_date_error = "Date not valid: {0}".format(err)
        homeRoles = await self.team_manager._roles_for_team(ctx, home)
        awayRoles = await self.team_manager._roles_for_team(ctx, away)

        # Avoid duplicate lobby info
        lobby_hashes = await self._get_lobby_hashes(ctx.guild)
        md_lobby_hashes = lobby_hashes.setdefault(str(match_day), [])

        valid_hash = False
        while not valid_hash:
            room_name = self._generate_name_pass()
            room_pass = self._generate_name_pass()
            lobby_hash = hash(f"{room_name}-{room_pass}")

            valid_hash = lobby_hash not in md_lobby_hashes

        md_lobby_hashes.append(lobby_hash)
        lobby_hashes[str(match_day)] = md_lobby_hashes

        await self._save_lobby_hashes(ctx.guild, lobby_hashes)

        # Validation of input
        # There are other validations we could do, but don't
        #     - that there aren't extra args
        errors = []
        if match_date_error:
            errors.append(
                "Date provided is not valid. " "(Make sure to use the right format.)"
            )
        if not homeRoles:
            errors.append("Home team roles not found ({}).".format(home))
        if not awayRoles:
            errors.append("Away team roles not found ({}).".format(away))
        if homeRoles[1] != awayRoles[1]:
            errors.append(
                "Home and Away teams are in different tiers ({}, {})".format(home, away)
            )
        if errors:
            await ctx.send(
                ":x: Errors with input:\n\n  " "* {0}\n".format("\n  * ".join(errors))
            )
            return

        schedule = await self._schedule(ctx)

        match_data = {
            "matchDay": match_day,
            "matchDate": match_date,
            "home": home,
            "away": away,
            "matchType": match_type,
            "matchFormat": match_format,
            "roomName": room_name,
            "roomPass": room_pass,
        }

        # Adds match to correct location within Schedules hierarchy
        franchise_role, tier_role = homeRoles
        tier_schedule = schedule.setdefault(tier_role.name, {})
        tier_matches = tier_schedule.setdefault(str(match_day), [])
        tier_matches.append(match_data)

        tier_schedule[str(match_day)] = tier_matches
        schedule[tier_role.name] = tier_schedule

        await self._save_schedule(ctx, schedule)

        result = match_data.copy()
        result["home"] = home
        result["away"] = away
        return result

    async def _format_match_embed(self, ctx, match, user_team_name):
        # Match format:
        # match = {
        #     'matchDay': match_day,
        #     'matchDate': match_date,
        #     'home': home,
        #     'away': away,
        #     'roomName': roomName,
        #     'roomPass': roomPass,
        # }
        home = match["home"]
        away = match["away"]

        tier_role = (await self.team_manager._roles_for_team(ctx, home))[1]

        title = "__Match Day {0}: {1}__\n".format(match["matchDay"], match["matchDate"])
        description = "**{0}**\n    versus\n**{1}**\n\n".format(home, away)

        embed = discord.Embed(
            title=title, description=description, color=tier_role.color
        )

        game_team_size = await self._get_game_team_size(ctx.guild)

        # 2s, 3s
        return await self._create_normal_match_embed(
            ctx, embed, match, user_team_name, home, away, game_team_size
        )

    async def _format_match_message(self, ctx, match, user_team_name):
        # Match format:
        # match_data = {
        #     'matchDay': match_day,
        #     'matchDate': match_date,
        #     'home': home,
        #     'away': away,
        #     'roomName': roomName,
        #     'roomPass': roomPass
        # }
        home = match["home"]
        away = match["away"]

        message = "__Match Day {0}: {1}__\n".format(
            match["matchDay"], match["matchDate"]
        )
        message += "**{0}**\n    versus\n**{1}**\n\n".format(home, away)

        message += await self._create_normal_match_message(
            ctx, match, user_team_name, home, away
        )
        return message

    async def get_team_matches(self, ctx, team_name, match_day=None):
        franchise_role, tier_role = await self.team_manager._roles_for_team(
            ctx, team_name
        )
        schedule = await self._schedule(ctx)

        tier_schedule = schedule.setdefault(tier_role.name, {})

        if match_day:
            tier_matches = tier_schedule.setdefault(str(match_day), [])
        else:
            tier_matches = []
            for match_day, matches in tier_schedule.items():
                tier_matches += matches

        team_matches = []
        for match in tier_matches:
            if team_name.lower() in [match["home"].lower(), match["away"].lower()]:
                team_matches.append(match)

        return team_matches

    async def _create_additional_info(
        self, guild, user_team_name, match, is_playoffs=False, is_embed=False
    ):
        home = match["home"]
        away = match["away"]
        match_format = match.get("matchFormat", "4-gs")

        additional_info = ""

        # Determine Format
        parsed_matchup_type = self.parse_matchup_type(match_format)

        if parsed_matchup_type:
            matchup_type_str = f"**{parsed_matchup_type[2]}**"
        else:
            matchup_type_str = "4 game series"

        if user_team_name:
            if user_team_name == home:
                additional_info += config.home_info.format(
                    series_switch_num=int(parsed_matchup_type[1] / 2)
                )
            elif user_team_name == away:
                additional_info += config.away_info

        # TODO: Add other info (complaint form, disallowed maps, enable crossplay, etc.)

        game = await self._get_guild_game(guild)

        if game == "Rocket League":
            # REGULAR SEASON INFO
            additional_info += "\n\n"
            additional_info += config.rl_regular_info + " "
            if is_embed:
                additional_info += config.rsc_upload_embed_info.format(
                    series_type=matchup_type_str
                )
            else:
                additional_info += config.rl_upload_info.format(
                    series_type=matchup_type_str
                )

            # PLAYOFF INFO
            # additional_info += config.playoff_info
            return additional_info

    async def _create_normal_match_embed(
        self, ctx, embed, match, user_team_name, home, away, game_team_size
    ):
        embed.add_field(
            name="Lobby Info",
            value="Name: **{0}**\nPassword: **{1}**".format(
                match["roomName"], match["roomPass"]
            ),
            inline=False,
        )
        embed.add_field(
            name="**Home Team:**",
            value=await self.team_manager.format_roster_info(ctx, home),
            inline=False,
        )
        embed.add_field(
            name="**Away Team:**",
            value=await self.team_manager.format_roster_info(ctx, away),
            inline=False,
        )

        try:
            additional_info = await self._create_additional_info(
                ctx.guild, user_team_name, match, is_embed=True
            )
        except KeyError:
            # TODO: this doesn't make sense
            additional_info = await self._create_additional_info(
                ctx.guild, user_team_name, match, is_embed=True
            )

        embed.add_field(name="Additional Info:", value=additional_info)
        return embed

    async def _create_normal_match_message(
        self, ctx, match, user_team_name, home, away
    ):
        message = "**Lobby Info:**\nName: **{0}**\nPassword: **{1}**\n\n".format(
            match["roomName"], match["roomPass"]
        )
        message += "**Home Team:**\n{0}\n".format(
            await self.team_manager.format_roster_info(ctx, home)
        )
        message += "**Away Team:**\n{0}\n".format(
            await self.team_manager.format_roster_info(ctx, away)
        )

        try:
            message += await self._create_additional_info(
                ctx.guild, user_team_name, match, is_embed=False
            )
        except KeyError:
            message += await self._create_additional_info(
                ctx.guild, user_team_name, match, is_embed=False
            )

        return message

    def is_valid_match_format(self, match_format):
        match_format = match_format.lower()
        format_components = match_format.split("-")

        if len(format_components) != 2:
            return False

        has_int = False
        for component in format_components:
            if component.isdigit():
                has_int = True
                num_games = int(component)
                break

        if not has_int:
            return False

        format_components.remove(str(num_games))
        format_type = format_components[0]

        if format_type == "gs":
            return len(format_components) == 1

        elif format_type == "bo":
            return (num_games > 0) and (num_games % 2 == 1)

        return False

    def _generate_name_pass(self):
        return config.room_pass[random.randrange(len(config.room_pass))]

    async def _is_in_game(self, member):
        if not member.activities:
            return False

        playing = False
        game = await self._get_guild_game(member.guild)

        for activity in member.activities:
            if type(activity) == discord.Game:
                if activity.name == game:
                    playing = True
                    try:
                        playing = (
                            not activity.end or activity.end > discord.utils.utcnow()
                        )
                    except:
                        playing = not activity.end
                    return playing

    def parse_matchup_type(self, matchup_code):
        format_components = matchup_code.lower().split("-")

        for component in format_components:
            if component.isdigit():
                num_games = int(component)
                break

        format_components.remove(str(num_games))
        format_type = format_components[0]

        if format_type == "gs":
            match_fmt_type = "game series"
            formatted = f"{num_games} {match_fmt_type}"
        elif format_type == "bo":
            match_fmt_type = "best-of"
            formatted = f"{match_fmt_type} {num_games}"

        return match_fmt_type, num_games, formatted

    async def get_franchise_match_channel(self, franchise_role: discord.Role):
        guild = franchise_role.guild
        franchise_name = self.team_manager._extract_franchise_name_from_role(
            franchise_role
        )
        franchise_channel_name = franchise_name.replace(" ", "-").lower()
        CAT_NAME = "Match Info"

        match_cat = None
        for cat in guild.categories:
            if cat.name == CAT_NAME:
                match_cat = cat
                break

        if not match_cat:
            match_cat = await guild.create_category(CAT_NAME)

        for team_channel in match_cat.channels:
            if team_channel.name == franchise_channel_name:
                return team_channel

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            franchise_role: discord.PermissionOverwrite(view_channel=True),
        }

        return await match_cat.create_text_channel(
            franchise_channel_name, overwrites=overwrites
        )

    def get_match_index_in_day(self, schedule, tier, match):
        matches = schedule.get(tier, {}).get(str(match["matchDay"]), [])
        for i in range(len(matches)):
            match_i = matches[i]
            match_matches_match_i = (
                match_i["home"] == match["home"]
                and match_i["away"] == match["away"]
                and match_i["matchDay"] == match["matchDay"]
                and match_i["matchDate"] == match["matchDate"]
                and match_i["roomName"] == match["roomName"]
                and match_i["roomPass"] == match["roomPass"]
            )
            if match_matches_match_i:
                return i
        return None

    async def get_unreported_matches(self, ctx):
        schedule = await self._schedule(ctx)
        missing_matches = {}
        for tier, match_day_matches in schedule.items():
            for match_day, matches in match_day_matches.items():
                for match in matches:
                    if not match.get("report"):
                        missing_tier_matches = missing_matches.setdefault(tier, [])
                        missing_tier_matches.append(match)
                        missing_matches[tier] = missing_tier_matches
        return missing_matches

    # json
    async def _schedule(self, ctx):
        return await self.config.guild(ctx.guild).Schedules()

    async def _save_schedule(self, ctx, schedules):
        await self.config.guild(ctx.guild).Schedules.set(schedules)

    async def _matches(self, ctx):
        schedule = await self._schedule(ctx)
        return schedule.setdefault(self.MATCHES_KEY, {})

    async def _save_matches(self, ctx, matches):
        schedule = await self._schedule(ctx)
        schedule[self.MATCHES_KEY] = matches
        await self._save_schedule(ctx, schedule)

    async def _match_day(self, ctx):
        return await self.config.guild(ctx.guild).MatchDay()

    async def _save_match_day(self, ctx, match_day):
        await self.config.guild(ctx.guild).MatchDay.set(match_day)

    async def _save_game_team_size(self, guild, team_size):
        await self.config.guild(guild).GameTeamSize.set(team_size)

    async def _get_game_team_size(self, guild):
        return int(await self.config.guild(guild).GameTeamSize())

    async def _save_lobby_hashes(self, guild, lobby_hashes):
        await self.config.guild(guild).LobbyHashes.set(lobby_hashes)

    async def _get_lobby_hashes(self, guild):
        return await self.config.guild(guild).LobbyHashes()

    async def _save_guild_game(self, guild, game):
        await self.config.guild(guild).Game.set(game)

    async def _get_guild_game(self, guild):
        return await self.config.guild(guild).Game()
