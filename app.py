"""
app.py – FRC Discord Bot entry point.

Setup
-----
Set these environment variables before running:
    DISCORD_BOT_TOKEN   – your bot's token
    TBA_KEY             – The Blue Alliance API key
    NEXUS_AUTH          – frc.nexus API key

Or fall back to keys.json for TBA_KEY.
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

import database

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

# ── bot setup ─────────────────────────────────────────────────────────────────
TOKEN = "MTM2MjM5Mjk3ODc0Mzg5MDAzMA.GIat6G.9YRxg3XuNh0fgp7SThicSgf4XeZISOJ-uiA38w"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d slash command(s)", len(synced))
    except Exception as e:
        log.error("Failed to sync commands: %s", e)


async def main() -> None:
    database.init_db()
    log.info("Database initialised ✅")

    async with bot:
        for fname in os.listdir("./cogs"):
            if fname.endswith(".py"):
                ext = f"cogs.{fname[:-3]}"
                await bot.load_extension(ext)
                log.info("Loaded extension: %s", ext)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
