"""
cogs/my_teams.py – Personal team subscriptions (/myteam add/remove/list/clear).
Notifications arrive via DM when subscribed teams have a match.
"""

from __future__ import annotations

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import database
import tba as _tba

MAX_USER_TEAMS = 20


class MyTeams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    myteam = app_commands.Group(
        name="myteam",
        description="Personal team subscriptions – you'll get a DM when they play"
    )

    @myteam.command(name="add", description="Subscribe to a team's match notifications")
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    async def myteam_add(self, interaction: discord.Interaction, team_number: str):
        await interaction.response.defer(ephemeral=True)

        current = database.get_user_teams(interaction.user.id)
        if len(current) >= MAX_USER_TEAMS:
            await interaction.followup.send(
                f"⚠️ You can subscribe to at most **{MAX_USER_TEAMS}** teams.", ephemeral=True
            )
            return

        info = await _tba.team_info(self._session, team_number)
        if not info:
            await interaction.followup.send(f"⚠️ Team `#{team_number}` not found on TBA.", ephemeral=True)
            return

        added    = database.add_user_team(interaction.user.id, team_number)
        nickname = info.get("nickname", f"#{team_number}")

        if added:
            await interaction.followup.send(
                f"✅ Subscribed to **{nickname}** (#{team_number}).\n"
                "You'll get a **DM** when they're about to play or finish a match.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"ℹ️ Already subscribed to **{nickname}** (#{team_number}).", ephemeral=True
            )

    @myteam.command(name="remove", description="Unsubscribe from a team")
    @app_commands.describe(team_number="FRC team number")
    async def myteam_remove(self, interaction: discord.Interaction, team_number: str):
        removed = database.remove_user_team(interaction.user.id, team_number)
        msg = f"🗑️ Unsubscribed from **#{team_number}**." if removed else f"⚠️ You weren't subscribed to **#{team_number}**."
        await interaction.response.send_message(msg, ephemeral=True)

    @myteam.command(name="list", description="See your personal team subscriptions")
    async def myteam_list(self, interaction: discord.Interaction):
        teams = database.get_user_teams(interaction.user.id)
        if not teams:
            await interaction.response.send_message(
                "No subscriptions yet. Use `/myteam add` to start.", ephemeral=True
            )
            return
        lines = "\n".join(f"• `#{t}`" for t in sorted(teams, key=lambda x: int(x) if x.isdigit() else 0))
        embed = discord.Embed(title="🔔 Your Subscriptions", description=lines, color=discord.Color.blurple())
        embed.set_footer(text=f"{len(teams)}/{MAX_USER_TEAMS} • alerts arrive via DM")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @myteam.command(name="clear", description="Remove all your personal subscriptions")
    async def myteam_clear(self, interaction: discord.Interaction):
        teams = database.get_user_teams(interaction.user.id)
        if not teams:
            await interaction.response.send_message("Nothing to clear.", ephemeral=True)
            return
        for t in teams:
            database.remove_user_team(interaction.user.id, t)
        await interaction.response.send_message(
            f"🗑️ Cleared **{len(teams)}** subscription(s).", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MyTeams(bot))
