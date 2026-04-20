"""cogs/help.py – dynamic /help, reads from the live command tree."""

from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

_SERVER_ONLY = {
    "setup", "addteam", "addepa", "removeteam",
    "listteams", "serverinfo", "adminroles",
}


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available bot commands")
    async def help(self, interaction: discord.Interaction):
        in_dm = interaction.guild is None
        rows: list[tuple[str, str]] = []

        for cmd in sorted(self.bot.tree.get_commands(), key=lambda c: c.name):
            if in_dm and cmd.name in _SERVER_ONLY:
                continue
            if isinstance(cmd, app_commands.Group):
                for sub in sorted(cmd.commands, key=lambda c: c.name):
                    rows.append((f"/{cmd.name} {sub.name}", sub.description or "—"))
            else:
                rows.append((f"/{cmd.name}", cmd.description or "—"))

        lines = "\n".join(f"`{name}` – {desc}" for name, desc in rows)

        if in_dm:
            embed = discord.Embed(
                title="📖 FRC Webhook Bot – DM Commands",
                description="Server-only commands are hidden.\n\n" + lines,
                color=discord.Color.from_rgb(40, 89, 165),
            )
            embed.set_footer(text="Powered by TBA & Nexus webhooks")
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="📖 FRC Webhook Bot – Commands",
                description=(
                    "Responses are **private** (ephemeral).\n"
                    "Match alerts post to the configured channel.\n"
                    "Personal alerts (`/myteam`) arrive via **DM**.\n\n" + lines
                ),
                color=discord.Color.from_rgb(40, 89, 165),
            )
            embed.set_footer(text="Powered by TBA & Nexus webhooks")
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
