"""
cogs/help.py – /help command, context-aware for DM vs server.

In a server: shows all commands (ephemeral).
In a DM: shows only commands that actually work in DMs, with a note
         that server-only commands are hidden.
"""

from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands


# ── Command lists ─────────────────────────────────────────────────────────────

# Available everywhere (server + DM)
_LOOKUP = ("🔍 Lookup", [
    ("/team <number>",              "Full team info, blue banners, links"),
    ("/events <number> [year]",     "Team's event list for a season"),
    ("/event <event_key>",          "Info about an event"),
    ("/matches <number> <event>",   "Team's match results at an event"),
    ("/robots <number>",            "Robot names by year"),
    ("/ranking <number> <event>",   "Team's ranking at an event"),
    ("/epa <number> [year]",        "Statbotics EPA breakdown"),
    ("/nextmatch",                  "Next upcoming match for teams you follow"),
])

_PERSONAL = ("🔔 Personal alerts", [
    ("/myteam add <number>",        "Subscribe – get a DM when this team plays"),
    ("/myteam remove <number>",     "Unsubscribe from a team"),
    ("/myteam list",                "See your personal subscriptions"),
    ("/myteam clear",               "Remove all your subscriptions"),
])

# Server-only
_SERVER_LISTS = ("🔍 Server lists", [
    ("/listteams",                  "All teams tracked for this server"),
    ("/epalist",                    "All EPA-tracked teams for this server"),
])

_ADMIN = ("🔑 Admin only", [
    ("/setup channel <#channel>",   "Set the announcement channel"),
    ("/setup adminrole <@role>",    "Grant a role bot-admin access"),
    ("/addteam <number>",           "Track a single team for live match alerts"),
    ("/addepa <count>",             "Add the top N teams by EPA to the watch list"),
    ("/removeteam <number>",        "Stop tracking a team"),
    ("/trackepa <number>",          "Track EPA changes for a team"),
    ("/untrackepa <number>",        "Stop EPA tracking a team"),
    ("/serverinfo",                 "View bot config for this server"),
    ("/adminroles",                 "Show which roles have admin bot access"),
])

SERVER_SECTIONS = [_LOOKUP, _SERVER_LISTS, _PERSONAL, _ADMIN]
DM_SECTIONS     = [_LOOKUP, _PERSONAL]


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available bot commands")
    async def help(self, interaction: discord.Interaction):
        in_dm = interaction.guild is None

        if in_dm:
            embed = discord.Embed(
                title="📖 FRC Bot – DM Commands",
                description=(
                    "Here's what works here in DMs.\n"
                    "Server-only commands (admin setup, `/listteams`, `/epalist`) "
                    "are hidden — use them inside a server instead."
                ),
                color=discord.Color.from_rgb(40, 89, 165),
            )
            sections  = DM_SECTIONS
            footer    = "Server-only commands hidden • Data: TBA & Statbotics"
            ephemeral = False  # DMs are inherently private, no need for ephemeral
        else:
            embed = discord.Embed(
                title="📖 FRC Bot – Command Reference",
                description=(
                    "**Lookup commands** are private (ephemeral) – only you see them.\n"
                    "**Personal alerts** (`/myteam`) arrive via **DM** – invisible to others.\n"
                    "**Live announcements** post to the configured server channel."
                ),
                color=discord.Color.from_rgb(40, 89, 165),
            )
            sections  = SERVER_SECTIONS
            footer    = "Data: The Blue Alliance & Statbotics • FRC Bot"
            ephemeral = True

        for section_name, cmds in sections:
            value = "\n".join(f"`{cmd}` – {desc}" for cmd, desc in cmds)
            embed.add_field(name=section_name, value=value, inline=False)

        embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
