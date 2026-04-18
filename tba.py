"""
tba.py – thin async wrapper around The Blue Alliance v3 API.
"""

from __future__ import annotations

import os
import json
from typing import Any

import aiohttp

# Resolve TBA key: env var → keys.json → empty
_TBA_KEY: str = os.environ.get("TBA_KEY", "")
if not _TBA_KEY:
    try:
        with open("keys.json", encoding="utf-8") as f:
            _TBA_KEY = json.load(f).get("tbaKey", "")
    except FileNotFoundError:
        pass

BASE = "https://www.thebluealliance.com/api/v3"
HEADERS = {"X-TBA-Auth-Key": _TBA_KEY}


async def get(session: aiohttp.ClientSession, path: str) -> Any | None:
    """GET /path from TBA.  Returns parsed JSON or None on error."""
    url = f"{BASE}/{path.lstrip('/')}"
    async with session.get(url, headers=HEADERS) as r:
        if r.status != 200:
            return None
        return await r.json()


async def team_info(session: aiohttp.ClientSession, team_number: str) -> dict | None:
    return await get(session, f"team/frc{team_number}")


async def team_events(session: aiohttp.ClientSession, team_number: str, year: str | None = None) -> list | None:
    path = f"team/frc{team_number}/events/{year}/simple" if year else f"team/frc{team_number}/events/simple"
    return await get(session, path)


async def team_matches_at_event(session: aiohttp.ClientSession, team_number: str, event_key: str) -> list | None:
    return await get(session, f"team/frc{team_number}/event/{event_key}/matches/simple")


async def event_info(session: aiohttp.ClientSession, event_key: str) -> dict | None:
    return await get(session, f"event/{event_key}/simple")


async def event_full(session: aiohttp.ClientSession, event_key: str) -> dict | None:
    """Full event object including webcasts, rankings, district points, etc."""
    return await get(session, f"event/{event_key}")


async def event_matches(session: aiohttp.ClientSession, event_key: str) -> list | None:
    return await get(session, f"event/{event_key}/matches")


async def event_rankings(session: aiohttp.ClientSession, event_key: str) -> dict | None:
    return await get(session, f"event/{event_key}/rankings")


async def team_robots(session: aiohttp.ClientSession, team_number: str) -> list | None:
    return await get(session, f"team/frc{team_number}/robots")


async def team_awards(session: aiohttp.ClientSession, team_number: str) -> list | None:
    return await get(session, f"team/frc{team_number}/awards")
