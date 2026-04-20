"""
cogs/config.py – Admin slash commands.

Commands
--------
/setup channel <channel>     – set announce channel
/setup adminrole <role>      – set admin role
/addteam <number>            – track a team
/addepa <count>              – add top N EPA teams
/removeteam <number>         – untrack a team
/listteams                   – list tracked teams
/serverinfo                  – show config
/adminroles                  – show admin roles
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

_GUILD_ONLY  = app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
_ADMIN_PERMS = app_commands.default_permissions(manage_guild=True)


import os


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
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
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    async def cog_app_command_error(self, interaction, error):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "❌ An error occurred."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    # ── /setup group ──────────────────────────────────────────────────────────
    setup_group = app_commands.Group(
        name="setup",
        description="Admin: configure the bot",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @setup_group.command(name="channel", description="Set the announcement channel")
    @app_commands.describe(channel="Mention the channel, e.g. #general")
    @is_admin()
    async def setup_channel(self, interaction: discord.Interaction, channel: str):
        clean = channel.strip("<#>").strip()
        if not clean.isdigit():
            await interaction.response.send_message(
                "⚠️ Mention the channel with `#`, e.g. `#general`.", ephemeral=True
            )
            return
        resolved = interaction.guild.get_channel(int(clean))
        if not isinstance(resolved, discord.TextChannel):
            await interaction.response.send_message("⚠️ That's not a text channel.", ephemeral=True)
            return
        database.set_announce_channel(interaction.guild_id, resolved.id)
        await interaction.response.send_message(
            f"✅ Announcements → {resolved.mention}", ephemeral=True
        )

    @setup_group.command(name="adminrole", description="Set a role with bot-admin access")
    @is_admin()
    async def setup_adminrole(self, interaction: discord.Interaction, role: discord.Role):
        database.set_admin_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} now has bot-admin access.", ephemeral=True
        )

    # ── /addteam ──────────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="addteam", description="Track a team – get match notifications")
    @_GUILD_ONLY
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    @is_admin()
    async def addteam(self, interaction: discord.Interaction, team_number: str):
        await interaction.response.defer(ephemeral=True)

        info = await _tba.team_info(self._session, team_number)
        if not info:
            await interaction.followup.send(f"⚠️ Team `#{team_number}` not found on TBA.", ephemeral=True)
            return

        added    = database.add_tracked_team(interaction.guild_id, team_number)
        nickname = info.get("nickname", f"#{team_number}")

        if added:
            await interaction.followup.send(
                f"✅ Now tracking **{nickname}** (#{team_number}).", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"ℹ️ **{nickname}** (#{team_number}) is already tracked.", ephemeral=True
            )

    # ── /addepa ───────────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="addepa", description="Add the top N teams by Statbotics EPA")
    @_GUILD_ONLY
    @app_commands.describe(count="How many top-EPA teams to add, e.g. 25")
    @is_admin()
    async def addepa(self, interaction: discord.Interaction, count: int):
        await interaction.response.defer(ephemeral=True)

        if not 1 <= count <= 100:
            await interaction.followup.send("⚠️ Count must be between 1 and 100.", ephemeral=True)
            return

        try:
            import statbotics
            sb = statbotics.Statbotics()
            season = date.today().year
            teams_data = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sb.get_team_years(year=season, limit=max(count * 4, 500), offset=0, fields=["team", "epa"])
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Statbotics error: `{e}`", ephemeral=True)
            return

        def _epa_val(t):
            epa = t.get("epa") or {}
            return float(epa.get("mean") or 0) if isinstance(epa, dict) else float(epa or 0)

        teams_data.sort(key=_epa_val, reverse=True)

        added, already = [], []
        for entry in teams_data[:count]:
            num = str(entry.get("team", "")).replace("frc", "").strip()
            if not num:
                continue
            (added if database.add_tracked_team(interaction.guild_id, num) else already).append(num)

        embed = discord.Embed(title=f"📈 Top {count} EPA Teams", color=discord.Color.teal())
        if added:
            preview = ", ".join(f"#{t}" for t in added[:20])
            embed.add_field(name=f"✅ Added ({len(added)})", value=preview + (" …" if len(added) > 20 else ""), inline=False)
        if already:
            preview = ", ".join(f"#{t}" for t in already[:20])
            embed.add_field(name=f"ℹ️ Already tracked ({len(already)})", value=preview + (" …" if len(already) > 20 else ""), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /removeteam ───────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="removeteam", description="Stop tracking a team")
    @_GUILD_ONLY
    @app_commands.describe(team_number="FRC team number")
    @is_admin()
    async def removeteam(self, interaction: discord.Interaction, team_number: str):
        removed = database.remove_tracked_team(interaction.guild_id, team_number)
        msg = f"🗑️ Stopped tracking **#{team_number}**." if removed else f"⚠️ **#{team_number}** wasn't tracked."
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /listteams ────────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="listteams", description="List all tracked teams")
    @_GUILD_ONLY
    async def listteams(self, interaction: discord.Interaction):
        teams = database.get_tracked_teams(interaction.guild_id)
        if not teams:
            await interaction.response.send_message("No teams tracked yet. Use `/addteam`.", ephemeral=True)
            return
        lines = "\n".join(f"• `#{t}`" for t in sorted(teams, key=lambda x: int(x) if x.isdigit() else 0))
        embed = discord.Embed(title="📋 Tracked Teams", description=lines, color=discord.Color.blurple())
        embed.set_footer(text=f"{len(teams)} team(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /serverinfo ───────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="serverinfo", description="Show bot configuration")
    @_GUILD_ONLY
    @is_admin()
    async def serverinfo(self, interaction: discord.Interaction):
        cfg   = database.get_config(interaction.guild_id)
        teams = database.get_tracked_teams(interaction.guild_id)

        chan_str = "Not set"
        if cfg and cfg.get("announce_channel_id"):
            ch = interaction.guild.get_channel(cfg["announce_channel_id"])
            chan_str = ch.mention if ch else f"<#{cfg['announce_channel_id']}>"

        role_str = "Not set"
        if cfg and cfg.get("admin_role_id"):
            role = interaction.guild.get_role(cfg["admin_role_id"])
            role_str = role.mention if role else f"<@&{cfg['admin_role_id']}>"

        embed = discord.Embed(title="⚙️ Bot Configuration", color=discord.Color.og_blurple())
        embed.add_field(name="📢 Channel",      value=chan_str, inline=False)
        embed.add_field(name="🔑 Admin Role",   value=role_str, inline=False)
        embed.add_field(name="🏅 Teams",        value=", ".join(f"#{t}" for t in sorted(teams, key=lambda x: int(x) if x.isdigit() else 0)) or "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /adminroles ───────────────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="adminroles", description="Show which roles have admin bot access")
    @_GUILD_ONLY
    @is_admin()
    async def adminroles(self, interaction: discord.Interaction):
        cfg   = database.get_config(interaction.guild_id)
        lines = ["**Manage Server** permission — always grants access"]
        if cfg and cfg.get("admin_role_id"):
            role = interaction.guild.get_role(cfg["admin_role_id"])
            lines.append(role.mention if role else f"<@&{cfg['admin_role_id']}> *(deleted?)*")
        else:
            lines.append("*No extra role set — use `/setup adminrole`*")
        embed = discord.Embed(title="🔑 Bot Admin Access", description="\n".join(lines), color=discord.Color.og_blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
