import discord
from discord.ext import commands


class Online(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_ready(self):
        print("online")


async def setup(client):
    await client.add_cog(Online(client))
