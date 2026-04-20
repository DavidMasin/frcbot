"""cogs/online.py – on_ready status."""
import discord
from discord.ext import commands


class Online(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="FRC webhooks • /help"
            )
        )
        print(f"✅ {self.bot.user} online")


async def setup(bot: commands.Bot):
    await bot.add_cog(Online(bot))
