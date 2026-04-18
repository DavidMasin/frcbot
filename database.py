"""
database.py – SQLite persistence layer for the FRC bot.

Tables
------
server_config  : per-guild settings (announce channel, etc.)
tracked_teams  : teams being watched per guild (server-wide, admin-managed)
user_teams     : teams a specific user personally subscribes to (DM notifications)
epa_tracking   : teams with EPA change tracking enabled per guild
"""

from __future__ import annotations
import sqlite3
import os
from pathlib import Path

DB_PATH = os.environ.get("BOT_DB_PATH", "frc_bot.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS server_config (
                guild_id            INTEGER PRIMARY KEY,
                announce_channel_id INTEGER,
                admin_role_id       INTEGER
            );

            CREATE TABLE IF NOT EXISTS tracked_teams (
                guild_id    INTEGER NOT NULL,
                team_number TEXT    NOT NULL,
                PRIMARY KEY (guild_id, team_number)
            );

            CREATE TABLE IF NOT EXISTS user_teams (
                user_id     INTEGER NOT NULL,
                team_number TEXT    NOT NULL,
                PRIMARY KEY (user_id, team_number)
            );

            CREATE TABLE IF NOT EXISTS epa_tracking (
                guild_id    INTEGER NOT NULL,
                team_number TEXT    NOT NULL,
                last_epa    REAL,
                PRIMARY KEY (guild_id, team_number)
            );
        """)


# ──────────────────────────────────────────────────────────────────────────────
#  Server config
# ──────────────────────────────────────────────────────────────────────────────

def get_config(guild_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM server_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return dict(row) if row else None


def set_announce_channel(guild_id: int, channel_id: int) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO server_config (guild_id, announce_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET announce_channel_id = excluded.announce_channel_id
        """, (guild_id, channel_id))


def set_admin_role(guild_id: int, role_id: int) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO server_config (guild_id, admin_role_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET admin_role_id = excluded.admin_role_id
        """, (guild_id, role_id))


# ──────────────────────────────────────────────────────────────────────────────
#  Tracked teams
# ──────────────────────────────────────────────────────────────────────────────

def add_tracked_team(guild_id: int, team_number: str) -> bool:
    """Returns True if newly added, False if already tracked."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO tracked_teams (guild_id, team_number) VALUES (?, ?)",
                (guild_id, str(team_number)),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_tracked_team(guild_id: int, team_number: str) -> bool:
    """Returns True if removed, False if wasn't tracked."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM tracked_teams WHERE guild_id = ? AND team_number = ?",
            (guild_id, str(team_number)),
        )
    return cur.rowcount > 0


def get_tracked_teams(guild_id: int) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT team_number FROM tracked_teams WHERE guild_id = ?", (guild_id,)
        ).fetchall()
    return [r["team_number"] for r in rows]


def get_all_tracked_teams() -> dict[int, list[str]]:
    """Returns {guild_id: [team_numbers]} for all guilds."""
    with _connect() as conn:
        rows = conn.execute("SELECT guild_id, team_number FROM tracked_teams").fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(row["guild_id"], []).append(row["team_number"])
    return result


# ──────────────────────────────────────────────────────────────────────────────
#  EPA tracking
# ──────────────────────────────────────────────────────────────────────────────

def add_epa_tracking(guild_id: int, team_number: str, current_epa: float | None = None) -> bool:
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO epa_tracking (guild_id, team_number, last_epa) VALUES (?, ?, ?)",
                (guild_id, str(team_number), current_epa),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_epa_tracking(guild_id: int, team_number: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM epa_tracking WHERE guild_id = ? AND team_number = ?",
            (guild_id, str(team_number)),
        )
    return cur.rowcount > 0


def get_epa_tracked_teams(guild_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT team_number, last_epa FROM epa_tracking WHERE guild_id = ?", (guild_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_last_epa(guild_id: int, team_number: str, epa: float) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE epa_tracking SET last_epa = ? WHERE guild_id = ? AND team_number = ?",
            (epa, guild_id, str(team_number)),
        )


def get_all_epa_tracked() -> dict[int, list[dict]]:
    with _connect() as conn:
        rows = conn.execute("SELECT guild_id, team_number, last_epa FROM epa_tracking").fetchall()
    result: dict[int, list[dict]] = {}
    for row in rows:
        result.setdefault(row["guild_id"], []).append(dict(row))
    return result


# ──────────────────────────────────────────────────────────────────────────────
#  User personal team subscriptions
# ──────────────────────────────────────────────────────────────────────────────

def add_user_team(user_id: int, team_number: str) -> bool:
    """Subscribe a user to a team.  Returns True if newly added."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO user_teams (user_id, team_number) VALUES (?, ?)",
                (user_id, str(team_number)),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_user_team(user_id: int, team_number: str) -> bool:
    """Unsubscribe a user from a team.  Returns True if removed."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM user_teams WHERE user_id = ? AND team_number = ?",
            (user_id, str(team_number)),
        )
    return cur.rowcount > 0


def get_user_teams(user_id: int) -> list[str]:
    """Return all team numbers a user is personally subscribed to."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT team_number FROM user_teams WHERE user_id = ?", (user_id,)
        ).fetchall()
    return [r["team_number"] for r in rows]


def get_all_user_teams() -> dict[int, list[str]]:
    """Return {user_id: [team_numbers]} for every subscribed user."""
    with _connect() as conn:
        rows = conn.execute("SELECT user_id, team_number FROM user_teams").fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(row["user_id"], []).append(row["team_number"])
    return result


def get_users_subscribed_to_team(team_number: str) -> list[int]:
    """Return all user IDs that personally track a given team number."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id FROM user_teams WHERE team_number = ?", (str(team_number),)
        ).fetchall()
    return [r["user_id"] for r in rows]
