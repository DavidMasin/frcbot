"""
cogs/config.py – Admin-only slash commands for per-server configuration.

All standalone commands use @app_commands.allowed_contexts(guilds=True, dms=False)
so Discord never shows them in a user's DM command list.
The /setup Group uses guild_only=True for the same effect.

Commands
--------
/setup channel <#channel>   – set the announcement channel
/setup adminrole <@role>    – set which role counts as "bot admin"
/addteam <number>           – track a single team for this server
/addepa <count>             – add the top <count> teams by Statbotics EPA
/removeteam <number>        – stop tracking a team
/listteams                  – show all tracked teams (ephemeral)
/serverinfo                 – show full bot config (admin)
"""

from __future__ import annotations

import asyncio
from datetime import date

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import database
import tba as _tba

# guild-only context shorthand
_GUILD_ONLY = app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)

# Discord-side permission: hides admin commands from non-admins in the UI by default.
# Server admins can override this per-channel in Discord's integration settings.
_ADMIN_PERMS = app_commands.default_permissions(manage_guild=True)

MAX_ADDEPA = 100


def is_admin():
    """
    Runtime check: user has Manage Guild OR the server's configured custom admin role.

    We raise CheckFailure with a message instead of responding directly — this lets
    discord.py's error handler send the response cleanly without double-response errors.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        # interaction.permissions is sent directly by Discord in the payload —
        # no member cache required, works correctly for owners and admins.
        if interaction.permissions.manage_guild:
            return True
        cfg = database.get_config(interaction.guild_id)
        if cfg and cfg.get("admin_role_id"):
            role = interaction.guild.get_role(cfg["admin_role_id"])
            if role and role in interaction.user.roles:
                return True
        raise app_commands.CheckFailure(
            "❌ You need **Manage Server** permission or the bot-admin role."
        )
    return app_commands.check(predicate)


class Config(commands.Cog):
    """Server configuration commands (guild-only)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        msg = str(error)
        # Unwrap CheckFailure so the user sees the actual reason
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error) or "❌ You don't have permission to use this command."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    # ── /setup ────────────────────────────────────────────────────────────────
    setup_group = app_commands.Group(
        name="setup",
        description="Admin: configure the bot for this server",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @setup_group.command(name="channel", description="Set the channel for live match announcements")
    @app_commands.describe(channel="Start typing a channel name")
    @is_admin()
    async def setup_channel(self, interaction: discord.Interaction, channel: str):
        # channel is either a channel ID (from autocomplete) or a raw mention/ID typed manually
        resolved = None
        if channel.isdigit():
            resolved = interaction.guild.get_channel(int(channel))
        else:
            # strip <#...> mention format
            stripped = channel.strip("<#>")
            if stripped.isdigit():
                resolved = interaction.guild.get_channel(int(stripped))
            else:
                # fall back to name match
                name = channel.lstrip("#").lower()
                resolved = discord.utils.get(interaction.guild.text_channels, name=name)

        if not isinstance(resolved, discord.TextChannel):
            await interaction.response.send_message(
                f"⚠️ Couldn't find a text channel matching `{channel}`. "
                "Please pick one from the autocomplete list.", ephemeral=True
            )
            return

        database.set_announce_channel(interaction.guild_id, resolved.id)
        await interaction.response.send_message(
            f"✅ Announcements will now be posted in {resolved.mention}.", ephemeral=True
        )

    @setup_channel.autocomplete("channel")
    async def setup_channel_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        return [
            app_commands.Choice(name=f"#{ch.name}", value=str(ch.id))
            for ch in interaction.guild.text_channels
            if current_lower in ch.name.lower()
        ][:25]

    @setup_group.command(name="adminrole", description="Set a role that can use admin bot commands")
    @app_commands.describe(role="The role to grant bot-admin access")
    @is_admin()
    async def setup_adminrole(self, interaction: discord.Interaction, role: discord.Role):
        database.set_admin_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Members with {role.mention} can now use admin bot commands.", ephemeral=True
        )

    # ── /addteam ──────────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="addteam", description="Track a team – bot will announce their matches")
    @_GUILD_ONLY
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    @is_admin()
    async def addteam(self, interaction: discord.Interaction, team_number: str):
        await interaction.response.defer(ephemeral=True)

        info = await _tba.team_info(self._session, team_number)
        if info is None:
            await interaction.followup.send(
                f"⚠️ Team `#{team_number}` not found on TBA.", ephemeral=True
            )
            return

        added    = database.add_tracked_team(interaction.guild_id, team_number)
        nickname = info.get("nickname", f"#{team_number}")

        if added:
            await interaction.followup.send(
                f"✅ Now tracking **{nickname}** (#{team_number}).", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"ℹ️ **{nickname}** (#{team_number}) is already being tracked.", ephemeral=True
            )

    # ── /addepa ───────────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="addepa", description="Add the top N teams by Statbotics EPA to the watch list")
    @_GUILD_ONLY
    @app_commands.describe(count="How many top-EPA teams to add, e.g. 25")
    @is_admin()
    async def addepa(self, interaction: discord.Interaction, count: int):
        await interaction.response.defer(ephemeral=True)

        if count < 1:
            await interaction.followup.send("⚠️ Count must be at least 1.", ephemeral=True)
            return
        if count > MAX_ADDEPA:
            await interaction.followup.send(
                f"⚠️ Maximum is **{MAX_ADDEPA}** teams at once.", ephemeral=True
            )
            return

        try:
            import statbotics
            sb     = statbotics.Statbotics()
            season = date.today().year

            # Statbotics doesn't support order_by — fetch a large pool and sort manually
            fetch_limit = max(count * 4, 500)
            teams_data = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sb.get_team_years(
                    year=season,
                    limit=fetch_limit,
                    offset=0,
                    fields=["team", "epa"],
                )
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to fetch EPA data from Statbotics: `{e}`", ephemeral=True
            )
            return

        if not teams_data:
            await interaction.followup.send(
                "⚠️ Statbotics returned no teams. Try again later.", ephemeral=True
            )
            return

        def _epa_val(t: dict) -> float:
            epa = t.get("epa") or {}
            if isinstance(epa, dict):
                return float(epa.get("mean") or epa.get("norm") or 0)
            return float(epa or 0)

        teams_data.sort(key=_epa_val, reverse=True)

        added_teams   = []
        already_teams = []

        for entry in teams_data[:count]:
            team_num = str(entry.get("team", "")).replace("frc", "").strip()
            if not team_num:
                continue
            if database.add_tracked_team(interaction.guild_id, team_num):
                added_teams.append(team_num)
            else:
                already_teams.append(team_num)

        embed = discord.Embed(
            title=f"📈 Top {count} EPA Teams Added",
            color=discord.Color.teal(),
        )
        if added_teams:
            preview = ", ".join(f"#{t}" for t in added_teams[:20])
            suffix  = f" and {len(added_teams) - 20} more…" if len(added_teams) > 20 else ""
            embed.add_field(
                name=f"✅ Added ({len(added_teams)})",
                value=preview + suffix,
                inline=False,
            )
        if already_teams:
            preview = ", ".join(f"#{t}" for t in already_teams[:20])
            suffix  = f" and {len(already_teams) - 20} more…" if len(already_teams) > 20 else ""
            embed.add_field(
                name=f"ℹ️ Already tracked ({len(already_teams)})",
                value=preview + suffix,
                inline=False,
            )

        embed.set_footer(text="Rankings from Statbotics • visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /removeteam ───────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="removeteam", description="Stop tracking a team")
    @_GUILD_ONLY
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    @is_admin()
    async def removeteam(self, interaction: discord.Interaction, team_number: str):
        removed = database.remove_tracked_team(interaction.guild_id, team_number)
        if removed:
            await interaction.response.send_message(
                f"🗑️ Stopped tracking team **#{team_number}**.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Team **#{team_number}** wasn't being tracked.", ephemeral=True
            )

    # ── /listteams ────────────────────────────────────────────────────────────
    @app_commands.command(name="listteams", description="List all tracked teams for this server")
    @_GUILD_ONLY
    async def listteams(self, interaction: discord.Interaction):
        teams = database.get_tracked_teams(interaction.guild_id)
        if not teams:
            await interaction.response.send_message(
                "No teams are being tracked yet. Use `/addteam` or `/addepa` to add some.",
                ephemeral=True,
            )
            return

        lines = "\n".join(f"• `#{t}`" for t in sorted(teams, key=lambda x: int(x)))
        embed = discord.Embed(
            title="📋 Tracked Teams",
            description=lines,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"{len(teams)} team(s) tracked • visible only to you")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /serverinfo ───────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="serverinfo", description="Show this server's bot configuration")
    @_GUILD_ONLY
    @is_admin()
    async def serverinfo(self, interaction: discord.Interaction):
        cfg   = database.get_config(interaction.guild_id)
        teams = database.get_tracked_teams(interaction.guild_id)

        chan_str = "Not set"
        if cfg and cfg.get("announce_channel_id"):
            chan = interaction.guild.get_channel(cfg["announce_channel_id"])
            chan_str = chan.mention if chan else f"<#{cfg['announce_channel_id']}> (deleted?)"

        role_str = "Not set (Manage Server only)"
        if cfg and cfg.get("admin_role_id"):
            role = interaction.guild.get_role(cfg["admin_role_id"])
            role_str = role.mention if role else f"<@&{cfg['admin_role_id']}> (deleted?)"

        embed = discord.Embed(title="⚙️ Bot Configuration", color=discord.Color.og_blurple())
        embed.add_field(name="📢 Announce Channel", value=chan_str, inline=False)
        embed.add_field(name="🔑 Admin Role",       value=role_str, inline=False)
        embed.add_field(
            name="🏅 Tracked Teams",
            value=", ".join(f"#{t}" for t in sorted(teams, key=lambda x: int(x))) or "None",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


    # ── /adminroles ───────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="adminroles", description="Show which roles can use admin bot commands")
    @_GUILD_ONLY
    @is_admin()
    async def adminroles(self, interaction: discord.Interaction):
        cfg = database.get_config(interaction.guild_id)

        lines = ["**Manage Server** permission — always grants access"]

        if cfg and cfg.get("admin_role_id"):
            role = interaction.guild.get_role(cfg["admin_role_id"])
            if role:
                lines.append(f"{role.mention} — set via `/setup adminrole`")
            else:
                lines.append(f"<@&{cfg['admin_role_id']}> — *(role deleted, use `/setup adminrole` to update)*")
        else:
            lines.append("*No extra role configured — use `/setup adminrole` to add one*")

        embed = discord.Embed(
            title="🔑 Bot Admin Access",
            description="".join(lines),
            color=discord.Color.og_blurple(),
        )
        embed.set_footer(text="visible only to you")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
