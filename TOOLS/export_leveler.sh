#!/usr/bin/env bash
# Export Leveler data for individual guilds into standalone JSON files.
#
# Leveler (nickmcogs) stores everything under the "UserProfile" config, identifier
# 1099710897114110101. Each export keeps Red's layout, filtered to one guild:
#   {"1099710897114110101": {"GUILD": {"<gid>": {...}}, "MEMBER": {"<gid>": {"<uid>": {...}}}}}
#
# Usage:
#   export_leveler.sh <red data dir | path/to/UserProfile/settings.json> [out dir] [guild_id ...]
#
# With no guild IDs, exports RSC EU and RSC SSA.
#
# Discord IDs are larger than 2^53, so jq < 1.7 silently rounds them. This uses jq
# only when it is 1.7+, and falls back to python3 otherwise.

set -euo pipefail

CONFIG_ID="1099710897114110101"
declare -A DEFAULT_GUILDS=(
    [564159012501717281]="rsc_eu"
    [1131745948708643016]="rsc_ssa"
)

usage() {
    echo "Usage: $0 <red data dir | UserProfile/settings.json> [out dir] [guild_id ...]" >&2
    exit 1
}

[[ $# -ge 1 ]] || usage

src="$1"
if [[ -d "$src" ]]; then
    src="$src/cogs/UserProfile/settings.json"
fi
[[ -f "$src" ]] || { echo "Leveler data not found: $src" >&2; exit 1; }

out_dir="${2:-.}"
mkdir -p "$out_dir"

shift $(( $# >= 2 ? 2 : 1 ))
if [[ $# -gt 0 ]]; then
    guilds=("$@")
else
    guilds=("${!DEFAULT_GUILDS[@]}")
fi

use_jq=false
if command -v jq >/dev/null; then
    jq_version="$(jq --version | sed 's/^jq-//')"
    if [[ "$(printf '%s\n1.7\n' "$jq_version" | sort -V | head -n1)" == "1.7" ]]; then
        use_jq=true
    fi
fi

extract() {
    local gid="$1"
    if $use_jq; then
        jq --arg id "$CONFIG_ID" --arg g "$gid" '
            .[$id] as $r
            | if ($r.GUILD[$g] == null and $r.MEMBER[$g] == null) then error("no data for guild \($g)") else . end
            | {($id): {GUILD: {($g): ($r.GUILD[$g] // {})}, MEMBER: {($g): ($r.MEMBER[$g] // {})}}}
        ' "$src"
    else
        python3 -I -c '
import json, sys
src, cid, g = sys.argv[1:]
with open(src) as f:
    r = json.load(f)[cid]
guild, members = r.get("GUILD", {}).get(g), r.get("MEMBER", {}).get(g)
if guild is None and members is None:
    sys.exit(f"no data for guild {g}")
json.dump({cid: {"GUILD": {g: guild or {}}, "MEMBER": {g: members or {}}}}, sys.stdout, indent=2, ensure_ascii=False)
print()
' "$src" "$CONFIG_ID" "$gid"
    fi
}

stamp="$(date -u +%Y-%m-%d)"
for gid in "${guilds[@]}"; do
    name="${DEFAULT_GUILDS[$gid]:-guild}"
    out="$out_dir/leveler_${name}_${gid}_${stamp}.json"
    extract "$gid" > "$out"
    python3 -I -c 'import json, sys; json.load(open(sys.argv[1]))' "$out"
    members="$(python3 -I -c 'import json, sys; d = json.load(open(sys.argv[1])); print(len(d[sys.argv[2]]["MEMBER"][sys.argv[3]]))' "$out" "$CONFIG_ID" "$gid")"
    echo "$out ($members members)"
done
