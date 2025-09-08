# cogs/events.py
"""
Events command for a Discord bot that queries The Blue Alliance
and shows a team’s event keys and names in an embed.

Requirements
------------
* discord.py == 2.x
* requests
* A `keys.json` file **one directory above** this file:
  {
      "tbaKey": "YOUR‑TBA‑AUTH‑KEY"
  }
"""

from __future__ import annotations

import json
import os
from typing import Any

import discord
import requests
from discord.ext import commands

# --------------------------------------------------------------------------- #
#  Load your secret TBA key once, when the module is imported
# --------------------------------------------------------------------------- #

ROOT = os.path.dirname(os.path.dirname(__file__))          # project root
with open(os.path.join(ROOT, "keys.json"), encoding="utf‑8") as f:
    _keys: dict[str, Any] = json.load(f)

TBA_KEY: str = _keys["tbaKey"]                             # change if key name differs
HEADERS = {"X-TBA-Auth-Key": TBA_KEY}

# --------------------------------------------------------------------------- #
#  Cog definition
# --------------------------------------------------------------------------- #

class Events(commands.Cog):
    """`!events <team> [year|all]` – show a team’s events."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # --------------------------------------------------------------------- #
    #  Command
    # --------------------------------------------------------------------- #

    @commands.command()
    async def events(self, ctx: commands.Context, team: str, year: str | None = None):
        """
        Fetch a team’s event list.

        Parameters
        ----------
        team : str
            Team number with the leading 'frc' omitted (e.g. '5987').
        year : str | None
            Specific season (e.g. '2025') or 'all'.  If omitted, defaults to 'all'.
        """
        # --- Build URLs --------------------------------------------------- #
        if year is None or year.lower() == "all":
            keys_url   = f"https://www.thebluealliance.com/api/v3/team/frc{team}/events/keys"
            simple_url = f"https://www.thebluealliance.com/api/v3/team/frc{team}/events/simple"
        else:
            keys_url   = f"https://www.thebluealliance.com/api/v3/team/frc{team}/events/{year}/keys"
            simple_url = f"https://www.thebluealliance.com/api/v3/team/frc{team}/events/{year}/simple"

        team_url = f"https://www.thebluealliance.com/api/v3/team/frc{team}"

        # --- Query TBA ---------------------------------------------------- #
        try:
            keys_resp   = requests.get(keys_url,   headers=HEADERS, timeout=10)
            simple_resp = requests.get(simple_url, headers=HEADERS, timeout=10)
            team_resp   = requests.get(team_url,   headers=HEADERS, timeout=10)
        except requests.RequestException:
            await ctx.send("❌  Failed to reach The Blue Alliance. Please try again later.")
            return

        if not (keys_resp.ok and simple_resp.ok and team_resp.ok):
            await ctx.send("⚠️  TBA returned an error – check the team number or year.")
            return

        event_keys   = keys_resp.json()      # list[str]
        event_simple = simple_resp.json()    # list[dict]
        team_info    = team_resp.json()      # dict

        # --- Prepare fields ---------------------------------------------- #
        keys_field = "\n".join(event_keys) or "No events found."

        names_field = "\n".join(
            e["name"].replace("(Cancelled)", "")               # strip “(Cancelled)”
            for e in event_simple
            if e.get("name")
        ) or "No event names to display."

        # --- Build embed -------------------------------------------------- #
        embed = discord.Embed(
            title=f"FRC Team {team_info.get('team_number', team)} Events",
            url=team_info.get("website") or discord.Embed.Empty,
            color=discord.Color.blue(),
        )
        embed.set_footer(text=team_info.get("nickname", ""))

        embed.add_field(name="Event Keys",  value=keys_field,  inline=True)
        embed.add_field(name="Event Names", value=names_field, inline=True)

        await ctx.send(embed=embed)

# --------------------------------------------------------------------------- #
#  Entry‑point for bot.load_extension()
# --------------------------------------------------------------------------- #

async def setup(bot: commands.Bot) -> None:
    """Add the cog to the bot – required by discord.py."""
    await bot.add_cog(Events(bot))
