import gspread
import requests
import csv
import datetime
import asyncio
import os

from redbot.core import commands
from redbot.core import checks
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup, Tag
from discord import File

now = datetime.datetime.now()
readibletime = now.strftime("%Y-%m-%d_%H-%M-%S")

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
credentials = ServiceAccountCredentials.from_json_keyfile_name(
    "Trackers-10a10d9d831a.json", scope
)
gc = gspread.authorize(credentials)

Outputcsv = "%s.csv" % (readibletime)
CurrentSeason = 11
Seasons = [11]
GamesPlayed = True


def _require_tag(tag: Tag | None) -> Tag:
    """Returns the tag, raising if the expected element is missing from the page."""
    if tag is None:
        raise ValueError("Expected HTML element not found")
    return tag


class MMRFetcher(commands.Cog):
    @commands.guild_only()
    @commands.command()
    @checks.is_owner()
    async def fetch(self, ctx):
        await ctx.send("Fetching MMR data...")
        w = self._createcsv()

        names, links = self._readTrackerList()
        total = len(names)
        tenPercent = total // 10

        i = 0  # count of each row in the Tracker Links
        for i in range(0, total):
            try:
                name, link = names[i], links[i]
                linksplit = link.split("profile/")
                unpack = [x for x in linksplit[1].split("/") if x]
                if "mmr" in unpack:
                    mmr, platform, gamertag = unpack
                else:
                    platform, gamertag = unpack
                data = self._rlscrape(gamertag, platform)
                self._writefetch(w, data, name, link)
                i += 1
                if i % tenPercent == 0:
                    await ctx.send(
                        "Fetch Progress: {}0% Complete".format(i // tenPercent)
                    )
            except Exception as e:
                i += 1
                await ctx.send("Error on line {0}: {1}".format(i, e))
            await asyncio.sleep(0.001)

        await ctx.send("Done", file=File(Outputcsv))
        os.remove(Outputcsv)

    def _readTrackerList(self):
        wks = gc.open("Tracker Links").sheet1
        names = wks.col_values(1)
        links = wks.col_values(2)
        return names, links

    def _createcsv(self):
        """Create CSV output file"""
        header = ["Name", "Tracker"]
        if GamesPlayed is True:
            header.extend(
                [
                    "1s_MMR",
                    "_2s_MMR",
                    "Solo_3s_MMR",
                    "3s_MMR",
                    "1s_GP",
                    "2s_GP",
                    "Solo_3s_GP",
                    "3s_GP",
                ]
            )
        else:
            header.extend(["1s_MMR", "_2s_MMR", "Solo_3s_MMR", "3s_MMR"])
        csvwrite = open(Outputcsv, "w", newline="")
        w = csv.writer(csvwrite, delimiter=",")
        w.writerow(header)
        return w

    def _writefetch(self, writer, data, name, link):
        newrow = self._dicttolist(data)
        newrow.insert(0, name.encode("ascii", "replace"))
        newrow[0] = newrow[0].decode("ascii")
        newrow.insert(1, link)
        writer.writerow(newrow)

    def _rlscrape(self, gamertag, platform):
        """Python BeautifulSoup4 Webscraper to https://rocketleague.tracker.network/ and grab Season 9 and 10"""
        # clienterrors = [400,401,402,403,404] #future proof
        # servererrors = [500,501,502,503,504,505,506,507,508,510,511] #future proof
        playerdata = {}  # define the playerdata dict
        playerdata[gamertag] = {}  # definite the gamertag dict
        playlistdict = {
            0: "Un-Ranked",
            10: "Ranked Duel 1v1",
            11: "Ranked Doubles 2v2",
            12: "Ranked Solo Standard 3v3",
            13: "Ranked Standard 3v3",
        }
        webpath = "https://rocketleague.tracker.network"
        for season in Seasons:
            playerdata[gamertag][season] = {}  # define the season dict
            seasonid = "season-%s" % (season)
            if CurrentSeason == season:
                tracker = "%s/%s/%s/%s" % (webpath, "profile/mmr", platform, gamertag)
                page = requests.get(tracker)
                if page.status_code == 200:
                    content = page.content
                    soup = BeautifulSoup(content, features="lxml")
                    for numrank, playlist in playlistdict.items():
                        try:
                            mmr_link = _require_tag(
                                soup.find("a", {"data-id": str(numrank)})
                            )
                            mmr = _require_tag(mmr_link.find("span")).text
                        except Exception:
                            playerdata[gamertag][season][playlist] = None
                        else:
                            playerdata[gamertag][season][
                                playlist
                            ] = {}  # define the playlist dict
                            stats = _require_tag(
                                soup.find("div", {"data-id": str(numrank)})
                            )
                            gamesplayed = _require_tag(
                                _require_tag(stats.find("div")).find("span")
                            ).text
                            division = stats.select("div > h4")[2].text
                            rank = stats.select("div > span")[2].text
                            playerdata[gamertag][season][playlist]["MMR"] = mmr
                            playerdata[gamertag][season][playlist]["Games Played"] = (
                                gamesplayed
                            )
                            playerdata[gamertag][season][playlist]["Rank"] = (
                                rank  # futureproof
                            )
                            playerdata[gamertag][season][playlist]["Rank Division"] = (
                                division  # futureproof
                            )
            else:
                tracker = "%s/%s/%s/%s" % (webpath, "profile", platform, gamertag)
                page = requests.get(tracker)
                if page.status_code == 200:
                    content = page.content
                    soup = BeautifulSoup(content, features="lxml")
                    # loop through playlistdict to get data then apply that to the soup to sort it
                    for numrank, playlist in playlistdict.items():
                        try:
                            season_tbody = _require_tag(soup.find(id=seasonid)).select(
                                "table > tbody"
                            )[0]
                            souptable = season_tbody.select("tr")[1:]
                        except Exception:
                            playerdata[gamertag][season][playlist] = None
                        else:
                            playerdata[gamertag][season][
                                playlist
                            ] = {}  # define the playlist dict
                            i = 0  # use a count to sort through the souptable for each playlist's data
                            for soupdata in souptable:
                                soupplaylist = (
                                    season_tbody.select("tr")[i]
                                    .select("td")[1]
                                    .text.split("\n")[1]
                                )
                                if (
                                    playlist == soupplaylist
                                ):  # loop through and match playlist to webscrape
                                    mmr = (
                                        season_tbody.select("tr")[i]
                                        .select("td")[2]
                                        .text
                                    )
                                    gamesplayed = (
                                        season_tbody.select("tr")[i]
                                        .select("td")[3]
                                        .text
                                    )
                                    playerdata[gamertag][season][playlist]["MMR"] = (
                                        mmr.strip()
                                    )
                                    if "n/a" not in gamesplayed:
                                        playerdata[gamertag][season][playlist][
                                            "Games Played"
                                        ] = gamesplayed.strip()
                                    else:
                                        playerdata[gamertag][season][playlist][
                                            "Games Played"
                                        ] = None
                                i += 1
        return playerdata

    def _dicttolist(self, data):
        newdict = {}
        for gamertag, gdata in data.items():
            for season, sdata in gdata.items():
                newdict[season] = {
                    "MMR_1s": None,
                    "MMR_2s": None,
                    "MMR_Solo3s": None,
                    "MMR_3s": None,
                    "GamesPlayed_1s": None,
                    "GamesPlayed_2s": None,
                    "GamesPlayed_Solo3s": None,
                    "GamesPlayed_3s": None,
                }
                for playlist, pdata in sdata.items():
                    if (
                        playlist in "Ranked Duel 1v1"
                        and pdata is not None
                        and pdata.items()
                    ):
                        newdict[season]["MMR_1s"] = pdata["MMR"]
                        newdict[season]["GamesPlayed_1s"] = pdata["Games Played"]
                    if (
                        playlist in "Ranked Doubles 2v2"
                        and pdata is not None
                        and pdata.items()
                    ):
                        newdict[season]["MMR_2s"] = pdata["MMR"]
                        newdict[season]["GamesPlayed_2s"] = pdata["Games Played"]
                    if (
                        playlist in "Ranked Solo Standard 3v3"
                        and pdata is not None
                        and pdata.items()
                    ):
                        newdict[season]["MMR_Solo3s"] = pdata["MMR"]
                        newdict[season]["GamesPlayed_Solo3s"] = pdata["Games Played"]
                    if (
                        playlist in "Ranked Standard 3v3"
                        and pdata is not None
                        and pdata.items()
                    ):
                        newdict[season]["MMR_3s"] = pdata["MMR"]
                        newdict[season]["GamesPlayed_3s"] = pdata["Games Played"]
        newlist = []
        for season, v in newdict.items():
            if GamesPlayed is True:
                newlist.extend(
                    [
                        v["MMR_1s"],
                        v["MMR_2s"],
                        v["MMR_Solo3s"],
                        v["MMR_3s"],
                        v["GamesPlayed_1s"],
                        v["GamesPlayed_2s"],
                        v["GamesPlayed_Solo3s"],
                        v["GamesPlayed_3s"],
                    ]
                )
            else:
                newlist.extend([v["MMR_1s"], v["MMR_2s"], v["MMR_Solo3s"], v["MMR_3s"]])
        return newlist
