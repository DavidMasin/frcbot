"""
database.py – PostgreSQL persistence layer for the FRC bot.

Uses psycopg2 with a simple connection pool.
Railway injects DATABASE_URL automatically when a Postgres service is attached.

Tables
------
server_config  : per-guild settings (announce channel, admin role)
tracked_teams  : teams being watched per guild (server-wide, admin-managed)
user_teams     : teams a specific user personally subscribes to (DM notifications)
epa_tracking   : teams with EPA change tracking enabled per guild
"""

from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import psycopg2.pool
import psycopg2.errors

log = logging.getLogger("database")

# Railway injects DATABASE_URL for the private network.
# Fall back to DATABASE_PUBLIC_URL if private isn't set (useful for local tunnelling).
_RAW_URL: str = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("DATABASE_PUBLIC_URL")
    or ""
)

if not _RAW_URL:
    raise RuntimeError(
        "No database URL found. Set DATABASE_URL (Railway injects this automatically "
        "when a Postgres service is attached to your project)."
    )

# Parse URL components individually — avoids psycopg2's DSN parser which
# rejects Railway's internal hostname (postgres.railway.internal).
_parsed = urlparse(_RAW_URL)
_DB_KWARGS = dict(
    host=_parsed.hostname,
    port=_parsed.port or 5432,
    user=_parsed.username,
    password=_parsed.password,
    dbname=(_parsed.path or "/railway").lstrip("/"),
    sslmode="require",        # Railway Postgres requires SSL
    connect_timeout=10,
)

_pool: psycopg2.pool.SimpleConnectionPool | None = None


def _get_pool() -> psycopg2.pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 10, **_DB_KWARGS)
        log.info("DB pool created → %s:%s/%s", _DB_KWARGS["host"], _DB_KWARGS["port"], _DB_KWARGS["dbname"])
    return _pool


@contextmanager
def _cursor():
    """Yield a DictCursor and commit/rollback automatically."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist."""
    with _cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS server_config (
                guild_id            BIGINT PRIMARY KEY,
                announce_channel_id BIGINT,
                admin_role_id       BIGINT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tracked_teams (
                guild_id    BIGINT NOT NULL,
                team_number TEXT   NOT NULL,
                PRIMARY KEY (guild_id, team_number)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_teams (
                user_id     BIGINT NOT NULL,
                team_number TEXT   NOT NULL,
                PRIMARY KEY (user_id, team_number)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS epa_tracking (
                guild_id    BIGINT NOT NULL,
                team_number TEXT   NOT NULL,
                last_epa    FLOAT,
                PRIMARY KEY (guild_id, team_number)
            )
        """)
    log.info("Database schema ready ✅")


# ── Server config ─────────────────────────────────────────────────────────────

def get_config(guild_id: int) -> dict | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM server_config WHERE guild_id = %s", (guild_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def set_announce_channel(guild_id: int, channel_id: int) -> None:
    with _cursor() as cur:
        cur.execute("""
            INSERT INTO server_config (guild_id, announce_channel_id)
            VALUES (%s, %s)
            ON CONFLICT (guild_id) DO UPDATE SET announce_channel_id = EXCLUDED.announce_channel_id
        """, (guild_id, channel_id))


def set_admin_role(guild_id: int, role_id: int) -> None:
    with _cursor() as cur:
        cur.execute("""
            INSERT INTO server_config (guild_id, admin_role_id)
            VALUES (%s, %s)
            ON CONFLICT (guild_id) DO UPDATE SET admin_role_id = EXCLUDED.admin_role_id
        """, (guild_id, role_id))


# ── Tracked teams ─────────────────────────────────────────────────────────────

def add_tracked_team(guild_id: int, team_number: str) -> bool:
    """Returns True if newly added, False if already tracked."""
    try:
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO tracked_teams (guild_id, team_number) VALUES (%s, %s)",
                (guild_id, str(team_number)),
            )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


def remove_tracked_team(guild_id: int, team_number: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM tracked_teams WHERE guild_id = %s AND team_number = %s",
            (guild_id, str(team_number)),
        )
        return cur.rowcount > 0


def get_tracked_teams(guild_id: int) -> list[str]:
    with _cursor() as cur:
        cur.execute(
            "SELECT team_number FROM tracked_teams WHERE guild_id = %s", (guild_id,)
        )
        return [r["team_number"] for r in cur.fetchall()]


def get_all_tracked_teams() -> dict[int, list[str]]:
    with _cursor() as cur:
        cur.execute("SELECT guild_id, team_number FROM tracked_teams")
        result: dict[int, list[str]] = {}
        for row in cur.fetchall():
            result.setdefault(row["guild_id"], []).append(row["team_number"])
    return result


# ── EPA tracking ──────────────────────────────────────────────────────────────

def add_epa_tracking(guild_id: int, team_number: str, current_epa: float | None = None) -> bool:
    try:
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO epa_tracking (guild_id, team_number, last_epa) VALUES (%s, %s, %s)",
                (guild_id, str(team_number), current_epa),
            )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


def remove_epa_tracking(guild_id: int, team_number: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM epa_tracking WHERE guild_id = %s AND team_number = %s",
            (guild_id, str(team_number)),
        )
        return cur.rowcount > 0


def get_epa_tracked_teams(guild_id: int) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT team_number, last_epa FROM epa_tracking WHERE guild_id = %s", (guild_id,)
        )
        return [dict(r) for r in cur.fetchall()]


def update_last_epa(guild_id: int, team_number: str, epa: float) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE epa_tracking SET last_epa = %s WHERE guild_id = %s AND team_number = %s",
            (epa, guild_id, str(team_number)),
        )


def get_all_epa_tracked() -> dict[int, list[dict]]:
    with _cursor() as cur:
        cur.execute("SELECT guild_id, team_number, last_epa FROM epa_tracking")
        result: dict[int, list[dict]] = {}
        for row in cur.fetchall():
            result.setdefault(row["guild_id"], []).append(dict(row))
    return result


# ── User personal team subscriptions ─────────────────────────────────────────

def add_user_team(user_id: int, team_number: str) -> bool:
    try:
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO user_teams (user_id, team_number) VALUES (%s, %s)",
                (user_id, str(team_number)),
            )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


def remove_user_team(user_id: int, team_number: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM user_teams WHERE user_id = %s AND team_number = %s",
            (user_id, str(team_number)),
        )
        return cur.rowcount > 0


def get_user_teams(user_id: int) -> list[str]:
    with _cursor() as cur:
        cur.execute(
            "SELECT team_number FROM user_teams WHERE user_id = %s", (user_id,)
        )
        return [r["team_number"] for r in cur.fetchall()]


def get_all_user_teams() -> dict[int, list[str]]:
    with _cursor() as cur:
        cur.execute("SELECT user_id, team_number FROM user_teams")
        result: dict[int, list[str]] = {}
        for row in cur.fetchall():
            result.setdefault(row["user_id"], []).append(row["team_number"])
    return result


def get_users_subscribed_to_team(team_number: str) -> list[int]:
    with _cursor() as cur:
        cur.execute(
            "SELECT user_id FROM user_teams WHERE team_number = %s", (str(team_number),)
        )
        return [r["user_id"] for r in cur.fetchall()]
