"""
app.py – FRC Discord Bot entry point.

Setup
-----
Set these environment variables before running:
    DISCORD_BOT_TOKEN   – your bot's token
    TBA_KEY             – The Blue Alliance API key
    NEXUS_AUTH          – frc.nexus API key
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback

import discord
from discord import app_commands
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
TOKEN = os.environ["DISCORD_BOT_TOKEN"]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ── global app-command error handler ─────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    """Catch any unhandled slash-command error and report it to the user."""
    # Unwrap the real cause if it's wrapped in CommandInvokeError
    cause = getattr(error, "original", error)

    if isinstance(cause, app_commands.CheckFailure):
        msg = str(cause) or "❌ You don't have permission to use this command."
    elif isinstance(cause, app_commands.CommandOnCooldown):
        msg = f"⏳ Slow down! Try again in {cause.retry_after:.1f}s."
    else:
        # Log the full traceback so we can debug from Railway logs
        log.error(
            "Unhandled error in /%s: %s",
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
        pass   # interaction already expired — nothing we can do


# ── on_ready: sync commands to every guild immediately ────────────────────────

@bot.event
async def on_ready():
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)

    # Clear any guild-specific commands that were registered previously
    # (they cause duplicates alongside global commands)
    for guild in bot.guilds:
        try:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
            log.info("Cleared guild-specific commands for %s (%s)", guild.name, guild.id)
        except Exception as e:
            log.warning("Failed to clear guild commands for %s: %s", guild.id, e)

    await _sync_all()


async def _sync_all():
    """Sync the command tree globally."""
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d global command(s)", len(synced))
    except Exception as e:
        log.error("Global sync failed: %s", e)


# ── /sync slash command (admin-only) ─────────────────────────────────────────

@bot.tree.command(name="sync", description="Force re-sync slash commands (bot owner only)")
async def slash_sync(interaction: discord.Interaction):
    if interaction.user.id != (await bot.application_info()).owner.id:
        await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await _sync_all()
    await interaction.followup.send(
        "✅ Global sync complete. New commands may take up to an hour to appear in new servers, "
        "but should be available here immediately.",
        ephemeral=True,
    )


# ── extension loading ─────────────────────────────────────────────────────────

async def main() -> None:
    database.init_db()
    log.info("Database initialised ✅")

    async with bot:
        failed = []
        for fname in sorted(os.listdir("./cogs")):   # sorted = deterministic order
            if fname.endswith(".py"):
                ext = f"cogs.{fname[:-3]}"
                try:
                    await bot.load_extension(ext)
                    log.info("Loaded extension: %s", ext)
                except Exception as e:
                    log.error("Failed to load %s: %s", ext, e)
                    failed.append(ext)   # log and continue — don't crash the bot

        if failed:
            log.warning("The following extensions failed to load: %s", ", ".join(failed))

        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
