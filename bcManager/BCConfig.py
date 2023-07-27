from datetime import datetime

# Discord ID: Steam ID -- maybe handle multiple accounts?

# ###############################################################################


class BCConfig:
    # Search Settings
    SEARCH_COUNT = 10
    PLAYLIST = "private"
    SORT_BY = "replay-date"
    SORT_DIR = "desc"

    ZONE_ADJ = "-04:00"
    START_MATCH_DT_TMPLT = "{}T21:00:00{}"  # search after 9 pm (start)
    END_MATCH_DT_TMPLT = "{}T23:59:59{}"  # search before 9 pm (end)

    utc_strftime_fmt = "%Y-%m-%dT%H:%M:%S+00:00"

    # Upload settings
    visibility = "public"
    team_identification = (
        "by-player-clusters"  # setting -- Alternative: 'by-distinct-players'
    )
    player_identification = "by-id"  # setting -- Alternative 'by-name'
