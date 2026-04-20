"""
cogs/notifications.py – Listens for webhook dispatch events and sends
Discord embeds to the right channels and users.

Event listeners
---------------
on_tba_match_score(data)          – match completed, post result
on_tba_upcoming_match(data)       – match queuing up, post alert
on_tba_starting_comp_level(data)  – qual/playoff starting
on_tba_schedule_updated(data)     – schedule changed
on_nexus_queue_update(data)       – Nexus queue push (on deck / on field)
"""

from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
import discord
from discord.ext import commands

import database
import event_router
import tba as _tba

log = logging.getLogger("notifications")

SEASON = int(os.environ.get("FRC_SEASON", "2026"))

try:
    import statbotics
    _sb = statbotics.Statbotics()
    _SB_OK = True
except Exception:
    _SB_OK = False


def _win_probability(match_key: str, side: str) -> tuple[float, str] | tuple[None, None]:
    if not _SB_OK:
        return None, None
    try:
        m    = _sb.get_match(match_key)
        if not m:
            return None, None
        pred   = m.get("pred") or {}
        rwp    = pred.get("red_win_prob")
        winner = pred.get("winner")
        if rwp is None or winner is None:
            return None, None
        prob = float(rwp) if side == "red" else 1 - float(rwp)
        return prob, str(winner)
    except Exception as e:
        log.debug("Statbotics error for %s: %s", match_key, e)
        return None, None


def _match_buttons(match_key: str, webcast_url: str | None) -> discord.ui.View:
    view = discord.ui.View()
    if webcast_url:
        view.add_item(discord.ui.Button(label="📺 Watch Live", url=webcast_url))
    view.add_item(discord.ui.Button(
        label="🔵 TBA", url=f"https://www.thebluealliance.com/match/{match_key}"
    ))
    view.add_item(discord.ui.Button(
        label="📊 Statbotics", url=f"https://www.statbotics.io/match/{match_key}"
    ))
    return view


