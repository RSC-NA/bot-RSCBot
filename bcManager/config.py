from datetime import datetime
# Discord ID: Steam ID -- maybe handle multiple accounts?

# ###############################################################################

class config:
    auth_token = None
    top_level_group = None
    search_count = 10
    visibility = 'public'
    team_identification = 'by-player-clusters'                  # setting -- Alternative: 'by-distinct-players'
    player_identification = 'by-id'                             # setting -- Alternative 'by-name'
