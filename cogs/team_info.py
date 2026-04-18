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
import datetime as dt
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

import database
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


    # ── /nextmatch ────────────────────────────────────────────────────────────
    @app_commands.command(
        name="nextmatch",
        description="See the next upcoming match for teams you follow"
    )
    async def nextmatch(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Combine personal subscriptions + server tracked teams
        teams: set[str] = set(database.get_user_teams(interaction.user.id))
        if interaction.guild:
            teams |= set(database.get_tracked_teams(interaction.guild_id))

        if not teams:
            await interaction.followup.send(
                "You're not following any teams.\n"
                "Use `/myteam add` to subscribe personally, "
                "or ask an admin to use `/addteam` for server-wide tracking.",
                ephemeral=True,
            )
            return

        now_ts = int(dt.datetime.now(dt.timezone.utc).timestamp())

        # Collect unique active events across all teams (deduplicated)
        event_teams: dict[str, set[str]] = {}   # event_key → set of tracked teams in it
        event_data:  dict[str, dict]     = {}   # event_key → event dict

        for team in teams:
            evs = await _tba.team_events(self._session, team, CURRENT_YEAR) or []
            for ev in evs:
                key = ev.get("key")
                if not key:
                    continue
                # Only care about events that haven't ended yet
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
                "No active or upcoming events found for your followed teams.",
                ephemeral=True,
            )
            return

        # Search every active event for the earliest unplayed match
        best: dict | None = None
        best_ts:    int   = 0
        best_teams: set[str] = set()
        best_event: dict  = {}

        for event_key, ev in event_data.items():
            matches = await _tba.event_matches(self._session, event_key) or []
            tracked = event_teams[event_key]

            for m in matches:
                # Skip played matches
                if m.get("winning_alliance") or m.get("actual_time"):
                    continue

                # Skip matches not involving any followed team
                all_match_teams = {t[3:] for t in (
                    m["alliances"]["red"]["team_keys"] +
                    m["alliances"]["blue"]["team_keys"]
                )}
                teams_here = tracked & all_match_teams
                if not teams_here:
                    continue

                match_ts = m.get("predicted_time") or m.get("time") or 0
                if match_ts < now_ts:
                    continue   # scheduled in the past but not yet played (delay)

                if best is None or match_ts < best_ts:
                    best    = m
                    best_ts = match_ts
                    best_teams  = teams_here
                    best_event  = ev

        if best is None:
            await interaction.followup.send(
                "No upcoming unplayed matches found for your followed teams right now.",
                ephemeral=True,
            )
            return

        # ── Build embed ───────────────────────────────────────────────────────
        red_teams  = [t[3:] for t in best["alliances"]["red"]["team_keys"]]
        blue_teams = [t[3:] for t in best["alliances"]["blue"]["team_keys"]]
        on_red  = bool(best_teams & set(red_teams))
        on_blue = bool(best_teams & set(blue_teams))

        side = (
            "🔴 Red Alliance"  if on_red and not on_blue else
            "🔵 Blue Alliance" if on_blue and not on_red else
            "🟪 Both Alliances"
        )

        teams_str   = ", ".join(f"**#{t}**" for t in sorted(best_teams, key=int))
        event_name  = best_event.get("short_name") or best_event.get("name") or best_event.get("key", "?")
        level       = best.get("comp_level", "?").upper()
        num         = best.get("match_number", "?")
        match_label = f"{level}{num}" if level != "?" else best.get("key", "?")

        time_str = (
            f"<t:{best_ts}:F>  (<t:{best_ts}:R>)"
            if best_ts else "Time not yet scheduled"
        )

        embed = discord.Embed(
            title=f"⏭️ Next Match – {event_name}",
            description=(
                f"🏅 {teams_str}\n"
                f"🎨 **Alliance:** {side}\n"
                f"📋 **Match:** {match_label}\n\n"
                f"🕑 {time_str}"
            ),
            color=discord.Color.blurple(),
        )

        # Alliance lineups
        embed.add_field(
            name="🔴 Red Alliance",
            value="\n".join(
                f"{'**' if t in best_teams else ''}#{t}{'**' if t in best_teams else ''}"
                for t in red_teams
            ),
            inline=True,
        )
        embed.add_field(
            name="🔵 Blue Alliance",
            value="\n".join(
                f"{'**' if t in best_teams else ''}#{t}{'**' if t in best_teams else ''}"
                for t in blue_teams
            ),
            inline=True,
        )

        embed.add_field(
            name="🔗 Links",
            value=(
                f"[TBA](https://www.thebluealliance.com/match/{best['key']})  •  "
                f"[Statbotics](https://www.statbotics.io/match/{best['key']})"
            ),
            inline=False,
        )
        embed.set_footer(text="Data from The Blue Alliance • visible only to you")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamInfo(bot))
