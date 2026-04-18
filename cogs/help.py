"""
cogs/help.py – /help command.

Builds the command list dynamically from the bot's live app_commands tree
so it only ever shows commands that are actually registered and working.
"""

from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

# Commands that should only appear in server context
_SERVER_ONLY = {
    "setup", "addteam", "addepa", "removeteam",
    "listteams", "serverinfo", "adminroles",
    "trackepa", "untrackepa",
}


def _format_tree(
    bot: commands.Bot,
    in_dm: bool,
) -> list[tuple[str, str]]:
    """Return [(name, description)] for every registered command, filtered by context."""
    rows: list[tuple[str, str]] = []

    for cmd in sorted(bot.tree.get_commands(), key=lambda c: c.name):
        if in_dm and cmd.name in _SERVER_ONLY:
            continue

        if isinstance(cmd, app_commands.Group):
            for sub in sorted(cmd.commands, key=lambda c: c.name):
                rows.append((f"/{cmd.name} {sub.name}", sub.description or "—"))
        else:
            rows.append((f"/{cmd.name}", cmd.description or "—"))

    return rows


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available bot commands")
    async def help(self, interaction: discord.Interaction):
        in_dm = interaction.guild is None
        rows  = _format_tree(self.bot, in_dm)

        if not rows:
            await interaction.response.send_message(
                "No commands are registered yet. The bot may still be syncing — try again in a moment.",
                ephemeral=True,
            )
            return

        lines = "\n".join(f"`{name}` – {desc}" for name, desc in rows)

        if in_dm:
            embed = discord.Embed(
                title="📖 FRC Bot – Available Commands",
                description=(
                    "Server-only commands (admin setup, team lists) are hidden here.\n\n"
                    + lines
                ),
                color=discord.Color.from_rgb(40, 89, 165),
            )
            embed.set_footer(text="Data: TBA & Statbotics")
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="📖 FRC Bot – Available Commands",
                description=(
                    "Info commands are **private** – only you see the response.\n"
                    "Personal alerts (`/myteam`) arrive via **DM**.\n"
                    "Live match alerts post to the configured server channel.\n\n"
                    + lines
                ),
                color=discord.Color.from_rgb(40, 89, 165),
            )
            embed.set_footer(text="Data: The Blue Alliance & Statbotics • FRC Bot")
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
