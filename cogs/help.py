# cogs/help.py
"""
Custom help command for your bot.
"""
from __future__ import annotations
import discord
from discord.ext import commands

class CustomHelp(commands.Cog):
    """`!help [command]` – show bot command usage."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Disable the default help command so this one can use the !help name
        if bot.help_command:
            bot.help_command = None

    # The command name is still 'help'
    @commands.command(name="help")
    async def _help(self, ctx: commands.Context, command: str | None = None):
        def base_embed(title: str) -> discord.Embed:
            return discord.Embed(
                title=title,
                color=discord.Color.from_rgb(40, 89, 165),
            )

        if command is None:
            embed = base_embed("2056 Bot – Help")
            embed.add_field(
                name="team",   value="`!team <team number>` – Info about an FRC team",     inline=False)
            embed.add_field(
                name="events", value="`!events <team number> [year]` – Team’s events",     inline=False)
            embed.add_field(
                name="event",  value="`!event <event key>` – Info about an FRC event",     inline=False)
            embed.add_field(
                name="matches",value="`!matches <team> <event>` – Team’s matches at event",inline=False)
            embed.add_field(
                name="robots", value="`!robots <team number>` – Team robot names",         inline=False)
            embed.add_field(
                name="help",   value="`!help [command]` – This message",                   inline=False)
            await ctx.send(embed=embed)
            return

        command = command.lower()
        syntax: dict[str, str] = {
            "team":    "`!team <team number>`",
            "events":  "`!events <team number> [year]`",
            "event":   "`!event <event key>`",
            "matches": "`!matches <team number> <event key>`",
            "robots":  "`!robots <team number>`",
            "help":    "`!help [command]`",
        }

        if command in syntax:
            embed = base_embed(f"2056 Bot Help – {command}")
            embed.add_field(name=command, value=syntax[command], inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❓ `{command}` is not a recognised command.")

# --------------------------------------------------------------------------- #
# Required entry point for discord.py
# --------------------------------------------------------------------------- #
async def setup(bot: commands.Bot) -> None:
    """Add the cog to the bot (discord.py expects this coroutine)."""
    await bot.add_cog(CustomHelp(bot))
