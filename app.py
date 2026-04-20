"""
app.py – FRC Webhook Bot entry point.

Runs two async services in the same event loop:
  1. An aiohttp HTTP server that receives TBA and Nexus webhook POSTs
  2. A discord.py bot that sends the resulting notifications

Environment variables
---------------------
DISCORD_BOT_TOKEN   – required
TBA_KEY             – required (Blue Alliance API key)
TBA_HMAC_SECRET     – required (set when registering webhook at thebluealliance.com/account)
NEXUS_AUTH          – required (frc.nexus API key)
DATABASE_URL / PG*  – required (Railway injects automatically)
PORT                – optional, defaults to 8000 (Railway injects automatically)
FRC_SEASON          – optional, defaults to 2026
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web

import database
from webhook_server import build_webhook_app

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

# ── bot setup ─────────────────────────────────────────────────────────────────
TOKEN = os.environ["DISCORD_BOT_TOKEN"]

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)


# ── global slash-command error handler ────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    cause = getattr(error, "original", error)
    if isinstance(cause, app_commands.CheckFailure):
        msg = str(cause) or "❌ You don't have permission to use this command."
    elif isinstance(cause, app_commands.CommandOnCooldown):
        msg = f"⏳ Slow down! Try again in {cause.retry_after:.1f}s."
    else:
        log.error(
            "Unhandled error in /%s:\n%s",
            interaction.command.name if interaction.command else "unknown",
            "".join(traceback.format_exception(type(cause), cause, cause.__traceback__)),
        )
        msg = f"❌ Something went wrong: `{cause}`"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


# ── on_ready: sync commands ────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)

    # Clear old guild-specific duplicates if any
    for guild in bot.guilds:
        try:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
        except Exception:
            pass

    try:
        synced = await bot.tree.sync()
        log.info("Synced %d global command(s)", len(synced))
    except Exception as e:
        log.error("Global sync failed: %s", e)


# ── /sync owner command ───────────────────────────────────────────────────────
@bot.tree.command(name="sync", description="Force re-sync slash commands (bot owner only)")
async def slash_sync(interaction: discord.Interaction):
    if interaction.user.id != (await bot.application_info()).owner.id:
        await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    await interaction.followup.send(f"✅ Synced {len(synced)} command(s).", ephemeral=True)


# ── main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    database.init_db()
    log.info("Database initialised ✅")

    # Build the webhook HTTP app — pass the bot so handlers can send Discord messages
    webhook_app = build_webhook_app(bot)

    # Load all cogs
    async with bot:
        for fname in sorted(os.listdir("./cogs")):
            if fname.endswith(".py"):
                ext = f"cogs.{fname[:-3]}"
                try:
                    await bot.load_extension(ext)
                    log.info("Loaded: %s", ext)
                except Exception as e:
                    log.error("Failed to load %s: %s", ext, e)

        # Start aiohttp server in the background
        port = int(os.environ.get("PORT", 8000))
        runner = web.AppRunner(webhook_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        log.info("Webhook server listening on port %d ✅", port)

        # Start Discord bot (runs until cancelled)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
