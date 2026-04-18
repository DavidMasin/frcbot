
import asyncio
import os
import discord
from discord.ext import commands
TOKEN = "MTM2MjM5Mjk3ODc0Mzg5MDAzMA.GIat6G.9YRxg3XuNh0fgp7SThicSgf4XeZISOJ-uiA38w"
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def main() -> None:
    for fname in os.listdir("./cogs"):
        if fname.endswith(".py"):
            await bot.load_extension(f"cogs.{fname[:-3]}")
    await bot.start(TOKEN)   # ← never hard‑code tokens!

if __name__ == "__main__":
    asyncio.run(main())
# import os, requests, json, pprint
# TBA_KEY = json.load(open("keys.json"))["tbaKey"]
# url = "https://www.thebluealliance.com/api/v3/team/frc5987"
# print(requests.get(url, headers={"X-TBA-Auth-Key": TBA_KEY}).status_code)
# pprint.pp(requests.get(url, headers={"X-TBA-Auth-Key": TBA_KEY}).json())