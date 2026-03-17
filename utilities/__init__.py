import discord


async def remove_prefix(member: discord.Member) -> str:
    """Remove team prefix from guild members display name"""
    result = member.display_name.split(" | ", maxsplit=1)
    if not result:
        raise ValueError(f"Unable to remove prefix from {member.display_name}")
    elif len(result) == 1:
        return result[0].strip()  # No prefix found
    else:
        return result[1].strip()
