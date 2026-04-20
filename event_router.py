"""
event_router.py – Given a set of team numbers from a webhook payload,
returns the guilds and users that should be notified.

This is the core routing layer: every webhook handler calls into here
to get the list of Discord channels/users to send to.
"""

from __future__ import annotations

import logging

import database

log = logging.getLogger("event_router")


def get_interested_guilds(team_numbers: set[str]) -> dict[int, set[str]]:
    """
    Returns {guild_id: {team_numbers_in_match}} for every guild that
    tracks at least one team in the provided set.
    """
    result: dict[int, set[str]] = {}
    for team in team_numbers:
        for guild_id in database.get_guilds_tracking_team(team):
            result.setdefault(guild_id, set()).add(team)
    return result


def get_interested_users(team_numbers: set[str]) -> dict[int, set[str]]:
    """
    Returns {user_id: {team_numbers_in_match}} for every user personally
    subscribed to at least one team in the provided set.
    """
    result: dict[int, set[str]] = {}
    for team in team_numbers:
        for user_id in database.get_users_subscribed_to_team(team):
            result.setdefault(user_id, set()).add(team)
    return result


def extract_teams_from_match(match_data: dict) -> set[str]:
    """Extract bare team numbers (no 'frc' prefix) from a TBA match dict."""
    teams: set[str] = set()
    alliances = match_data.get("alliances") or {}
    for color in ("red", "blue"):
        for key in alliances.get(color, {}).get("team_keys", []):
            teams.add(key.lstrip("frc"))
    return teams
