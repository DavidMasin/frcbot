"""
cogs/team_info.py – Public lookup slash commands (all ephemeral by default).

Commands
--------
/team   <number>            – team overview, blue banners
/events <number> [year]     – team's events
/event  <event_key>         – event overview
/matches <number> <event>   – team's matches at an event
/robots <number>            – robot names by year
/ranking <number> <event>   – team's current ranking at an event
"""

from __future__ import annotations

import collections
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

import tba as _tba

AWARD_TYPES = {
    0:  "chairmans",
    69: "chairmans_finalists",
    1:  "winner",
    3:  "woodie_flowers",
    74: "skills_competition_winner",
}

CURRENT_YEAR = "2026"


class TeamInfo(commands.Cog):
    """Public read-only FRC lookup commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    # ── /team ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="team", description="Get info about an FRC team")
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    async def team(self, interaction: discord.Interaction, team_number: str):
        await interaction.response.defer(ephemeral=True)

        team_data = await _tba.team_info(self._session, team_number)
        if not team_data:
            await interaction.followup.send(f"⚠️ Team `#{team_number}` not found on TBA.", ephemeral=True)
            return

        awards = await _tba.team_awards(self._session, team_number) or []
        counts = collections.Counter(
            AWARD_TYPES[a["award_type"]] for a in awards if a["award_type"] in AWARD_TYPES
        )
        blue_banners = sum(counts.values())

        website = team_data.get("website") or f"https://www.thebluealliance.com/team/{team_number}"
        embed = discord.Embed(
            title=f"FRC {team_data['team_number']} – {team_data.get('nickname', '?')}",
            url=website,
            color=discord.Color.from_rgb(40, 89, 165),
        )
        embed.add_field(
            name="📍 Location",
            value=(
                f"**City:** {team_data.get('city') or '—'}\n"
                f"**State/Prov.:** {team_data.get('state_prov') or '—'}\n"
                f"**Country:** {team_data.get('country') or '—'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="🏫 Team Info",
            value=(
                f"**School:** {team_data.get('school_name') or '—'}\n"
                f"**Rookie Year:** {team_data.get('rookie_year') or '—'}\n"
                f"**Key:** `{team_data['key']}`"
            ),
            inline=True,
        )

        if blue_banners:
            banner_lines = "\n".join(
                f"**{label.replace('_', ' ').title()}:** {counts[label]}"
                for label in AWARD_TYPES.values() if counts[label]
            )
            embed.add_field(
                name=f"🏆 Blue Banners ({blue_banners})",
                value=banner_lines,
                inline=False,
            )

        embed.add_field(
            name="🔗 Links",
            value=(
                f"[TBA](https://www.thebluealliance.com/team/{team_number})  •  "
                f"[Statbotics](https://www.statbotics.io/team/{team_number})  •  "
                f"[FIRST](https://frc-events.firstinspires.org/team/{team_number})"
            ),
            inline=False,
        )
        embed.set_footer(text="Data from The Blue Alliance • visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /events ───────────────────────────────────────────────────────────────
    @app_commands.command(name="events", description="Get a team's events for a given year")
    @app_commands.describe(
        team_number="FRC team number, e.g. 5987",
        year=f"Season year (default: {CURRENT_YEAR})"
    )
    async def events(self, interaction: discord.Interaction, team_number: str, year: str = CURRENT_YEAR):
        await interaction.response.defer(ephemeral=True)

        evs = await _tba.team_events(self._session, team_number, year)
        team_data = await _tba.team_info(self._session, team_number)

        if evs is None or team_data is None:
            await interaction.followup.send("⚠️ Couldn't find that team or year.", ephemeral=True)
            return

        if not evs:
            await interaction.followup.send(f"No events found for team **#{team_number}** in **{year}**.", ephemeral=True)
            return

        evs.sort(key=lambda e: e.get("start_date", ""))
        lines = "\n".join(
            f"`{e['key']}` – {e['name'].replace('(Cancelled)', '').strip()}"
            for e in evs
        )

        embed = discord.Embed(
            title=f"📅 #{team_number} – {team_data.get('nickname', '')} Events ({year})",
            description=lines,
            color=discord.Color.from_rgb(40, 89, 165),
        )
        embed.set_footer(text="visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /event ────────────────────────────────────────────────────────────────
    @app_commands.command(name="event", description="Get info about an FRC event")
    @app_commands.describe(event_key="TBA event key, e.g. 2026isde1")
    async def event(self, interaction: discord.Interaction, event_key: str):
        await interaction.response.defer(ephemeral=True)

        data = await _tba.event_info(self._session, event_key)
        if not data:
            await interaction.followup.send(f"⚠️ Event `{event_key}` not found.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🏟️ {data['name']}",
            url=f"https://www.thebluealliance.com/event/{event_key}",
            color=discord.Color.green(),
        )
        embed.add_field(name="📍 Location",
                        value=f"{data.get('city', '—')}, {data.get('state_prov', '—')}, {data.get('country', '—')}",
                        inline=False)
        embed.add_field(name="📅 Dates",
                        value=f"{data.get('start_date', '?')} → {data.get('end_date', '?')}",
                        inline=True)
        embed.add_field(name="🔑 Key", value=f"`{event_key}`", inline=True)
        embed.set_footer(text="visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /matches ──────────────────────────────────────────────────────────────
    @app_commands.command(name="matches", description="Get a team's matches at an event")
    @app_commands.describe(
        team_number="FRC team number, e.g. 5987",
        event_key="TBA event key, e.g. 2026isde1"
    )
    async def matches(self, interaction: discord.Interaction, team_number: str, event_key: str):
        await interaction.response.defer(ephemeral=True)

        match_list = await _tba.team_matches_at_event(self._session, team_number, event_key)
        if match_list is None:
            await interaction.followup.send("⚠️ Couldn't fetch matches. Check team/event key.", ephemeral=True)
            return

        if not match_list:
            await interaction.followup.send(f"No matches found for **#{team_number}** at `{event_key}`.", ephemeral=True)
            return

        match_list.sort(key=lambda m: (m.get("comp_level", ""), m.get("match_number", 0)))

        rows = []
        for m in match_list:
            level = m.get("comp_level", "?").upper()
            num   = m.get("match_number", "?")
            red   = m["alliances"]["red"]["score"]
            blue  = m["alliances"]["blue"]["score"]
            win   = m.get("winning_alliance", "")

            key  = f"frc{team_number}"
            side = "🔴" if key in m["alliances"]["red"]["team_keys"] else "🔵"

            if not win:
                result = "⏳"
            elif (win == "red" and side == "🔴") or (win == "blue" and side == "🔵"):
                result = "✅"
            else:
                result = "❌"

            rows.append(f"{result} {side} **{level}{num}** – Red {red} : Blue {blue}")

        embed = discord.Embed(
            title=f"🎮 #{team_number} @ `{event_key}`",
            description="\n".join(rows),
            color=discord.Color.from_rgb(40, 89, 165),
        )
        embed.set_footer(text="✅ win  ❌ loss  ⏳ not played • visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /robots ───────────────────────────────────────────────────────────────
    @app_commands.command(name="robots", description="Show a team's robot names by year")
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    async def robots(self, interaction: discord.Interaction, team_number: str):
        await interaction.response.defer(ephemeral=True)

        data = await _tba.team_robots(self._session, team_number)
        if not data:
            await interaction.followup.send(f"No robots found for team **#{team_number}**.", ephemeral=True)
            return

        data.sort(key=lambda r: r.get("year", 0), reverse=True)
        embed = discord.Embed(
            title=f"🤖 #{team_number} – Robots",
            color=discord.Color.from_rgb(40, 89, 165),
        )
        for r in data:
            embed.add_field(name=str(r.get("year", "?")), value=r.get("robot_name", "—"), inline=True)

        embed.set_footer(text="visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /ranking ──────────────────────────────────────────────────────────────
    @app_commands.command(name="ranking", description="Check a team's ranking at an event")
    @app_commands.describe(
        team_number="FRC team number",
        event_key="TBA event key, e.g. 2026arc"
    )
    async def ranking(self, interaction: discord.Interaction, team_number: str, event_key: str):
        await interaction.response.defer(ephemeral=True)

        data = await _tba.event_rankings(self._session, event_key)
        if not data:
            await interaction.followup.send("⚠️ Couldn't fetch rankings.", ephemeral=True)
            return

        rankings = data.get("rankings", [])
        target = f"frc{team_number}"
        row = next((r for r in rankings if r.get("team_key") == target), None)

        if not row:
            await interaction.followup.send(
                f"Team **#{team_number}** not found in `{event_key}` rankings.", ephemeral=True
            )
            return

        rank     = row.get("rank", "?")
        total    = len(rankings)
        rp       = row.get("extra_stats", [None])[0]
        wins     = row.get("wins", "?")
        losses   = row.get("losses", "?")
        ties     = row.get("ties", "?")

        embed = discord.Embed(
            title=f"🏅 #{team_number} Ranking @ `{event_key}`",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Rank",   value=f"**#{rank}** / {total}", inline=True)
        embed.add_field(name="Record", value=f"{wins}W – {losses}L – {ties}T", inline=True)
        if rp is not None:
            embed.add_field(name="RP", value=str(rp), inline=True)
        embed.set_footer(text="visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamInfo(bot))
