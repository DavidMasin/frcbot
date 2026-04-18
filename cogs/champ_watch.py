# cogs/champ_watch.py
"""
Live watch for Israeli teams at 2026 FIRST Championship.

• Announces when an Israeli team is about to play
• Posts the final score once it’s available

Author: you 😊   Requires discord.py 2.x and aiohttp.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Final

import aiohttp
import discord
import statbotics
from discord.ext import commands, tasks

# --------------------------------------------------------------------------- #
#  CONFIG – update these to your info
# --------------------------------------------------------------------------- #

TBA_KEY: Final[str] = "Z2VNC3RzqmYPmdIn9otts616q62uVfsJ74xr6WtEhmdq1asi7BVR4zYPCKl7geog"
NEXUS_AUTH: Final[str] = "NFkS99_q6pO8lvyC831Ia_lFkf4"
NEXUS_BASE = "https://frc.nexus/api/v1/event"
sb = statbotics.Statbotics()
# Only these teams are tracked (hardcoded, based on your list)
ISR_TEAMS: set[str] = {
    "1690", "5990", "2630", "2230", "5987", "5951",
    "3339", "2231", "6738", "5654", "5614", "1942",
}

EVENT_KEYS = [
    "2026arc", "2026cur", "2026dal", "2026gal",
    "2026hop", "2026joh", "2026mil", "2026new",
]
EVENT_KEYS_NEXUS = [
    "2026archimedes", "2026curie", "2026daly", "2026galileo",
    "2026hopper", "2026johnson", "2026milstein", "2026newton",
]

ANNOUNCE_CHANNEL_ID = 1362810453977334001  # put your channel ID here
POLL_INTERVAL = 30  # seconds

BASE_TBA = "https://www.thebluealliance.com/api/v3"
HEADERS_TBA = {"X-TBA-Auth-Key": TBA_KEY}
FIELD_NAMES = {
    "2026arc": "ARCHIMEDES",
    "2026cur": "CURIE",
    "2026dal": "DALLY",
    "2026gal": "GALILEO",
    "2026hop": "HOPPER",
    "2026joh": "JOHNSON",
    "2026mil": "MILSTEIN",
    "2026new": "NEWTON",
}

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Cog
# --------------------------------------------------------------------------- #
class ChampWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.http = aiohttp.ClientSession()
        self.seen_upcoming: dict[str, set[str]] = {event: set() for event in EVENT_KEYS_NEXUS}
        self.seen_played: dict[str, set[str]] = {event: set() for event in EVENT_KEYS}
        self.latest_played: dict[str, int] = {}
        self.team_ranks_before: dict[str, int] = {}
        self.team_ranks_now: dict[str, int] = {}

        print("ChampWatch loaded with hardcoded team list 🚀")
        asyncio.create_task(self._start_watch())

    async def _update_team_rankings_for_all_events(self):
        """Fetch initial team rankings from TBA."""
        for event in EVENT_KEYS:
            await self._update_team_rankings(event)

    async def _update_team_rankings(self, event_key: str):
        """Fetch and update current rankings from TBA for an event."""
        url = f"{BASE_TBA}/event/{event_key}/rankings"
        async with self.http.get(url, headers=HEADERS_TBA) as r:
            if r.status != 200:
                print(f"Failed to fetch rankings for {event_key}")
                return

            data = await r.json()
            rankings = data.get("rankings", [])
            for rank_info in rankings:
                team_key = rank_info.get("team_key", "")
                if team_key.startswith("frc"):
                    team_number = team_key[3:]
                    if team_number in ISR_TEAMS:
                        rank = rank_info.get("rank", None)
                        if rank:
                            self.team_ranks_now[team_number] = rank

    def _build_ranking_movement_text(self, israeli_teams: set[str]) -> str:
        """Build a ranking movement text (up/down/stay) for embed."""
        lines = []
        for team in israeli_teams:
            before = self.team_ranks_before.get(team)
            now = self.team_ranks_now.get(team)

            if before is None or now is None:
                lines.append(f"🏅 #{team}: Unknown")
                continue

            if now < before:
                movement = "🔼"
            elif now > before:
                movement = "🔽"
            else:
                movement = "➡️"

            lines.append(f"🏅 #{team}: #{now} {movement}")

        return "\n".join(lines) if lines else "🏅 Rankings unknown"

    async def cog_unload(self):
        self.watch_matches.cancel()
        await self.http.close()

    async def _mark_existing_played_matches(self):
        print("Marking existing played matches...")
        for event in EVENT_KEYS:
            url = f"{BASE_TBA}/event/{event}/matches/simple"
            async with self.http.get(url, headers=HEADERS_TBA) as r:
                if r.status != 200:
                    continue
                matches = await r.json()

            played = [m for m in matches if m.get("winning_alliance")]
            if played:
                self.latest_played[event] = max(m["match_number"] for m in played)
                self.seen_played[event].update(m["key"] for m in played)
                print(f" {event}: {len(self.seen_played[event])} played matches seen ✅")
            else:
                self.latest_played[event] = 0
                print(f" {event}: No played matches yet")
    async def _start_watch(self):
        await self.bot.wait_until_ready()
        await self._mark_existing_played_matches()

        # Get the channel early
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel:
            print("❌ Couldn't find channel!")
            return

        self.watch_matches.start()
        print("watch_matches started ✅")

    @tasks.loop(seconds=POLL_INTERVAL)
    async def watch_matches(self):
        print("--- poll tick ---")
        try:
            await self.poll_upcoming()
            await self.poll_results()
        except Exception as e:
            print("watch_matches error:", e)
            import traceback;
            traceback.print_exc()

    def _build_match_view(self, match_key: str, event_key: str) -> discord.ui.View:
        """Build a Discord view with buttons for Twitch, TBA, and Statbotics links."""
        view = discord.ui.View()

        # Twitch link per field
        field_streams = {
            "2026arc": "https://twitch.tv/firstinspires_archimedes",
            "2026cur": "https://twitch.tv/firstinspires_curie",
            "2026dal": "https://twitch.tv/firstinspires_daly",
            "2026gal": "https://twitch.tv/firstinspires_galileo",
            "2026hop": "https://twitch.tv/firstinspires_hopper",
            "2026joh": "https://twitch.tv/firstinspires_johnson",
            "2026mil": "https://twitch.tv/firstinspires_milstein",
            "2026new": "https://twitch.tv/firstinspires_newton",
        }

        twitch_url = field_streams.get(event_key, "https://twitch.tv/firstinspires")

        view.add_item(discord.ui.Button(label="📺 Twitch Live", url=twitch_url))
        view.add_item(
            discord.ui.Button(label="🔵 View on TBA", url=f"https://www.thebluealliance.com/match/{match_key}"))
        view.add_item(
            discord.ui.Button(label="📊 View on Statbotics", url=f"https://www.statbotics.io/match/{match_key}"))

        return view

    async def poll_upcoming(self):
        global win_pred, winner_pred

        print("Checking upcoming matches (using Nexus)")
        now_ms = int(dt.datetime.now().timestamp() * 1000)  # current time in ms

        for i, event in enumerate(EVENT_KEYS_NEXUS):
            try:
                url = f"{NEXUS_BASE}/{event}"
                headers = {"Nexus-Api-Key": NEXUS_AUTH}
                async with self.http.get(url, headers=headers, ssl=False) as r:
                    if r.status != 200:
                        print(f" Nexus failed for {event}: {r.status}")
                        continue
                    event_data = await r.json()

                matches = event_data.get("matches", [])
                print(f" {event}: {len(matches)} matches received")

                for m in matches:
                    label = m.get("label", "")
                    status = m.get("status", "")
                    red_teams = m.get("redTeams", [])
                    blue_teams = m.get("blueTeams", [])
                    times = m.get("times", {})

                    on_field_time = times.get("estimatedStartTime")
                    if not on_field_time:
                        print(f"  - Skipping {label} (no timing info)")
                        continue

                    if on_field_time < now_ms:
                        print(f"  - Skipping {label} (already played)")
                        continue

                    all_teams = set(red_teams + blue_teams)
                    israeli_teams_in_match = ISR_TEAMS & all_teams
                    if not israeli_teams_in_match:
                        print(f"  - Skipping {label} (no Israeli teams)")
                        continue

                    match_key = f"{EVENT_KEYS[i]}_{label.replace('Qualification', 'qm').replace('Final', 'f1m').replace('Playoff', 'sf').replace(' ', '').lower()}"
                    if match_key.find("sf"):
                        match_key= f"{match_key}m1"
                    field_name = FIELD_NAMES.get(EVENT_KEYS[i], "UNKNOWN FIELD")
                    ms_until_match = max(0, on_field_time - now_ms)
                    minutes_until = ms_until_match // 60000

                    print(f"  - Found Israeli match: {label} ({status}), starts in {minutes_until} min")

                    # --- Fetch Statbotics prediction ---
                    try:
                        if status != "Queuing soon" and status != "Now queuing":
                            stat_m = sb.get_match(match_key)
                            winner_pred = stat_m.get('pred', {}).get('winner', 'unknown')
                            red_win_prob = stat_m.get('pred', {}).get('red_win_prob', 0.5)
                            # Determine which alliance Israeli team is on
                            israeli_alliance = 'red' if ISR_TEAMS & set(red_teams) else 'blue'
                            if israeli_alliance == 'blue':
                                win_pred = 1 - red_win_prob
                            else:
                                win_pred = red_win_prob
                            print(f"    - Statbotics: winner_pred={winner_pred}, win_pred={win_pred:.2%}")
                    except Exception as e:
                        print(f"    - Statbotics error for {match_key}: {e}")

                    # --- Send "On deck" announcement ---
                    if status == "On deck" and label not in self.seen_upcoming[event]:
                        print(f"    -> Announcing ON DECK: {label}")

                        israeli_team_names = []
                        israeli_sides = []

                        for team in israeli_teams_in_match:
                            # Detect side
                            if team in red_teams:
                                israeli_sides.append('red')
                            elif team in blue_teams:
                                israeli_sides.append('blue')

                            # Get nickname from TBA
                            tba_url = f"{BASE_TBA}/team/frc{team}"
                            async with self.http.get(tba_url, headers=HEADERS_TBA) as tba_r:
                                if tba_r.status == 200:
                                    tba_data = await tba_r.json()
                                    israeli_team_names.append(tba_data.get("nickname", f"#{team}"))
                                else:
                                    israeli_team_names.append(f"#{team}")

                        names_string = ", ".join(israeli_team_names)

                        # Determine side
                        if all(side == "red" for side in israeli_sides):
                            alliance_color = "🔴 Red Alliance"
                        elif all(side == "blue" for side in israeli_sides):
                            alliance_color = "🔵 Blue Alliance"
                        else:
                            alliance_color = "🟪 Both Alliances"

                        # Fetch Statbotics prediction
                        try:
                            if status != "Queuing soon" and status != "Now queuing":

                                stat_m = sb.get_match(match_key)
                                winner_pred = stat_m.get('pred', {}).get('winner', 'unknown')
                                red_win_prob = stat_m.get('pred', {}).get('red_win_prob', 0.5)

                                if all(side == "blue" for side in israeli_sides):
                                    win_pred = 1 - red_win_prob
                                elif all(side == "red" for side in israeli_sides):
                                    win_pred = red_win_prob
                                else:
                                    win_pred = 0.5
                                print(f"    - Statbotics: winner_pred={winner_pred}, win_pred={win_pred:.2%}")
                        except Exception as e:
                            print(f"    - Statbotics error for {match_key}: {e}")
                            winner_pred = "unknown"
                            win_pred = 0.5

                        embed = discord.Embed(
                            title=f"🛫 {field_name} - {label}",
                            description=(
                                f"🇮🇱 Israeli Team(s): **{names_string}**\n"
                                f"🎨 **Starting on:** {alliance_color}\n\n"
                                f"🏆 **Win Probability:** {win_pred:.1%} (Powered By Statbotics)\n"
                                f"🔮 **Predicted Winner:** {winner_pred.upper()}\n\n"
                                f"🕑 Starts in approx **{minutes_until} min**!"
                            ),
                            color=discord.Color.gold(),
                        )
                        embed.set_footer(text="#BringThemHome")

                        chan = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
                        if chan:
                            await chan.send(embed=embed, view=self._build_match_view(match_key, EVENT_KEYS[i]))
                        self.seen_upcoming[event].add(label)

                    # --- Send "Starting Now" announcement ---
                    if status == "On field" and (label + "_start") not in self.seen_upcoming[event]:
                        print(f"    -> Announcing STARTING NOW: {label}")

                        israeli_team_names = []
                        israeli_sides = []

                        for team in israeli_teams_in_match:
                            # Check which side the team is on
                            if team in red_teams:
                                israeli_sides.append('red')
                            elif team in blue_teams:
                                israeli_sides.append('blue')

                            # Get name from TBA
                            tba_url = f"{BASE_TBA}/team/frc{team}"
                            async with self.http.get(tba_url, headers=HEADERS_TBA) as tba_r:
                                if tba_r.status == 200:
                                    tba_data = await tba_r.json()
                                    israeli_team_names.append(tba_data.get("nickname", f"#{team}"))
                                else:
                                    israeli_team_names.append(f"#{team}")

                        names_string = ", ".join(israeli_team_names)

                        # Determine alliance side description
                        if all(side == "red" for side in israeli_sides):
                            alliance_color = "🔴 Red Alliance"
                        elif all(side == "blue" for side in israeli_sides):
                            alliance_color = "🔵 Blue Alliance"
                        else:
                            alliance_color = "🟪 Both Alliances"

                        # Fetch Statbotics prediction
                        try:
                            stat_m = sb.get_match(match_key)
                            winner_pred = stat_m.get('pred', {}).get('winner', 'unknown')
                            red_win_prob = stat_m.get('pred', {}).get('red_win_prob', 0.5)

                            # Israeli color for prediction
                            if all(side == "blue" for side in israeli_sides):
                                win_pred = 1 - red_win_prob
                            elif all(side == "red" for side in israeli_sides):
                                win_pred = red_win_prob
                            else:
                                win_pred = 0.5  # split if on both alliances
                            print(f"    - Statbotics: winner_pred={winner_pred}, win_pred={win_pred:.2%}")
                        except Exception as e:
                            print(f"    - Statbotics error for {match_key}: {e}")
                            winner_pred = "unknown"
                            win_pred = 0.5

                        embed = discord.Embed(
                            title=f"🔥 MATCH STARTING NOW on {field_name}!",
                            description=(
                                f"🇮🇱 Israeli Team(s): **{names_string}**\n"
                                f"🎨 **Starting on:** {alliance_color}\n\n"
                                f"🏆 **Win Probability:** {win_pred:.1%}\n"
                                f"🔮 **Predicted Winner:** {winner_pred.upper()}\n\n"
                                f"🏟️ Field: {field_name}\n"
                                f"🕑 Match: {label}"
                            ),
                            color=discord.Color.red(),
                        )
                        embed.set_footer(text="#BringThemHome")

                        chan = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
                        if chan:
                            await chan.send(embed=embed, view=self._build_match_view(match_key, EVENT_KEYS[i]))
                        self.seen_upcoming[event].add(label + "_start")

            except Exception as e:
                print(f"Error polling Nexus for {event}: {e}")
                import traceback;
                traceback.print_exc()

    async def _get_event_matches(self, event_key):
        """Still needed for TBA results only."""
        url = f"{BASE_TBA}/event/{event_key}/matches"
        async with self.http.get(url, headers=HEADERS_TBA) as r:
            if r.status != 200:
                return []
            return await r.json()

    def _build_upcoming_embed_nexus(self, match: dict, event_key: str) -> discord.Embed:
        """Build a pretty upcoming match embed from Nexus data."""
        field_name = FIELD_NAMES.get(event_key, "UNKNOWN FIELD")
        red_teams = match.get("redTeams", [])
        blue_teams = match.get("blueTeams", [])
        label = match.get("label", "Unknown Match")
        status = match.get("status", "Unknown")

        israeli_red = ISR_TEAMS & set(red_teams)
        israeli_blue = ISR_TEAMS & set(blue_teams)
        israeli_in_match = ISR_TEAMS & (set(red_teams) | set(blue_teams))

        if not israeli_in_match:
            israeli_in_match = {"Unknown"}

        side = "🔴 Red Alliance" if israeli_red else "🔵 Blue Alliance" if israeli_blue else "Unknown Side"
        israel_str = ", ".join(f"#{team}" for team in sorted(israeli_in_match))

        embed = discord.Embed(
            title=f"🏟️ {field_name} - {label}",
            description=(f"🇮🇱 **{israel_str}** playing soon!\n"
                         f"🕑 **Status:** {status}\n"
                         f"**Starting On:** {side}\n\n"
                         f"🔴 **Red Alliance**\n"
                         f"{chr(10).join(f'• #{team}' for team in red_teams)}\n\n"
                         f"🔵 **Blue Alliance**\n"
                         f"{chr(10).join(f'• #{team}' for team in blue_teams)}"),
            color=discord.Color.blue() if israeli_blue else discord.Color.red(),
        )
        embed.set_footer(text="#BringThemHome")

        return embed

    async def poll_results(self):
        print("Checking results")
        for event in EVENT_KEYS:
            matches = await self._get_event_matches(event)
            played = [m for m in matches if m.get("winning_alliance")]

            await self._update_team_rankings(event)  # << ADD THIS

            for m in played:
                if m["key"] in self.seen_played[event]:
                    continue

                if self._has_israeli_team(m):
                    print(f" Announcing result {m['key']}")
                    chan = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
                    if chan:
                        await chan.send(embed=self._result_embed(m))
                    self.seen_played[event].add(m["key"])
                    self.latest_played[event] = max(self.latest_played.get(event, 0), m["match_number"])

            self.team_ranks_before = self.team_ranks_now.copy()  # << UPDATE history after batch

    def _has_israeli_team(self, match):
        teams = {t[3:] for t in match["alliances"]["red"]["team_keys"] +
                 match["alliances"]["blue"]["team_keys"]}
        return bool(teams & ISR_TEAMS)

    def _result_embed(self, m):
        field = FIELD_NAMES.get(m["event_key"], "UNKNOWN FIELD")
        red_teams = [t[3:] for t in m["alliances"]["red"]["team_keys"]]
        blue_teams = [t[3:] for t in m["alliances"]["blue"]["team_keys"]]

        israeli_red = ISR_TEAMS & set(red_teams)
        israeli_blue = ISR_TEAMS & set(blue_teams)
        all_teams = set(red_teams + blue_teams)
        israeli_in_match = ISR_TEAMS & all_teams

        if not israeli_in_match:
            israeli_in_match = {"Unknown"}

        on_red = bool(israeli_in_match & set(red_teams))
        on_blue = bool(israeli_in_match & set(blue_teams))

        red_score = m["alliances"]["red"]["score"]
        blue_score = m["alliances"]["blue"]["score"]
        winner = "Red" if red_score > blue_score else "Blue" if blue_score > red_score else "Tie"

        # Pull RP from score breakdown if available
        rp_red = m.get("score_breakdown", {}).get("red", {}).get("rp", 0)
        rp_blue = m.get("score_breakdown", {}).get("blue", {}).get("rp", 0)
        rp = rp_red if on_red else rp_blue if on_blue else 0

        # Outcome
        if winner == "Tie":
            outcome = "tied 🤝"
        elif (winner == "Red" and on_red) or (winner == "Blue" and on_blue):
            outcome = "won! 🎉"
        else:
            outcome = "lost 💔"

        # Title and message
        israel_str = ", ".join(f"#{team}" for team in sorted(israeli_in_match))
        alliance_result = "(Winner)" if (winner == "Red" and on_red) or (winner == "Blue" and on_blue) else "(Loser)"

        embed = discord.Embed(
            title=f"🏟️ {field} - Qualification Match {m['match_number']}",
            description=(
                f"🇮🇱 Israeli Teams {outcome}\n"
                f"{israel_str}\n\n"
                f"🔴 **Red Alliance** {'(Winner)' if winner == 'Red' else '(Loser)'}\n"
                f"{chr(10).join(f'• #{team}' for team in red_teams)}\n\n"
                f"🔵 **Blue Alliance** {'(Winner)' if winner == 'Blue' else '(Loser)'}\n"
                f"{chr(10).join(f'• #{team}' for team in blue_teams)}\n\n"
                f"🏅 **Score:** Red {red_score} - Blue {blue_score}\n"
                f"📈 **RP Earned:** {rp}\n"
                f"{self._build_ranking_movement_text(israeli_in_match)}"
            ),
            color=discord.Color.green() if outcome == "won! 🎉" else discord.Color.red() if outcome == "lost 💔" else discord.Color.greyple()
        )

        embed.set_footer(text="#BringThemHome")

        return embed


# --------------------------------------------------------------------------- #
#  entry point
# --------------------------------------------------------------------------- #
async def setup(bot: commands.Bot):
    await bot.add_cog(ChampWatch(bot))
