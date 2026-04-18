"""
cogs/online.py – fires on_ready and logs the bot as online.
"""
import discord
from discord.ext import commands


class Online(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.Cog.listener()
    async def on_ready(self):
        await self.client.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="FRC matches • /help | Send a DM for private notifications"
            )
        )
        print(f"✅ {self.client.user} is online!")


async def setup(client: commands.Bot):
    await client.add_cog(Online(client))
