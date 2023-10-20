import discord

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

from typing import Literal

settings = {
    "PrimaryCategory": None,
    "ManagementRole": None,
    "Groups": {},
}


class ModThread(commands.Cog):
    """Used to move modmail channels to the correct category for
    processing by the right team."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=12345678941337, force_registration=True
        )
        self.config.register_guild(**settings)

# region commands
    @commands.guild_only()
    @commands.command()
    async def assign(self, ctx, group: str):
        """Assigns the current channel to role and moves channel"""
        currentCategory = ctx.channel.category
        primary_category = await self._get_primary_category(ctx.guild)
        groups = await self._get_groups(ctx.guild)

        isThread = False
        for group_name in groups:
            if currentCategory.id == groups[group_name]["category"]:
                isThread = True
            elif primary_category and currentCategory.id == primary_category.id:
                isThread = True

        if isThread is False:
            await ctx.send(
                "This channel is not in any of the ModMail Thread Categories."
            )
            return False

        if group in groups:
            category = ctx.guild.get_channel(groups[group]["category"])
            await ctx.channel.move(
                end=True,
                category=category,
                sync_permissions=True
            )

            role = ctx.guild.get_role(groups[group]["role"])
            if role:
                allowed_mentions = discord.AllowedMentions(roles=True)
                await ctx.send(
                    "This ticket has been assigned to {0}".format(
                        role.mention
                    ),
                    allowed_mentions=allowed_mentions,
                )
            else:
                await ctx.send(
                    "This ticket has been assigned to {0}".format(
                        role
                    )
                )
        else:
            assign_embed = discord.Embed(
                title="ModThread Assignment",
                description="```Syntax: ?assign <group>```",
                color=discord.Color.blue()
            )
            assign_embed.set_footer(
                text="You can also run `?unassign` to remove channel."
            )
            group_list = ""
            for group_name in groups:
                group_obj = ctx.guild.get_role(groups[group_name]["role"])
                group_list += f"\n- **{group_name}** - {group_obj.mention}"
            assign_embed.add_field(
                name="Available Groups",
                value=group_list,
                inline=False
            )
            await ctx.send(embed=assign_embed)

        return True

    @commands.guild_only()
    @commands.command()
    async def unassign(self, ctx) -> None:
        """Unassigns the modmail and moves channel to primary"""
        currentCategory = ctx.channel.category
        primary_category = await self._get_primary_category(ctx.guild)
        management_role = await self._get_management_role(ctx.guild)
        groups = await self._get_groups(ctx.guild)

        isThread = False
        for group_name in groups:
            if currentCategory.id == groups[group_name]["category"]:
                isThread = True
            elif currentCategory.id == primary_category.id:
                isThread = True

        if isThread is False:
            await ctx.send(
                "This channel is not in any of the ModMail Thread Categories."
            )
            return False

        await ctx.channel.move(
            end=True,
            category=primary_category,
            sync_permissions=True
        )

        allowed_mentions = discord.AllowedMentions(roles=True)
        await ctx.send(
            f"This ticket has been given back to {management_role.mention}",
            allowed_mentions=allowed_mentions,
        )

    # primary command group
    @commands.guild_only()
    @commands.command(name="feet")
    @checks.admin_or_permissions(manage_guild=True)
    async def _this_is_a_secret(self, ctx: commands.Context) -> None:
        """This is a secret. Nobody say anything... :shh:"""
        await ctx.send("@everyone send <@249326300148269058> some feet pics!")

    @commands.guild_only()
    @commands.group(name="modthread", aliases=["mt"])
    @checks.admin_or_permissions(manage_guild=True)
    async def modthread(self, ctx: commands.Context) -> None:
        """Display or configure modthread cog settings"""
        pass

    @modthread.command(name="category")
    async def primary_category(
        self,
        ctx: commands.Context,
        category: discord.CategoryChannel | str | None
    ) -> None:
        """View or change the primary category."""
        settings_embed = discord.Embed(
            title="ModThread Primary Category Settings",
            description="Primary Category configuration for modThread.",
            color=discord.Color.blue(),
        )

        if category is not None:
            if category in ['delete', 'rm', 'del', 'clear', 'unset']:
                category = category.lower()
                await self._set_primary_category(ctx.guild, None)
                settings_embed.add_field(
                    name="Primary Category Removed",
                    value="Not Set",
                    inline=False
                )
            elif type(category) is discord.CategoryChannel:
                set_category = await self._set_primary_category(
                    ctx.guild,
                    category
                )
                if set_category is not None:
                    settings_embed.add_field(
                        name="Category Set",
                        value=f"Category set to {set_category.jump_url}",
                        inline=False
                    )
            else:
                settings_embed.add_field(
                    name="Invalid Category",
                    value="You **must** select a Discord Category Channel.",
                    inline=False
                )

        else:
            primary_category = await self._get_primary_category(ctx.guild)
            if primary_category:
                settings_embed.add_field(
                    name="Current Category",
                    value=f"Category set to {primary_category.jump_url}",
                    inline=False
                )

        await ctx.send(embed=settings_embed)

    @modthread.command(name="role")
    async def management_role(
        self,
        ctx: commands.Context,
        role: discord.Role | str | None
    ) -> None:
        """View or change the management role."""
        settings_embed = discord.Embed(
            title="ModThread Management Role Settings",
            description="Current Management Role configuration for modThread.",
            color=discord.Color.blue(),
        )

        if role is not None:
            if role in ['delete', 'rm', 'del', 'clear', 'unset']:
                role = role.lower()
                await self._set_primary_category(ctx.guild, None)
                settings_embed.add_field(
                    name="Management Role Removed",
                    value="Not Set",
                    inline=False
                )
            elif type(role) is discord.Role:
                set_role = await self._set_management_role(
                    ctx.guild,
                    role
                )
                settings_embed.add_field(
                    name="Management Role Set",
                    value=f"Role set to {set_role.mention}",
                    inline=False
                )
            else:
                settings_embed.add_field(
                    name="Invalid Role",
                    value="You must provide a valid Discord Role",
                    inline=False
                )
        else:
            management_role = await self._get_management_role(ctx.guild)
            if management_role:
                settings_embed.add_field(
                    name="Current Management Role",
                    value=f"Management Role set to {management_role.mention}",
                    inline=False
                )

        await ctx.send(embed=settings_embed)

    @modthread.command(name="settings")
    async def settings(
        self,
        ctx: commands.Context
    ) -> None:
        """Settings command group"""

        primary_category = await self._get_primary_category(ctx.guild)
        management_role = await self._get_management_role(ctx.guild)

        settings_embed = discord.Embed(
            title="ModThread Settings",
            description="Current configuration for modThread Cog.",
            color=discord.Color.blue(),
        )

        # Check channel values before mention to avoid exception
        if primary_category:
            settings_embed.add_field(
                name="Primary Category",
                value=primary_category.jump_url,
                inline=False
            )
        else:
            settings_embed.add_field(
                name="Primary Category", value="Not Set", inline=False
            )

        if management_role:
            settings_embed.add_field(
                name="Management Role",
                value=management_role.mention,
                inline=False
            )
        else:
            settings_embed.add_field(
                name="Management Role", value="Not Set", inline=False
            )

        await ctx.send(embed=settings_embed)

    @modthread.command(name="groups", alias="group")
    async def groups(
        self,
        ctx: commands.Context,
        action: Literal["add", "update", "delete", "rm", "unset", "clear"] | None,
        group: str | None,
        category: discord.CategoryChannel | None,
        role: discord.Role | None
    ):
        """Groups command group"""

        if action:
            action = action.lower()
            if action in ["add", "update"]:
                group = group.lower()
                await self._set_group(ctx.guild, group, category, role)
                await ctx.send('Ok!')
            elif action in ['delete', 'rm', 'clear', 'unset']:
                group = group.lower()
                await self._unset_group(ctx.guild, group)
            else:
                await ctx.send(
                    'Unrecognized command. [`add`, `update`, `delete`]'
                )

        groups = await self._get_groups(ctx.guild)

        groups_embed = discord.Embed(
            title="ModThread Groups",
            description="Groups defined for assignable tickets.",
            color=discord.Color.blue(),
        )

        syntax_desc = """
