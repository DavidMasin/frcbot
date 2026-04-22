"""
database.py – PostgreSQL persistence layer.

Tables
------
server_config         : per-guild settings (announce channel, admin role)
tracked_teams         : teams being watched per guild (admin-managed)
user_teams            : personal user team subscriptions (DM notifications)
known_team_events     : seeding table — prevents flooding old events/matches on first add
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool

log = logging.getLogger("database")


def _build_db_kwargs() -> dict:
    host = os.environ.get("PGHOST") or os.environ.get("DB_HOST")
    if host:
        return dict(
            host=host,
            port=int(os.environ.get("PGPORT") or 5432),
            user=os.environ.get("PGUSER") or "postgres",
            password=os.environ.get("PGPASSWORD") or "",
            dbname=os.environ.get("PGDATABASE") or "railway",
            sslmode="require",
            connect_timeout=10,
        )

    raw_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PRIVATE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
        or ""
    )
    if raw_url:
        if raw_url.startswith("postgres://"):
            raw_url = raw_url.replace("postgres://", "postgresql://", 1)
        parsed = urlparse(raw_url)
        if parsed.hostname:
            return dict(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                dbname=(parsed.path or "/railway").lstrip("/"),
                sslmode="require",
                connect_timeout=10,
            )

    raise RuntimeError(
        "No database config found. Set PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE "
        "or DATABASE_URL."
    )


_DB_KWARGS = _build_db_kwargs()
_pool: psycopg2.pool.SimpleConnectionPool | None = None


def _get_pool() -> psycopg2.pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 10, **_DB_KWARGS)
        log.info("DB pool ready → %s:%s/%s",
                 _DB_KWARGS["host"], _DB_KWARGS["port"], _DB_KWARGS["dbname"])
    return _pool


@contextmanager
def _cursor():
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
            CREATE TABLE IF NOT EXISTS known_team_events (
                guild_id    BIGINT NOT NULL,
                team_number TEXT   NOT NULL,
                event_key   TEXT   NOT NULL,
                PRIMARY KEY (guild_id, team_number, event_key)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seen_matches (
                guild_id  BIGINT NOT NULL,
                match_key TEXT   NOT NULL,
                PRIMARY KEY (guild_id, match_key)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS guild_nexus_seeded (
                guild_id BIGINT PRIMARY KEY
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seen_queue (
                event_key TEXT NOT NULL,
                label     TEXT NOT NULL,
                status    TEXT NOT NULL,
                PRIMARY KEY (event_key, label, status)
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


def get_all_configs() -> list[dict]:
    with _cursor() as cur:
        cur.execute("SELECT * FROM server_config WHERE announce_channel_id IS NOT NULL")
        return [dict(r) for r in cur.fetchall()]


# ── Tracked teams ─────────────────────────────────────────────────────────────

def add_tracked_team(guild_id: int, team_number: str) -> bool:
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


def get_all_tracked_team_numbers() -> set[str]:
    """All unique team numbers tracked by any guild."""
    with _cursor() as cur:
        cur.execute("SELECT DISTINCT team_number FROM tracked_teams")
        return {r["team_number"] for r in cur.fetchall()}


def get_guilds_tracking_team(team_number: str) -> list[int]:
    """Return all guild IDs that track this team number."""
    with _cursor() as cur:
        cur.execute(
            "SELECT guild_id FROM tracked_teams WHERE team_number = %s", (str(team_number),)
        )
        return [r["guild_id"] for r in cur.fetchall()]


# ── User personal subscriptions ───────────────────────────────────────────────

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


def get_users_subscribed_to_team(team_number: str) -> list[int]:
    with _cursor() as cur:
        cur.execute(
            "SELECT user_id FROM user_teams WHERE team_number = %s", (str(team_number),)
        )
        return [r["user_id"] for r in cur.fetchall()]


# ── Known team events (new registration detection) ────────────────────────────

def get_known_events(guild_id: int, team_number: str) -> set[str]:
    with _cursor() as cur:
        cur.execute(
            "SELECT event_key FROM known_team_events WHERE guild_id = %s AND team_number = %s",
            (guild_id, str(team_number)),
        )
        return {r["event_key"] for r in cur.fetchall()}


def add_known_events(guild_id: int, team_number: str, event_keys: set[str]) -> None:
    if not event_keys:
        return
    with _cursor() as cur:
        for key in event_keys:
            cur.execute("""
                INSERT INTO known_team_events (guild_id, team_number, event_key)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """, (guild_id, str(team_number), key))


# ── Seen matches (dedup for result announcements) ─────────────────────────────

def is_match_seen(guild_id: int, match_key: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            "SELECT 1 FROM seen_matches WHERE guild_id = %s AND match_key = %s",
            (guild_id, match_key),
        )
        return cur.fetchone() is not None


def mark_match_seen(guild_id: int, match_key: str) -> None:
    with _cursor() as cur:
        cur.execute("""
            INSERT INTO seen_matches (guild_id, match_key) VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (guild_id, match_key))


def seed_seen_matches(guild_id: int, match_keys: list[str]) -> None:
    """Bulk-insert match keys as seen (used when a new team is added)."""
    if not match_keys:
        return
    with _cursor() as cur:
        for key in match_keys:
            cur.execute("""
                INSERT INTO seen_matches (guild_id, match_key) VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (guild_id, key))



# ── Seen queue (Nexus dedup) ──────────────────────────────────────────────────

def is_queue_seen(event_key: str, label: str, status: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            "SELECT 1 FROM seen_queue WHERE event_key = %s AND label = %s AND status = %s",
            (event_key, label, status),
        )
        return cur.fetchone() is not None


def mark_queue_seen(event_key: str, label: str, status: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO seen_queue (event_key, label, status) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (event_key, label, status),
        )

# ── Guild Nexus seeding ───────────────────────────────────────────────────────

def is_guild_nexus_seeded(guild_id: int) -> bool:
    with _cursor() as cur:
        cur.execute("SELECT 1 FROM guild_nexus_seeded WHERE guild_id = %s", (guild_id,))
        return cur.fetchone() is not None


def mark_guild_nexus_seeded(guild_id: int) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO guild_nexus_seeded (guild_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (guild_id,),
        )
