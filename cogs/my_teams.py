"""
cogs/my_teams.py – Personal team subscriptions for individual users.

Any user can subscribe to teams they care about.  When those teams have a
match (on deck, starting, or result), the bot DMs the user directly — so
only they see it, completely invisible to other server members.

Commands
--------
/myteam add <number>     – subscribe to a team
/myteam remove <number>  – unsubscribe from a team
/myteam list             – see your subscriptions (ephemeral)
/myteam clear            – remove all your subscriptions
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

import database
import tba as _tba

MAX_USER_TEAMS = 20   # prevent abuse


class MyTeams(commands.Cog):
    """Personal team subscriptions – DM notifications, invisible to others."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    # ── /myteam group ─────────────────────────────────────────────────────────
    myteam = app_commands.Group(
        name="myteam",
        description="Manage your personal team subscriptions (you'll be DM'd for their matches)"
    )

    @myteam.command(name="add", description="Subscribe to a team – you'll get a DM when they play")
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    async def myteam_add(self, interaction: discord.Interaction, team_number: str):
        await interaction.response.defer(ephemeral=True)

        # Cap per-user subscriptions
        current = database.get_user_teams(interaction.user.id)
        if len(current) >= MAX_USER_TEAMS:
            await interaction.followup.send(
                f"⚠️ You can subscribe to at most **{MAX_USER_TEAMS}** teams. "
                f"Use `/myteam remove` to free up a slot.", ephemeral=True
            )
            return

        # Validate team exists on TBA
        info = await _tba.team_info(self._session, team_number)
        if info is None:
            await interaction.followup.send(
                f"⚠️ Team `#{team_number}` wasn't found on The Blue Alliance.", ephemeral=True
            )
            return

        added    = database.add_user_team(interaction.user.id, team_number)
        nickname = info.get("nickname", f"#{team_number}")

        if added:
            await interaction.followup.send(
                f"✅ Subscribed to **{nickname}** (#{team_number}).\n"
                f"You'll receive a **DM** whenever they're about to play or finish a match.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"ℹ️ You're already subscribed to **{nickname}** (#{team_number}).", ephemeral=True
            )

    @myteam.command(name="remove", description="Unsubscribe from a team")
    @app_commands.describe(team_number="FRC team number, e.g. 5987")
    async def myteam_remove(self, interaction: discord.Interaction, team_number: str):
        removed = database.remove_user_team(interaction.user.id, team_number)
        if removed:
            await interaction.response.send_message(
                f"🗑️ Unsubscribed from team **#{team_number}**.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ You weren't subscribed to team **#{team_number}**.", ephemeral=True
            )

    @myteam.command(name="list", description="See all the teams you're personally subscribed to")
    async def myteam_list(self, interaction: discord.Interaction):
        teams = database.get_user_teams(interaction.user.id)
        if not teams:
            await interaction.response.send_message(
                "You have no personal team subscriptions yet.\n"
                "Use `/myteam add <number>` to start receiving DM match alerts.",
                ephemeral=True,
            )
            return

        lines = "\n".join(f"• `#{t}`" for t in sorted(teams, key=lambda x: int(x)))
        embed = discord.Embed(
            title="🔔 Your Team Subscriptions",
            description=lines,
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text=f"{len(teams)}/{MAX_USER_TEAMS} subscriptions • "
                 "Match alerts are sent to you via DM"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @myteam.command(name="clear", description="Remove all your personal team subscriptions")
    async def myteam_clear(self, interaction: discord.Interaction):
        teams = database.get_user_teams(interaction.user.id)
        if not teams:
            await interaction.response.send_message(
                "You have no subscriptions to clear.", ephemeral=True
            )
            return

        for t in teams:
            database.remove_user_team(interaction.user.id, t)

        await interaction.response.send_message(
            f"🗑️ Cleared all **{len(teams)}** personal subscription(s).", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MyTeams(bot))
