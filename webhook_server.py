"""
webhook_server.py – aiohttp HTTP server that receives TBA and Nexus webhooks.

Routes
------
POST /webhook/tba    – TBA match_score, upcoming_match, verification, ping
POST /webhook/nexus  – Nexus queue status updates (On deck, On field, etc.)
GET  /health         – simple health check for Railway

TBA webhook setup
-----------------
1. Go to https://www.thebluealliance.com/account
2. Under "Webhooks", add your Railway URL:
   https://<your-app>.railway.app/webhook/tba
3. Set a secret — put it in Railway env as TBA_HMAC_SECRET

Nexus webhook setup
-------------------
Register via the Nexus API by POSTing your event key + webhook URL.
The bot does this automatically via /setup nexus-webhook <event_key>.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    import discord
    from discord.ext import commands

log = logging.getLogger("webhook_server")

TBA_HMAC_SECRET: str = os.environ.get("TBA_HMAC_SECRET", "")
NEXUS_AUTH: str      = os.environ.get("NEXUS_AUTH", "")


# ── HMAC verification ─────────────────────────────────────────────────────────

def _verify_tba_hmac(body: bytes, received_hmac: str) -> bool:
    """Verify TBA's X-TBA-HMAC header against our secret."""
    if not TBA_HMAC_SECRET:
        log.warning("TBA_HMAC_SECRET not set — skipping HMAC verification (unsafe!)")
        return True

    # TBA computes HMAC-MD5 using the secret as the key.
    # Try string-encoded key first, then raw bytes (in case secret is hex-encoded).
    expected_str = hmac.new(
        TBA_HMAC_SECRET.encode("utf-8"),
        body,
        hashlib.md5,
    ).hexdigest()

    try:
        expected_bytes = hmac.new(
            bytes.fromhex(TBA_HMAC_SECRET),
            body,
            hashlib.md5,
        ).hexdigest()
    except ValueError:
        expected_bytes = None

    log.info(
        "HMAC debug — received: %s | expected(str): %s | expected(bytes): %s",
        received_hmac, expected_str, expected_bytes,
    )

    if hmac.compare_digest(expected_str, received_hmac):
        return True
    if expected_bytes and hmac.compare_digest(expected_bytes, received_hmac):
        log.info("HMAC matched using raw-bytes key")
        return True
    return False


def _verify_nexus_auth(request: web.Request) -> bool:
    """Nexus passes its API key as a header."""
    return request.headers.get("Nexus-Api-Key", "") == NEXUS_AUTH


# ── TBA webhook handler ───────────────────────────────────────────────────────

async def handle_tba(request: web.Request) -> web.Response:
    body = await request.read()

    # Verify HMAC
    received = request.headers.get("X-TBA-HMAC", "")
    if not _verify_tba_hmac(body, received):
        log.warning("TBA webhook: invalid HMAC — rejected")
        return web.Response(status=403, text="Invalid HMAC")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return web.Response(status=400, text="Bad JSON")

    msg_type = payload.get("message_type", "")
    msg_data = payload.get("message_data", {})

    log.info("TBA webhook: %s", msg_type)

    bot: commands.Bot = request.app["bot"]

    if msg_type == "verification":
        # TBA sends this when you first register — must respond 200
        log.info("TBA webhook verified ✅ (key: %s)", msg_data.get("verification_key"))
        return web.Response(status=200, text="ok")

    if msg_type == "ping":
        return web.Response(status=200, text="pong")

    if msg_type == "match_score":
        await _dispatch(bot, "tba_match_score", msg_data)

    elif msg_type == "upcoming_match":
        await _dispatch(bot, "tba_upcoming_match", msg_data)

    elif msg_type == "schedule_updated":
        await _dispatch(bot, "tba_schedule_updated", msg_data)

    elif msg_type == "starting_comp_level":
        await _dispatch(bot, "tba_starting_comp_level", msg_data)

    return web.Response(status=200, text="ok")


# ── Nexus webhook handler ─────────────────────────────────────────────────────

async def handle_nexus(request: web.Request) -> web.Response:
    if not _verify_nexus_auth(request):
        log.warning("Nexus webhook: invalid auth — rejected")
        return web.Response(status=403, text="Invalid auth")

    try:
        payload = json.loads(await request.read())
    except json.JSONDecodeError:
        return web.Response(status=400, text="Bad JSON")

    log.info("Nexus webhook: event=%s match=%s status=%s",
             payload.get("eventKey"), payload.get("matchLabel"), payload.get("status"))

    bot: commands.Bot = request.app["bot"]
    await _dispatch(bot, "nexus_queue_update", payload)

    return web.Response(status=200, text="ok")


# ── Health check ──────────────────────────────────────────────────────────────

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "bot": str(request.app["bot"].user)})


# ── Event dispatcher ──────────────────────────────────────────────────────────

async def _dispatch(bot: "commands.Bot", event_name: str, data: dict) -> None:
    """
    Fire a custom bot event so cogs can listen with @commands.Cog.listener().
    e.g. notifications.py listens for on_tba_match_score(data).
    """
    bot.dispatch(event_name, data)


# ── App factory ───────────────────────────────────────────────────────────────

def build_webhook_app(bot: "commands.Bot") -> web.Application:
    app = web.Application()
    app["bot"] = bot

    app.router.add_post("/webhook/tba",   handle_tba)
    app.router.add_post("/webhook/nexus", handle_nexus)
    app.router.add_get("/health",         handle_health)

    return app
