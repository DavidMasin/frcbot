"""
cogs/live_watch.py – Generic live match watcher.

Dynamically discovers every active event for every tracked team by querying TBA,
then polls those events for upcoming matches (via Nexus) and final results (via TBA).
Works for regional, district, district championship, and championship events alike.

Flow
----
Every EVENT_CACHE_INTERVAL seconds:
  • Fetch each tracked team's current-year events from TBA
  • Build a unified set of active event keys per guild

Every POLL_INTERVAL seconds:
  • For each active event, query Nexus for queue status → "on deck / on field" alerts
  • For each active event, query TBA for completed matches → result embeds
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from typing import Final

import aiohttp
import discord
from discord.ext import commands, tasks

import database
import tba as _tba

log = logging.getLogger("live_watch")

NEXUS_AUTH: Final[str] = os.environ.get("NEXUS_AUTH", "NFkS99_q6pO8lvyC831Ia_lFkf4")
NEXUS_BASE  = "https://frc.nexus/api/v1/event"
SEASON      = int(os.environ.get("FRC_SEASON", "2026"))

POLL_INTERVAL        = 30    # seconds – how often to check for new matches / queue status
EVENT_CACHE_INTERVAL = 300   # seconds – how often to re-fetch each team's event list

# Nexus uses different identifiers only for CMP divisions; all other events match TBA keys.
_TBA_TO_NEXUS_OVERRIDE: dict[str, str] = {
    "2026arc": "2026archimedes",
    "2026cur": "2026curie",
    "2026dal": "2026daly",
    "2026gal": "2026galileo",
    "2026hop": "2026hopper",
    "2026joh": "2026johnson",
    "2026mil": "2026milstein",
    "2026new": "2026newton",
}

try:
    import statbotics
    _sb = statbotics.Statbotics()
    _SB_OK = True
except Exception:
    _SB_OK = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nexus_key(tba_key: str) -> str:
    """Return the Nexus event identifier for a given TBA event key."""
    return _TBA_TO_NEXUS_OVERRIDE.get(tba_key, tba_key)


def _display_name(event_data: dict) -> str:
    """Human-readable event name from a TBA event dict."""
    return event_data.get("short_name") or event_data.get("name") or event_data.get("key", "?")


def _nexus_label_to_match_key(tba_event: str, label: str) -> str:
    """Convert a Nexus label like 'Qualification 12' → TBA key '2026isde1_qm12'."""
    s = label.lower().replace(" ", "")
    if s.startswith("qualification"):
        return f"{tba_event}_qm{s.removeprefix('qualification')}"
    if s.startswith("final"):
        num = s.removeprefix("final") or "1"
        return f"{tba_event}_f1m{num}"
    if s.startswith("semifinal"):
        num = s.removeprefix("semifinal") or "1"
        return f"{tba_event}_sf{num}m1"
    if s.startswith("playoff"):
        num = s.removeprefix("playoff") or "1"
        return f"{tba_event}_sf{num}m1"
    return f"{tba_event}_{s}"


def _is_event_active(event: dict) -> bool:
    """True if this event is ongoing or upcoming within the current season."""
    today = dt.date.today()
    try:
        end   = dt.date.fromisoformat(event["end_date"])
        start = dt.date.fromisoformat(event["start_date"])
    except (KeyError, ValueError):
        return False
    # Include events that ended up to 1 day ago (results may still trickle in)
    return end >= today - dt.timedelta(days=1) and start.year == SEASON


def _webcast_url(event_data: dict) -> str | None:
    """
    Return the stream URL that is most likely live right now.
    Uses the current event day as an index into TBA's webcasts array,
    so day-specific streams (YouTube etc.) match what's actually broadcasting.
    Clamps to the last entry if we're past the end of the schedule.
    """
    webcasts = event_data.get("webcasts") or []
    valid    = [w for w in webcasts if w.get("channel")]
    if not valid:
        return None

    # Work out which day of the event we're on (0 = first day)
    day_index = 0
    try:
        start     = dt.date.fromisoformat(event_data["start_date"])
        day_index = max(0, (dt.date.today() - start).days)
    except (KeyError, ValueError):
        pass

    w       = valid[min(day_index, len(valid) - 1)]
    wtype   = w.get("type", "")
    channel = w.get("channel", "")

    if wtype == "youtube":
        return f"https://youtube.com/watch?v={channel}"
    if wtype == "twitch":
        return f"https://twitch.tv/{channel}"
    if wtype == "livestream":
        return f"https://livestream.com/{channel}"
    if wtype == "ustream":
        return f"https://ustream.tv/channel/{channel}"
    if wtype == "iframe":
        return channel
    return None


def _match_view(match_key: str, webcast_url: str | None) -> discord.ui.View:
    view = discord.ui.View()
    if webcast_url:
        view.add_item(discord.ui.Button(label="📺 Watch Live", url=webcast_url))
    view.add_item(discord.ui.Button(
        label="🔵 TBA",
        url=f"https://www.thebluealliance.com/match/{match_key}",
    ))
    view.add_item(discord.ui.Button(
        label="📊 Statbotics",
        url=f"https://www.statbotics.io/match/{match_key}",
    ))
    return view


def _win_probability(match_key: str, side: str) -> tuple[float, str] | tuple[None, None]:
    """
    Returns (win_prob, predicted_winner) from Statbotics, or (None, None) if
    the match isn't found or has no prediction yet.  Never returns a fake 50%.
    """
    if not _SB_OK:
        return None, None
    try:
        m    = _sb.get_match(match_key)
        if not m:
            return None, None
        pred = m.get("pred") or {}
        rwp  = pred.get("red_win_prob")
        winner = pred.get("winner")
        if rwp is None or winner is None:
            return None, None
        prob = float(rwp) if side == "red" else 1 - float(rwp)
        return prob, str(winner)
    except Exception as e:
        log.debug("Statbotics lookup failed for %s: %s", match_key, e)
        return None, None


# ── Main cog ──────────────────────────────────────────────────────────────────

class LiveWatch(commands.Cog):
    """
    Watches all events for tracked teams and announces match queue status
    and results to each guild's configured channel.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._http: aiohttp.ClientSession | None = None

        # {guild_id: {tba_event_key: event_dict}}  – refreshed periodically
        self._active_events: dict[int, dict[str, dict]] = {}

        # Dedup sets
        self._seen_upcoming: set[tuple] = set()   # (guild_id, nexus_key, label, stage)
        self._seen_results:  set[tuple] = set()   # (guild_id, match_key)

        # Nickname cache to avoid hammering TBA
        self._nickname_cache: dict[str, str] = {}

        # Rankings cache: {event_key: {team_number: rank}}
        # Stores rankings BEFORE each match so we can show movement after
        self._rankings_before: dict[str, dict[str, int]] = {}
        self._rankings_now:    dict[str, dict[str, int]] = {}

    async def cog_load(self):
        self._http = aiohttp.ClientSession()
        asyncio.create_task(self._start())

    async def cog_unload(self):
        self._refresh_events.cancel()
        self._poll.cancel()
        if self._http:
            await self._http.close()

    # ── Startup ───────────────────────────────────────────────────────────────

    async def _start(self):
        await self.bot.wait_until_ready()
        await self._do_refresh_events()
        await self._seed_played()
        self._refresh_events.start()
        self._poll.start()
        total_events = sum(len(v) for v in self._active_events.values())
        log.info("LiveWatch ready – watching %d event(s) across %d guild(s)",
                 total_events, len(self._active_events))

    # ── Event discovery ───────────────────────────────────────────────────────

    async def _do_refresh_events(self):
        """
        Query TBA for every tracked team's SEASON events, then update
        _active_events with the subset that are currently active/upcoming.
        """
        all_guild_teams = database.get_all_tracked_teams()

        # De-duplicate API calls: fetch each team's events once, share across guilds
        all_teams: set[str] = {t for teams in all_guild_teams.values() for t in teams}
        team_event_map: dict[str, list[dict]] = {}
        for team in all_teams:
            evs = await _tba.team_events(self._http, team, str(SEASON))
            team_event_map[team] = evs or []
            log.debug("Team %s has %d events in %d", team, len(team_event_map[team]), SEASON)

        # Collect all unique active event keys across every guild
        all_active_keys: set[str] = set()
        guild_event_keys: dict[int, set[str]] = {}
        for guild_id, tracked_teams in all_guild_teams.items():
            keys: set[str] = set()
            for team in tracked_teams:
                for ev in team_event_map.get(team, []):
                    if not isinstance(ev, dict):
                        continue
                    key = ev.get("key")
                    if not isinstance(key, str):
                        continue
                    if _is_event_active(ev):
                        keys.add(key)
                        all_active_keys.add(key)
            guild_event_keys[guild_id] = keys

        # Fetch full event data (includes webcasts) for each unique key.
        # Re-use cached data for keys we already have so we don't hammer TBA.
        existing_full: dict[str, dict] = {}
        for ev_map in self._active_events.values():
            existing_full.update(ev_map)

        full_event_data: dict[str, dict] = {}
        for key in all_active_keys:
            if key in existing_full and existing_full[key].get("webcasts") is not None:
                full_event_data[key] = existing_full[key]  # already have full data
            else:
                data = await _tba.event_full(self._http, key)
                if data:
                    full_event_data[key] = data
                    log.debug("Fetched full event data for %s", key)

        new_cache: dict[int, dict[str, dict]] = {}
        for guild_id, keys in guild_event_keys.items():
            events_for_guild = {k: full_event_data[k] for k in keys if k in full_event_data}

            prev = set(self._active_events.get(guild_id, {}))
            curr = set(events_for_guild)
            if curr - prev:
                log.info("Guild %s: added events %s", guild_id, ", ".join(curr - prev))
            if prev - curr:
                log.info("Guild %s: removed events %s", guild_id, ", ".join(prev - curr))

            new_cache[guild_id] = events_for_guild

        self._active_events = new_cache

        # Check for newly registered events and announce them
        await self._check_new_event_registrations(all_guild_teams, team_event_map, full_event_data)

    async def _check_new_event_registrations(
        self,
        all_guild_teams: dict[int, list[str]],
        team_event_map: dict[str, list[dict]],
        full_event_data: dict[str, dict],
    ) -> None:
        """
        For each guild, compare each team's current TBA event list against
        known_team_events in the DB.

        Per-team seeding logic:
          - known_keys is EMPTY for this team → first time we've seen it
            (either bot first-run or a new /addteam). Seed silently, no announcement.
          - known_keys has entries → team was already tracked. Any new_keys are
            genuinely new event registrations → announce them.
        """
        for guild_id, tracked_teams in all_guild_teams.items():
            cfg = database.get_config(guild_id)
            channel = (
                self.bot.get_channel(cfg["announce_channel_id"])
                if cfg and cfg.get("announce_channel_id") else None
            )

            for team in tracked_teams:
                current_keys: set[str] = set()
                for ev in team_event_map.get(team, []):
                    if not isinstance(ev, dict):
                        continue
                    k = ev.get("key")
                    if isinstance(k, str) and k:
                        current_keys.add(k)
                if not current_keys:
                    continue

                known_keys = database.get_known_events(guild_id, team)
                new_keys   = current_keys - known_keys

                if new_keys:
                    database.add_known_events(guild_id, team, new_keys)

                    # known_keys being non-empty means this team was already
                    # tracked — so new_keys are genuinely new registrations.
                    # If known_keys is empty this is first-time init → stay silent.
                    if known_keys and channel:
                        for key in new_keys:
                            ev_data = full_event_data.get(key)
                            embed   = await self._new_event_embed(team, key, ev_data)
                            await channel.send(embed=embed)
                            log.info(
                                "Guild %s: announced new event %s for team #%s",
                                guild_id, key, team,
                            )
                    elif not known_keys:
                        # New team — pre-seed all existing played matches so the
                        # next poll doesn't flood the channel with old results.
                        seeded = 0
                        for event_key in current_keys:
                            matches = await _tba.event_matches(self._http, event_key) or []
                            for m in matches:
                                if m.get("winning_alliance") or m.get("actual_time"):
                                    self._seen_results.add((guild_id, m["key"]))
                                    seeded += 1
                        if seeded:
                            log.info(
                                "Guild %s: seeded %d existing match(es) for new team #%s",
                                guild_id, seeded, team,
                            )

    async def _new_event_embed(
        self, team_number: str, event_key: str, event_data: dict | None
    ) -> discord.Embed:
        name     = _display_name(event_data) if event_data else event_key
        nickname = await self._team_nickname(team_number)

        start = event_data.get("start_date", "?") if event_data else "?"
        end   = event_data.get("end_date",   "?") if event_data else "?"
        loc_parts = [
            event_data.get("city"),
            event_data.get("state_prov"),
            event_data.get("country"),
        ] if event_data else []
        location = ", ".join(p for p in loc_parts if p) or "Location TBA"

        embed = discord.Embed(
            title=f"📅 New Event Registered – {nickname} (#{team_number})",
            description=f"**{name}**\n📍 {location}\n🗓️ {start} → {end}",
            color=discord.Color.green(),
            url=f"https://www.thebluealliance.com/event/{event_key}",
        )
        embed.set_footer(text=f"Event key: {event_key} • via The Blue Alliance")
        return embed

    @tasks.loop(seconds=EVENT_CACHE_INTERVAL)
    async def _refresh_events(self):
        try:
            await self._do_refresh_events()
        except Exception:
            log.exception("Error refreshing event cache")

    @_refresh_events.before_loop
    async def _before_refresh(self):
        await self.bot.wait_until_ready()

    # ── Seed already-played matches on startup ────────────────────────────────

    async def _seed_played(self):
        """Mark all already-completed matches as seen so we don't spam old results."""
        all_guild_teams = database.get_all_tracked_teams()
        count = 0
        for guild_id, events in self._active_events.items():
            tracked = set(all_guild_teams.get(guild_id, []))
            for event_key in events:
                matches = await _tba.event_matches(self._http, event_key) or []
                for m in matches:
                    if not m.get("winning_alliance"):
                        continue
                    mt = {t[3:] for t in (
                        m["alliances"]["red"]["team_keys"] +
                        m["alliances"]["blue"]["team_keys"]
                    )}
                    if tracked & mt:
                        self._seen_results.add((guild_id, m["key"]))
                        count += 1
        log.info("Seeded %d already-played match(es)", count)

    # ── Main poll loop ─────────────────────────────────────────────────────────

    @tasks.loop(seconds=POLL_INTERVAL)
    async def _poll(self):
        try:
            await self._poll_upcoming()
            await self._poll_results()
        except Exception:
            log.exception("Error in LiveWatch poll")

    @_poll.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()

    # ── Upcoming matches via Nexus ─────────────────────────────────────────────

    async def _poll_upcoming(self):
        now_ms = int(dt.datetime.now().timestamp() * 1000)
        all_guild_teams = database.get_all_tracked_teams()

        for guild_id, events in self._active_events.items():
            tracked = set(all_guild_teams.get(guild_id, []))
            cfg = database.get_config(guild_id)
            if not cfg or not cfg.get("announce_channel_id"):
                continue
            channel = self.bot.get_channel(cfg["announce_channel_id"])
            if not channel:
                continue

            for tba_key, event_data in events.items():
                nexus_k = _nexus_key(tba_key)
                try:
                    async with self._http.get(
                        f"{NEXUS_BASE}/{nexus_k}",
                        headers={"Nexus-Api-Key": NEXUS_AUTH},
                        ssl=False,
                    ) as r:
                        if r.status != 200:
                            continue
                        nexus_data = await r.json()
                except Exception:
                    continue

                for m in nexus_data.get("matches", []):
                    label      = m.get("label", "")
                    status     = m.get("status", "")
                    red_teams  = m.get("redTeams", [])
                    blue_teams = m.get("blueTeams", [])
                    start_ms   = (m.get("times") or {}).get("estimatedStartTime")

                    if not start_ms or start_ms < now_ms:
                        continue  # already past

                    teams_in_match = tracked & set(red_teams + blue_teams)
                    if not teams_in_match:
                        continue

                    match_key     = _nexus_label_to_match_key(tba_key, label)
                    display       = _display_name(event_data)
                    minutes_until = max(0, (start_ms - now_ms)) // 60_000

                    if status == "On deck" and (guild_id, nexus_k, label, "deck") not in self._seen_upcoming:
                        embed = await self._upcoming_embed(
                            teams_in_match, red_teams, blue_teams,
                            label, display, tba_key, match_key, minutes_until, "🛫 On Deck"
                        )
                        view = _match_view(match_key, _webcast_url(event_data))
                        try:
                            await channel.send(embed=embed, view=view)
                        except discord.Forbidden:
                            log.warning("Missing permissions to send to channel in guild %s — check bot role permissions", guild_id)
                        await self._dm_personal_subscribers(teams_in_match, embed, view)
                        self._seen_upcoming.add((guild_id, nexus_k, label, "deck"))

                    if status == "On field" and (guild_id, nexus_k, label, "field") not in self._seen_upcoming:
                        embed = await self._upcoming_embed(
                            teams_in_match, red_teams, blue_teams,
                            label, display, tba_key, match_key, 0, "🔥 MATCH STARTING NOW"
                        )
                        view = _match_view(match_key, _webcast_url(event_data))
                        try:
                            await channel.send(embed=embed, view=view)
                        except discord.Forbidden:
                            log.warning("Missing permissions to send to channel in guild %s — check bot role permissions", guild_id)
                        await self._dm_personal_subscribers(teams_in_match, embed, view)
                        self._seen_upcoming.add((guild_id, nexus_k, label, "field"))

    # ── Results via TBA ───────────────────────────────────────────────────────

    async def _poll_results(self):
        all_guild_teams = database.get_all_tracked_teams()

        for guild_id, events in self._active_events.items():
            tracked = set(all_guild_teams.get(guild_id, []))
            cfg = database.get_config(guild_id)
            if not cfg or not cfg.get("announce_channel_id"):
                continue
            channel = self.bot.get_channel(cfg["announce_channel_id"])
            if not channel:
                continue

            for tba_key, event_data in events.items():
                matches = await _tba.event_matches(self._http, tba_key) or []
                for m in matches:
                    if not m.get("winning_alliance"):
                        continue
                    key = (guild_id, m["key"])
                    if key in self._seen_results:
                        continue
                    match_teams = {t[3:] for t in (
                        m["alliances"]["red"]["team_keys"] +
                        m["alliances"]["blue"]["team_keys"]
                    )}
                    teams_in_match = tracked & match_teams
                    if not teams_in_match:
                        continue

                    # Snapshot rankings before this batch, then fetch current
                    before = self._rankings_now.get(tba_key, {})
                    current = await self._fetch_rankings(tba_key)
                    self._rankings_before[tba_key] = before
                    self._rankings_now[tba_key]    = current

                    result_embed = self._result_embed(
                        m, teams_in_match, event_data,
                        rankings_before=before,
                        rankings_now=current,
                    )
                    try:
                        await channel.send(embed=result_embed)
                    except discord.Forbidden:
                        log.warning("Missing permissions to send to channel in guild %s — check bot role permissions", guild_id)
                    await self._dm_personal_subscribers(teams_in_match, result_embed)
                    self._seen_results.add(key)

    # ── Embed builders ────────────────────────────────────────────────────────

    async def _team_nickname(self, team_number: str) -> str:
        if team_number in self._nickname_cache:
            return self._nickname_cache[team_number]
        info = await _tba.team_info(self._http, team_number)
        name = info.get("nickname", f"#{team_number}") if info else f"#{team_number}"
        self._nickname_cache[team_number] = name
        return name

    async def _dm_personal_subscribers(
        self,
        teams_in_match: set[str],
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> None:
        """
        Find every user who personally subscribes to any team in this match
        and send them the embed via DM.
        Silently skips users who have DMs disabled.
        """
        notified: set[int] = set()
        for team in teams_in_match:
            for user_id in database.get_users_subscribed_to_team(team):
                if user_id in notified:
                    continue
                notified.add(user_id)
                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(embed=embed, view=view)
                except discord.Forbidden:
                    pass   # user has DMs closed
                except Exception:
                    pass

    async def _upcoming_embed(
        self,
        tracked_in_match: set[str],
        red_teams: list[str],
        blue_teams: list[str],
        label: str,
        display_name: str,
        tba_key: str,
        match_key: str,
        minutes_until: int,
        title_prefix: str,
    ) -> discord.Embed:
        names     = [await self._team_nickname(t) for t in tracked_in_match]
        names_str = ", ".join(f"**{n}** (#{t})" for n, t in zip(names, tracked_in_match))

        on_red  = bool(tracked_in_match & set(red_teams))
        on_blue = bool(tracked_in_match & set(blue_teams))
        side_str = (
            "🔴 Red Alliance"  if on_red and not on_blue else
            "🔵 Blue Alliance" if on_blue and not on_red else
            "🟪 Both Alliances"
        )
        side_key = "red" if (on_red and not on_blue) else "blue"

        win_prob, winner_pred = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _win_probability(match_key, side_key)
        )

        time_str = f"Starts in ~**{minutes_until} min**" if minutes_until > 0 else "**Starting now!**"

        # Build description — omit prediction lines if Statbotics has no data yet
        desc_lines = [
            f"📋 **Match:** {label}",
            f"🏅 {names_str}",
            f"🎨 **Alliance:** {side_str}",
            "",
        ]
        if win_prob is not None and winner_pred:
            desc_lines += [
                f"🏆 **Win Probability:** {win_prob:.1%}",
                f"🔮 **Predicted Winner:** {winner_pred.upper()}",
                "",
            ]
        desc_lines.append(f"🕑 {time_str}")

        footer = (
            f"{display_name} • Powered by Statbotics & TBA • FRC Bot"
            if win_prob is not None
            else f"{display_name} • FRC Bot"
        )

        embed = discord.Embed(
            title=f"{title_prefix} – {display_name}",
            description="\n".join(desc_lines),
            color=discord.Color.gold() if minutes_until > 0 else discord.Color.red(),
        )
        embed.set_footer(text=footer)
        return embed

    async def _fetch_rankings(self, event_key: str) -> dict[str, int]:
        """Return {team_number: rank} for all ranked teams at this event."""
        data = await _tba.event_rankings(self._http, event_key)
        if not data:
            return {}
        result: dict[str, int] = {}
        for row in data.get("rankings", []):
            team = row.get("team_key", "")[3:]   # strip "frc"
            rank = row.get("rank")
            if team and rank:
                result[team] = rank
        return result

    def _result_embed(
        self,
        m: dict,
        tracked_in_match: set[str],
        event_data: dict,
        rankings_before: dict[str, int] | None = None,
        rankings_now:    dict[str, int] | None = None,
    ) -> discord.Embed:
        red_teams  = [t[3:] for t in m["alliances"]["red"]["team_keys"]]
        blue_teams = [t[3:] for t in m["alliances"]["blue"]["team_keys"]]
        red_score  = m["alliances"]["red"]["score"]
        blue_score = m["alliances"]["blue"]["score"]
        winner     = m.get("winning_alliance", "")

        on_red  = bool(tracked_in_match & set(red_teams))
        on_blue = bool(tracked_in_match & set(blue_teams))
        won  = (winner == "red" and on_red) or (winner == "blue" and on_blue)
        tied = winner == ""

        outcome = "🎉 WON!" if won else ("🤝 TIE" if tied else "💔 lost")
        color   = (
            discord.Color.green()   if won  else
            discord.Color.greyple() if tied else
            discord.Color.red()
        )

        teams_str  = ", ".join(f"#{t}" for t in sorted(tracked_in_match, key=int))
        rp         = (m.get("score_breakdown") or {}).get(
            "red" if on_red else "blue", {}
        ).get("rp", 0)
        level      = m.get("comp_level", "?").upper()
        num        = m.get("match_number", "?")
        event_name = _display_name(event_data)

        embed = discord.Embed(
            title=f"🏟️ Match Result – {event_name}",
            description=(
                f"**{teams_str}** {outcome}\n\n"
                f"🔴 **Red Alliance** {'✅' if winner == 'red' else ''}\n"
                + "\n".join(f"• #{t}" for t in red_teams) + "\n\n"
                f"🔵 **Blue Alliance** {'✅' if winner == 'blue' else ''}\n"
                + "\n".join(f"• #{t}" for t in blue_teams) + "\n\n"
                f"**Score:** 🔴 {red_score}  –  {blue_score} 🔵\n"
                + (f"**RP Earned:** {rp}" if rp else "")
            ),
            color=color,
        )

        # ── Ranking movement ──────────────────────────────────────────────────
        if rankings_now:
            ranking_lines = []
            for team in sorted(tracked_in_match, key=int):
                rank_now    = rankings_now.get(team)
                rank_before = (rankings_before or {}).get(team)

                if rank_now is None:
                    continue

                if rank_before is None or rank_before == rank_now:
                    arrow = "➡️"
                    delta = ""
                elif rank_now < rank_before:
                    arrow = "🔼"
                    delta = f" (+{rank_before - rank_now})"
                else:
                    arrow = "🔽"
                    delta = f" (-{rank_now - rank_before})"

                ranking_lines.append(f"#{team}: **#{rank_now}** {arrow}{delta}")

            if ranking_lines:
                embed.add_field(
                    name="🏅 Rankings",
                    value="\n".join(ranking_lines),
                    inline=False,
                )

        embed.add_field(
            name="🔗 Links",
            value=(
                f"[View on TBA](https://www.thebluealliance.com/match/{m['key']})  •  "
                f"[Statbotics](https://www.statbotics.io/match/{m['key']})"
            ),
            inline=False,
        )
        embed.set_footer(text=f"{event_name} • {level} {num} • FRC Bot")
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(LiveWatch(bot))