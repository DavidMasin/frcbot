import discord
from discord.ext import commands
import json
import requests


class Robots(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command()
    async def robots(self, ctx, teamKey):
        tbaKey = 'Z2VNC3RzqmYPmdIn9otts616q62uVfsJ74xr6WtEhmdq1asi7BVR4zYPCKl7geog'
        url = f'https://www.thebluealliance.com/api/v3/team/{teamKey}/robots?X-TBA-Auth-Key={tbaKey}'
        data = requests.get(url).json()

        embed = discord.Embed(title=teamKey, color=discord.Color.from_rgb(40, 89, 165))

        for i in data:
            embed.add_field(name = i['year'], value=i['robot_name'], inline=False)
        await ctx.send(embed=embed)
async def setup(client):
    await client.add_cog(Robots(client))
