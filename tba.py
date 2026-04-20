"""
tba.py – thin async wrapper around The Blue Alliance v3 API.
Used to enrich webhook payloads (fetch team nicknames, event names, etc.)
and for the /nextmatch command.
"""

from __future__ import annotations

import json
import os
from typing import Any

import aiohttp

_TBA_KEY: str = os.environ.get("TBA_KEY", "")
if not _TBA_KEY:
    try:
        with open("keys.json", encoding="utf-8") as f:
            _TBA_KEY = json.load(f).get("tbaKey", "")
    except FileNotFoundError:
        pass

BASE    = "https://www.thebluealliance.com/api/v3"
HEADERS = {"X-TBA-Auth-Key": _TBA_KEY}


async def get(session: aiohttp.ClientSession, path: str) -> Any | None:
    url = f"{BASE}/{path.lstrip('/')}"
    async with session.get(url, headers=HEADERS) as r:
        if r.status != 200:
            return None
        return await r.json()


async def team_info(session: aiohttp.ClientSession, team_number: str) -> dict | None:
    return await get(session, f"team/frc{team_number}")


async def team_events(session: aiohttp.ClientSession, team_number: str, year: str) -> list | None:
    return await get(session, f"team/frc{team_number}/events/{year}/simple")


async def event_full(session: aiohttp.ClientSession, event_key: str) -> dict | None:
    return await get(session, f"event/{event_key}")


async def event_matches(session: aiohttp.ClientSession, event_key: str) -> list | None:
    return await get(session, f"event/{event_key}/matches")


async def match_detail(session: aiohttp.ClientSession, match_key: str) -> dict | None:
    return await get(session, f"match/{match_key}")


async def event_teams(session: aiohttp.ClientSession, event_key: str) -> list | None:
    return await get(session, f"event/{event_key}/teams/simple")