```Syntax: mt groups add <group> <#category> <@role>

Example: ?mt groups add mods 1116910419458662490 @Mods```
        """
        groups_embed.add_field(
            name="Syntax",
            value=syntax_desc,
            inline=False
        )

        actions_desc = """
- **add** - `?mt groups add <group> <#category> <@role>`
- **update** - `?mt groups update <group> <#category> <@role>`
- **delete** - `?mt groups delete <group>`
        """
        groups_embed.add_field(
            name="Group Actions",
            value=actions_desc,
            inline=False
        )

        groups_list = "- *None*"
        if len(groups):
            groups_list = ""
            for group_name in groups:
                group_obj = ctx.guild.get_role(groups[group_name]["role"])
                groups_list += f"\n**{group_name}** - {group_obj.mention}"

        groups_embed.add_field(
            name="Defined Groups",
            value=groups_list,
            inline=False
        )

        await ctx.send(embed=groups_embed)
# endregion commands

# region jsondb
    async def _unset_group(
        self,
        guild: discord.Guild,
        group_name: str | None,
    ) -> None:
        groups = await self._get_groups(guild)
        groups.pop(group_name)

        await self.config.guild(
            guild
        ).Groups.set(groups)

    async def _set_group(
        self,
        guild: discord.Guild,
        group_name: str | None,
        category: discord.CategoryChannel | None,
        role: discord.Role | None
    ) -> None:
        groups = await self._get_groups(guild)

        group = {
            "category": category.id,
            "role": role.id
        }

        groups[group_name] = group
        await self.config.guild(
            guild
        ).Groups.set(groups)

    async def _get_primary_category(
        self,
        guild: discord.Guild
    ) -> discord.CategoryChannel | None:
        return discord.utils.get(
            guild.categories,
            id=await self.config.guild(guild).PrimaryCategory()
        )

    async def _get_management_role(
        self,
        guild: discord.Guild
    ) -> discord.Role | None:
        return guild.get_role(
            await self.config.guild(guild).ManagementRole()
        )

    async def _set_primary_category(
        self,
        guild: discord.Guild,
        primary_category: discord.CategoryChannel
    ) -> discord.CategoryChannel:
        set_cat = primary_category
        if set_cat is not None:
            if "id" in set_cat:
                set_cat = primary_category.id
            else:
                set_cat = None
        await self.config.guild(
            guild
        ).PrimaryCategory.set(set_cat)
        return primary_category

    async def _set_management_role(
        self,
        guild: discord.Guild,
        management_role: discord.Role
    ) -> discord.Role:
        set_role = management_role
        if set_role is not None:
            if "id" in set_role:
                set_role = management_role.id
            else:
                set_role = None
        await self.config.guild(
            guild
        ).ManagementRole.set(set_role)
        return management_role

    async def _get_groups(self, guild: discord.Guild) -> dict:
        return await self.config.guild(guild).Groups()
# endregion jsondb