class Notifications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        # nickname cache to avoid hammering TBA
        self._nicknames: dict[str, str] = {}
        # event data cache (event_key → dict with name, webcasts, etc.)
        self._event_cache: dict[str, dict] = {}

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _nickname(self, team_number: str) -> str:
        if team_number in self._nicknames:
            return self._nicknames[team_number]
        info = await _tba.team_info(self._session, team_number)
        name = info.get("nickname", f"#{team_number}") if info else f"#{team_number}"
        self._nicknames[team_number] = name
        return name

    async def _event_data(self, event_key: str) -> dict:
        if event_key not in self._event_cache:
            data = await _tba.event_full(self._session, event_key)
            self._event_cache[event_key] = data or {}
        return self._event_cache[event_key]

    def _webcast_url(self, event_data: dict) -> str | None:
        import datetime as dt
        webcasts = event_data.get("webcasts") or []
        valid    = [w for w in webcasts if w.get("channel")]
        if not valid:
            return None
        day_index = 0
        try:
            start     = dt.date.fromisoformat(event_data["start_date"])
            day_index = max(0, (dt.date.today() - start).days)
        except (KeyError, ValueError):
            pass
        w       = valid[min(day_index, len(valid) - 1)]
        wtype   = w.get("type", "")
        channel = w.get("channel", "")
        if wtype == "youtube":    return f"https://youtube.com/watch?v={channel}"
        if wtype == "twitch":     return f"https://twitch.tv/{channel}"
        if wtype == "livestream": return f"https://livestream.com/{channel}"
        if wtype == "iframe":     return channel
        return None

    async def _send_to_channel(self, guild_id: int, embed: discord.Embed,
                                view: discord.ui.View | None = None) -> None:
        cfg = database.get_config(guild_id)
        if not cfg or not cfg.get("announce_channel_id"):
            return
        channel = self.bot.get_channel(cfg["announce_channel_id"])
        if channel:
            await channel.send(embed=embed, view=view)

    async def _dm_users(self, team_numbers: set[str], embed: discord.Embed,
                        view: discord.ui.View | None = None) -> None:
        notified: set[int] = set()
        for team in team_numbers:
            for user_id in database.get_users_subscribed_to_team(team):
                if user_id in notified:
                    continue
                notified.add(user_id)
                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(embed=embed, view=view)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    # ── TBA: match result ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_tba_match_score(self, data: dict) -> None:
        log.info("on_tba_match_score fired — data keys: %s", list(data.keys()))
        try:
            match = data.get("match") or data
            match_key = match.get("key", "")
            log.info("match_key: %s", match_key)
            if not match_key:
                log.warning("no match_key — returning")
                return

            teams = event_router.extract_teams_from_match(match)
            log.info("teams in match: %s", teams)
            if not teams:
                log.warning("no teams extracted — returning")
                return

            guilds = event_router.get_interested_guilds(teams)
            users  = event_router.get_interested_users(teams)
            log.info("interested guilds: %s | interested users: %s", guilds, users)
            if not guilds and not users:
                log.warning("no interested guilds or users — returning (is 254 tracked?)")
                return

            event_key = match.get("event_key", match_key.rsplit("_", 1)[0])
            ev        = await self._event_data(event_key)
            log.info("event_key: %s | event found: %s", event_key, bool(ev))

            embed = await self._build_result_embed(match, teams, ev)
            log.info("embed built successfully")

            for guild_id, guild_teams in guilds.items():
                seen = database.is_match_seen(guild_id, match_key)
                log.info("guild %s — already seen: %s", guild_id, seen)
                if seen:
                    continue
                await self._send_to_channel(guild_id, embed)
                database.mark_match_seen(guild_id, match_key)
                log.info("guild %s — result sent", guild_id)

            await self._dm_users(teams, embed)
        except Exception as e:
            log.exception("Error in on_tba_match_score: %s", e)

    async def _build_result_embed(
        self, match: dict, tracked: set[str], event_data: dict
    ) -> discord.Embed:
        red_teams  = [t[3:] for t in match["alliances"]["red"]["team_keys"]]
        blue_teams = [t[3:] for t in match["alliances"]["blue"]["team_keys"]]
        red_score  = match["alliances"]["red"]["score"]
        blue_score = match["alliances"]["blue"]["score"]
        winner     = match.get("winning_alliance", "")

        on_red  = bool(tracked & set(red_teams))
        on_blue = bool(tracked & set(blue_teams))
        won  = (winner == "red" and on_red) or (winner == "blue" and on_blue)
        tied = winner == ""

        outcome = "🎉 WON!" if won else ("🤝 TIE" if tied else "💔 lost")
        color   = discord.Color.green() if won else (
            discord.Color.greyple() if tied else discord.Color.red()
        )

        teams_str  = ", ".join(f"**#{t}**" for t in sorted(tracked, key=lambda x: int(x) if x.isdigit() else 0))
        event_name = event_data.get("short_name") or event_data.get("name") or match.get("event_key", "?")
        level      = match.get("comp_level", "?").upper()
        num        = match.get("match_number", "?")
        rp         = match.get("score_breakdown", {}).get(
            "red" if on_red else "blue", {}
        ).get("rp", 0)

        embed = discord.Embed(
            title=f"🏟️ Match Result – {event_name}",
            description=(
                f"**{teams_str}** {outcome}\n\n"
                f"🔴 **Red Alliance** {'✅' if winner == 'red' else ''}\n"
                + "\n".join(f"• #{t}" for t in red_teams) + "\n\n"
                f"🔵 **Blue Alliance** {'✅' if winner == 'blue' else ''}\n"
                + "\n".join(f"• #{t}" for t in blue_teams) + "\n\n"
                f"**Score:** 🔴 {red_score}  –  {blue_score} 🔵"
                + (f"\n**RP Earned:** {rp}" if rp else "")
            ),
            color=color,
        )
        embed.add_field(
            name="🔗 Links",
            value=(
                f"[TBA](https://www.thebluealliance.com/match/{match['key']})  •  "
                f"[Statbotics](https://www.statbotics.io/match/{match['key']})"
            ),
            inline=False,
        )
        embed.set_footer(text=f"{event_name} • {level}{num} • FRC Webhook Bot")
        return embed

    # ── TBA: upcoming match ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_tba_upcoming_match(self, data: dict) -> None:
        match_key  = data.get("match_key", "")
        event_key  = data.get("event_key", "")
        team_keys  = data.get("team_keys", [])
        if not match_key:
            return

        teams = {k.lstrip("frc") for k in team_keys}
        if not teams:
            # TBA sometimes omits team_keys — extract from event roster isn't worth it here
            return

        guilds = event_router.get_interested_guilds(teams)
        users  = event_router.get_interested_users(teams)
        if not guilds and not users:
            return

        ev        = await self._event_data(event_key)
        event_name = ev.get("short_name") or ev.get("name") or event_key
        webcast   = self._webcast_url(ev)

        # Statbotics prediction
        # Determine side from event teams — TBA upcoming_match doesn't include full alliances
        # so we do a best-effort single call
        win_prob, winner_pred = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _win_probability(match_key, "red")
        )

        minutes = data.get("scheduled_time", 0)

        desc_lines = [
            f"📋 **Match:** {data.get('match_key', '?').split('_')[-1].upper()}",
            f"🏅 Teams: {', '.join(f'**#{t}**' for t in sorted(teams, key=lambda x: int(x) if x.isdigit() else 0))}",
            "",
        ]
        if win_prob is not None:
            desc_lines += [
                f"🏆 **Win Probability (Red):** {win_prob:.1%}",
                f"🔮 **Predicted Winner:** {winner_pred.upper() if winner_pred else '?'}",
                "",
            ]
        if minutes:
            desc_lines.append(f"🕑 Scheduled: <t:{minutes}:F>  (<t:{minutes}:R>)")

        embed = discord.Embed(
            title=f"⏰ Upcoming Match – {event_name}",
            description="\n".join(desc_lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"{event_name} • FRC Webhook Bot")
        view = _match_buttons(match_key, webcast)

        for guild_id in guilds:
            await self._send_to_channel(guild_id, embed, view)
        await self._dm_users(teams, embed, view)

    # ── TBA: competition level starting ──────────────────────────────────────

    @commands.Cog.listener()
    async def on_tba_starting_comp_level(self, data: dict) -> None:
        event_key  = data.get("event_key", "")
        comp_level = data.get("comp_level", "?").upper()

        if not event_key:
            return

        # Notify any guild that has teams at this event
        all_teams = database.get_all_tracked_team_numbers()
        ev = await self._event_data(event_key)
        ev_teams_raw = await _tba.event_teams(self._session, event_key) or []
        ev_team_nums = {t["key"].lstrip("frc") for t in ev_teams_raw}
        interested   = all_teams & ev_team_nums

        guilds = event_router.get_interested_guilds(interested)
        if not guilds:
            return

        event_name = ev.get("short_name") or ev.get("name") or event_key
        level_name = {"qm": "Qualifications", "sf": "Semifinals", "f": "Finals"}.get(
            data.get("comp_level", "").lower(), comp_level
        )

        embed = discord.Embed(
            title=f"🚨 {level_name} Starting – {event_name}",
            description=f"**{level_name}** are now underway at **{event_name}**!",
            color=discord.Color.orange(),
            url=f"https://www.thebluealliance.com/event/{event_key}",
        )
        embed.set_footer(text="FRC Webhook Bot")

        for guild_id in guilds:
            await self._send_to_channel(guild_id, embed)

    # ── Nexus: queue update ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_nexus_queue_update(self, data: dict) -> None:
        """
        Nexus sends queue status updates: On deck, On field, etc.
        Expected payload shape:
          {
            "eventKey": "2026isde1",
            "matchLabel": "Qualification 12",
            "status": "On deck",
            "redTeams": ["1234", "5678", "9012"],
            "blueTeams": ["2345", "6789", "0123"],
            "times": {"estimatedStartTime": 1714000000000}
          }
        """
        status      = data.get("status", "")
        red_teams   = data.get("redTeams", [])
        blue_teams  = data.get("blueTeams", [])
        label       = data.get("matchLabel", "?")
        event_key   = data.get("eventKey", "")
        times       = data.get("times") or {}
        start_ms    = times.get("estimatedStartTime", 0)

        if status not in ("On deck", "On field"):
            return

        all_match_teams = set(red_teams + blue_teams)
        guilds = event_router.get_interested_guilds(all_match_teams)
        users  = event_router.get_interested_users(all_match_teams)
        if not guilds and not users:
            return

        # Build a TBA-style match key for Statbotics + buttons
        tba_key = _nexus_label_to_tba_key(event_key, label)
        ev      = await self._event_data(event_key)
        event_name = ev.get("short_name") or ev.get("name") or event_key
        webcast = self._webcast_url(ev)

        minutes_until = max(0, (start_ms - __import__("time").time() * 1000)) // 60_000 if start_ms else 0
        time_str      = f"~**{int(minutes_until)} min**" if minutes_until > 0 else "**now!**"
        title_prefix  = "🛫 On Deck" if status == "On deck" else "🔥 Starting Now"

        for guild_id, guild_teams in guilds.items():
            on_red  = bool(guild_teams & set(red_teams))
            on_blue = bool(guild_teams & set(blue_teams))
            side    = (
                "🔴 Red Alliance"  if on_red and not on_blue else
                "🔵 Blue Alliance" if on_blue and not on_red else
                "🟪 Both Alliances"
            )
            side_key = "red" if on_red and not on_blue else "blue"

            names = [await self._nickname(t) for t in guild_teams]
            names_str = ", ".join(f"**{n}** (#{t})" for n, t in zip(names, guild_teams))

            win_prob, winner_pred = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _win_probability(tba_key, side_key)
            )

            desc_lines = [
                f"📋 **Match:** {label}",
                f"🏅 {names_str}",
                f"🎨 **Alliance:** {side}",
                "",
            ]
            if win_prob is not None:
                desc_lines += [
                    f"🏆 **Win Probability:** {win_prob:.1%}",
                    f"🔮 **Predicted Winner:** {winner_pred.upper()}",
                    "",
                ]
            desc_lines.append(f"🕑 Starts in {time_str}")

            embed = discord.Embed(
                title=f"{title_prefix} – {event_name}",
                description="\n".join(desc_lines),
                color=discord.Color.gold() if status == "On deck" else discord.Color.red(),
            )
            embed.set_footer(text=f"{event_name} • FRC Webhook Bot")
            view = _match_buttons(tba_key, webcast)
            await self._send_to_channel(guild_id, embed, view)

        # DM personal subscribers
        for user_id, user_teams in event_router.get_interested_users(all_match_teams).items():
            on_red  = bool(user_teams & set(red_teams))
            on_blue = bool(user_teams & set(blue_teams))
            side    = (
                "🔴 Red Alliance"  if on_red and not on_blue else
                "🔵 Blue Alliance" if on_blue and not on_red else
                "🟪 Both Alliances"
            )
            names     = [await self._nickname(t) for t in user_teams]
            names_str = ", ".join(f"**{n}** (#{t})" for n, t in zip(names, user_teams))

            embed = discord.Embed(
                title=f"{title_prefix} – {event_name}",
                description=(
                    f"📋 **Match:** {label}\n"
                    f"🏅 {names_str}\n"
                    f"🎨 **Alliance:** {side}\n\n"
                    f"🕑 Starts in {time_str}"
                ),
                color=discord.Color.gold() if status == "On deck" else discord.Color.red(),
            )
            embed.set_footer(text=f"{event_name} • FRC Webhook Bot")
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=embed, view=_match_buttons(tba_key, webcast))
            except (discord.Forbidden, discord.HTTPException):
                pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _nexus_label_to_tba_key(event_key: str, label: str) -> str:
    s = label.lower().replace(" ", "")
    if s.startswith("qualification"):
        return f"{event_key}_qm{s.removeprefix('qualification')}"
    if s.startswith("final"):
        return f"{event_key}_f1m{s.removeprefix('final') or '1'}"
    if s.startswith("semifinal"):
        return f"{event_key}_sf{s.removeprefix('semifinal') or '1'}m1"
    if s.startswith("playoff"):
        return f"{event_key}_sf{s.removeprefix('playoff') or '1'}m1"
    return f"{event_key}_{s}"


async def setup(bot: commands.Bot):
    await bot.add_cog(Notifications(bot))