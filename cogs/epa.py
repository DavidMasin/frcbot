"""
cogs/epa.py – EPA (Expected Points Added) lookup and change tracking.

Commands
--------
/epa <team> [year]     – look up current EPA for a team (works in DMs too)
/trackepa <team>       – admin: track EPA changes and announce them (guild-only)
/untrackepa <team>     – admin: stop tracking EPA for a team (guild-only)
/epalist               – show all EPA-tracked teams for this server (guild-only)
"""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database
from cogs.config import is_admin

# guild-only context shorthand
_GUILD_ONLY = app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
_ADMIN_PERMS = app_commands.default_permissions(manage_guild=True)

try:
    import statbotics
    _sb = statbotics.Statbotics()
    _SB_AVAILABLE = True
except Exception:
    _SB_AVAILABLE = False

EPA_POLL_INTERVAL = 3600


def _get_team_epa(team_number: str, year: int | None = None) -> dict | None:
    if not _SB_AVAILABLE:
        return None
    try:
        if year:
            return _sb.get_team_year(int(team_number), year)
        return _sb.get_team(int(team_number))
    except Exception:
        return None


class EPA(commands.Cog):
    """Statbotics EPA lookup and change-tracking."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        if _SB_AVAILABLE:
            self.poll_epa_changes.start()

    async def cog_unload(self):
        self.poll_epa_changes.cancel()

    # ── /epa (works everywhere) ───────────────────────────────────────────────
    @app_commands.command(name="epa", description="Look up EPA (Expected Points Added) for a team")
    @app_commands.describe(
        team_number="FRC team number, e.g. 5987",
        year="Season year (leave blank for career overview)"
    )
    async def epa(self, interaction: discord.Interaction, team_number: str, year: int | None = None):
        await interaction.response.defer(ephemeral=True)

        if not _SB_AVAILABLE:
            await interaction.followup.send("⚠️ Statbotics library not available.", ephemeral=True)
            return

        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _get_team_epa(team_number, year)
        )

        if not data:
            await interaction.followup.send(
                f"⚠️ No EPA data found for team **#{team_number}**"
                + (f" in **{year}**" if year else "") + ".", ephemeral=True
            )
            return

        embed = _build_epa_embed(team_number, data, year)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /trackepa (guild-only) ────────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="trackepa", description="Track EPA changes for a team and announce them")
    @_GUILD_ONLY
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    @is_admin()
    async def trackepa(self, interaction: discord.Interaction, team_number: str):
        await interaction.response.defer(ephemeral=True)

        if not _SB_AVAILABLE:
            await interaction.followup.send("⚠️ Statbotics library not available.", ephemeral=True)
            return

        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _get_team_epa(team_number, 2026)
        )
        current_epa = data.get("epa", {}).get("mean") if data else None

        added = database.add_epa_tracking(interaction.guild_id, team_number, current_epa)
        if added:
            await interaction.followup.send(
                f"✅ EPA tracking enabled for **#{team_number}**."
                + (f" Baseline EPA: `{current_epa:.2f}`" if current_epa else ""),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"ℹ️ EPA tracking already enabled for **#{team_number}**.", ephemeral=True
            )

    # ── /untrackepa (guild-only) ──────────────────────────────────────────────
    @_ADMIN_PERMS
    @app_commands.command(name="untrackepa", description="Stop tracking EPA for a team")
    @_GUILD_ONLY
    @app_commands.describe(team_number="FRC team number")
    @is_admin()
    async def untrackepa(self, interaction: discord.Interaction, team_number: str):
        removed = database.remove_epa_tracking(interaction.guild_id, team_number)
        if removed:
            await interaction.response.send_message(
                f"🗑️ Stopped EPA tracking for **#{team_number}**.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ **#{team_number}** wasn't being EPA-tracked.", ephemeral=True
            )

    # ── /epalist (guild-only) ─────────────────────────────────────────────────
    @app_commands.command(name="epalist", description="Show all EPA-tracked teams for this server")
    @_GUILD_ONLY
    async def epalist(self, interaction: discord.Interaction):
        rows = database.get_epa_tracked_teams(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(
                "No teams are EPA-tracked yet. Use `/trackepa` to add one.", ephemeral=True
            )
            return

        lines = "\n".join(
            f"• `#{r['team_number']}` – last EPA: `{r['last_epa']:.2f}`" if r["last_epa"]
            else f"• `#{r['team_number']}`"
            for r in rows
        )
        embed = discord.Embed(
            title="📈 EPA Tracked Teams", description=lines, color=discord.Color.teal()
        )
        embed.set_footer(text="visible only to you")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "❌ An error occurred."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    # ── background EPA polling ────────────────────────────────────────────────
    @tasks.loop(seconds=EPA_POLL_INTERVAL)
    async def poll_epa_changes(self):
        all_tracked = database.get_all_epa_tracked()

        for guild_id, teams in all_tracked.items():
            cfg = database.get_config(guild_id)
            if not cfg or not cfg.get("announce_channel_id"):
                continue
            channel = self.bot.get_channel(cfg["announce_channel_id"])
            if not channel:
                continue

            for row in teams:
                team_number = row["team_number"]
                old_epa     = row["last_epa"]

                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _get_team_epa(team_number, 2026)
                )
                if not data:
                    continue

                new_epa = data.get("epa", {}).get("mean")
                if new_epa is None:
                    continue

                if old_epa is None:
                    database.update_last_epa(guild_id, team_number, new_epa)
                    continue

                delta = new_epa - old_epa
                if abs(delta) < 0.5:
                    continue

                direction = "📈" if delta > 0 else "📉"
                embed = discord.Embed(
                    title=f"{direction} EPA Update – Team #{team_number}",
                    description=(
                        f"**Previous EPA:** `{old_epa:.2f}`\n"
                        f"**Current EPA:**  `{new_epa:.2f}`\n"
                        f"**Change:** `{delta:+.2f}`"
                    ),
                    color=discord.Color.green() if delta > 0 else discord.Color.red(),
                )
                embed.set_footer(text="Powered by Statbotics • FRC Bot")
                await channel.send(embed=embed)
                database.update_last_epa(guild_id, team_number, new_epa)

    @poll_epa_changes.before_loop
    async def before_epa_poll(self):
        await self.bot.wait_until_ready()


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_epa_embed(team_number: str, data: dict, year: int | None) -> discord.Embed:
    epa_block    = data.get("epa", {})
    title_suffix = f" ({year})" if year else ""

    embed = discord.Embed(
        title=f"📊 Team #{team_number} EPA{title_suffix}",
        url=f"https://www.statbotics.io/team/{team_number}",
        color=discord.Color.teal(),
    )

    mean  = epa_block.get("mean")
    sd    = epa_block.get("sd")
    rank  = epa_block.get("ranks", {}).get("total", {}).get("rank")
    total = epa_block.get("ranks", {}).get("total", {}).get("count")

    if mean  is not None: embed.add_field(name="EPA (mean)",   value=f"`{mean:.2f}`",        inline=True)
    if sd    is not None: embed.add_field(name="Std Dev",      value=f"`{sd:.2f}`",           inline=True)
    if rank and total:    embed.add_field(name="Global Rank",  value=f"`#{rank}` / {total}",  inline=True)

    breakdown = epa_block.get("breakdown", {})
    if breakdown:
        parts = [
            f"**{k.replace('_', ' ').title()}:** `{v:.2f}`"
            for k, v in breakdown.items() if isinstance(v, (int, float))
        ]
        if parts:
            embed.add_field(name="Breakdown", value="\n".join(parts), inline=False)

    embed.set_footer(text="Powered by Statbotics • visible only to you")
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(EPA(bot))
