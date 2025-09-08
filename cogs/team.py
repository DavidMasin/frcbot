# cogs/team.py
from __future__ import annotations
import os, json, collections
import requests, discord
from discord.ext import commands

ROOT = os.path.dirname(os.path.dirname(__file__))
with open(os.path.join(ROOT, "keys.json"), encoding="utf-8") as f:
    TBA_KEY = json.load(f)["tbaKey"]

HEADERS = {"X-TBA-Auth-Key": TBA_KEY}

AWARD_TYPES = {
    0:  "chairmans",
    69: "chairmans_finalists",
    1:  "winner",
    3:  "woodie_flowers",
    74: "skills_competition_winner",
}

class Team(commands.Cog):
    """`!team <team_num>` – show high‑level info & blue‑banners."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command()
    async def team(self, ctx: commands.Context, team_num: str):
        base = f"https://www.thebluealliance.com/api/v3/team/frc{team_num}"
        try:
            team_r  = requests.get(base,headers=HEADERS, timeout=2); team_r.raise_for_status()
            award_r = requests.get(base + "/awards",   headers=HEADERS, timeout=2); award_r.raise_for_status()
        except requests.RequestException as e:
            await ctx.send(f"❌  TBA error: {e}")
            return
        team = team_r.json()
        awards = award_r.json()

        counts = collections.Counter(
            AWARD_TYPES[a["award_type"]] for a in awards if a["award_type"] in AWARD_TYPES
        )
        blue_banners = sum(counts.values())

        website = team.get("website") or f"https://www.thebluealliance.com/team/{team_num}"

        embed = discord.Embed(
            title=f"FRC {team['team_number']}",
            url=website,
            color=discord.Color.from_rgb(40, 89, 165),
        )
        embed.add_field(
            name="Location",
            value=(
                f"**City:** {team.get('city') or '—'}\n"
                f"**State/Prov.:** {team.get('state_prov') or '—'}\n"
                f"**Country:** {team.get('country') or '—'}\n"
                f"**Postal Code:** {team.get('postal_code') or '—'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Team Info",
            value=(
                f"**Nickname:** {team.get('nickname') or '—'}\n"
                f"**School:** {team.get('school_name') or '—'}\n"
                f"**Rookie Year:** {team.get('rookie_year') or '—'}\n"
                f"**Key:** {team['key']}"
            ),
            inline=True,
        )
        banner_text = "\n".join(f"**{label.replace('_',' ').title()}:** {counts[label]}"
                                for label in AWARD_TYPES.values())
        embed.add_field(
            name="Blue Banners",
            value=f"{banner_text}\n**Total Blue Banners:** {blue_banners}",
            inline=False,
        )
        embed.add_field(
            name="External",
            value=(
                f"[TBA]({website})  |  "
                f"[FIRST](https://frc-events.firstinspires.org/team/{team_num})  |  "
                f"[Statbotics](https://www.statbotics.io/team/{team_num})"
            ),
            inline=False,
        )

        await ctx.send(embed=embed)

# required by discord.py
async def setup(bot: commands.Bot):
    await bot.add_cog(Team(bot))
