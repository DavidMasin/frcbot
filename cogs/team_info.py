"""
cogs/team_info.py – /nextmatch command.
"""

from __future__ import annotations

import datetime as dt
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import database
import tba as _tba

CURRENT_YEAR = str(os.environ.get("FRC_SEASON", "2026"))


class TeamInfo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    @app_commands.command(name="nextmatch", description="Next upcoming match for teams you follow")
    async def nextmatch(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        teams: set[str] = set(database.get_user_teams(interaction.user.id))
        if interaction.guild:
            teams |= set(database.get_tracked_teams(interaction.guild_id))

        if not teams:
            await interaction.followup.send(
                "You're not following any teams.\n"
                "Use `/myteam add` to subscribe, or ask an admin to use `/addteam`.",
                ephemeral=True,
            )
            return

        now_ts = int(dt.datetime.now(dt.timezone.utc).timestamp())

        event_teams: dict[str, set[str]] = {}
        event_data:  dict[str, dict]     = {}

        for team in teams:
            evs = await _tba.team_events(self._session, team, CURRENT_YEAR) or []
            for ev in evs:
                key = ev.get("key")
                if not key:
                    continue
                try:
                    end = dt.date.fromisoformat(ev["end_date"])
                except (KeyError, ValueError):
                    continue
                if end < dt.date.today() - dt.timedelta(days=1):
                    continue
                event_teams.setdefault(key, set()).add(team)
                event_data[key] = ev

        if not event_data:
            await interaction.followup.send(
                "No active or upcoming events found for your followed teams.", ephemeral=True
            )
            return

        best: dict | None = None
        best_ts = 0
        best_teams: set[str] = set()
        best_event: dict = {}

        for event_key, ev in event_data.items():
            matches = await _tba.event_matches(self._session, event_key) or []
            tracked = event_teams[event_key]
            for m in matches:
                if m.get("winning_alliance") or m.get("actual_time"):
                    continue
                all_match_teams = {t[3:] for t in (
                    m["alliances"]["red"]["team_keys"] +
                    m["alliances"]["blue"]["team_keys"]
                )}
                teams_here = tracked & all_match_teams
                if not teams_here:
                    continue
                match_ts = m.get("predicted_time") or m.get("time") or 0
                if match_ts < now_ts:
                    continue
                if best is None or match_ts < best_ts:
                    best = m; best_ts = match_ts
                    best_teams = teams_here; best_event = ev

        if best is None:
            await interaction.followup.send(
                "No upcoming unplayed matches found right now.", ephemeral=True
            )
            return

        red_teams  = [t[3:] for t in best["alliances"]["red"]["team_keys"]]
        blue_teams = [t[3:] for t in best["alliances"]["blue"]["team_keys"]]
        on_red     = bool(best_teams & set(red_teams))
        on_blue    = bool(best_teams & set(blue_teams))
        side       = (
            "🔴 Red Alliance"  if on_red and not on_blue else
            "🔵 Blue Alliance" if on_blue and not on_red else
            "🟪 Both Alliances"
        )
        teams_str   = ", ".join(f"**#{t}**" for t in sorted(best_teams, key=lambda x: int(x) if x.isdigit() else 0))
        event_name  = best_event.get("short_name") or best_event.get("name") or best_event.get("key", "?")
        level       = best.get("comp_level", "?").upper()
        num         = best.get("match_number", "?")
        match_label = f"{level}{num}" if level != "?" else best.get("key", "?")
        time_str    = f"<t:{best_ts}:F>  (<t:{best_ts}:R>)" if best_ts else "Time not yet scheduled"

        embed = discord.Embed(
            title=f"⏭️ Next Match – {event_name}",
            description=(
                f"🏅 {teams_str}\n🎨 **Alliance:** {side}\n"
                f"📋 **Match:** {match_label}\n\n🕑 {time_str}"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🔴 Red Alliance",
            value="\n".join(f"{'**' if t in best_teams else ''}#{t}{'**' if t in best_teams else ''}" for t in red_teams),
            inline=True,
        )
        embed.add_field(
            name="🔵 Blue Alliance",
            value="\n".join(f"{'**' if t in best_teams else ''}#{t}{'**' if t in best_teams else ''}" for t in blue_teams),
            inline=True,
        )
        embed.add_field(
            name="🔗 Links",
            value=f"[TBA](https://www.thebluealliance.com/match/{best['key']})  •  [Statbotics](https://www.statbotics.io/match/{best['key']})",
            inline=False,
        )
        embed.set_footer(text="Data from The Blue Alliance • visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamInfo(bot))
