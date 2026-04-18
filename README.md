# FRC Discord Bot 🤖

A generic, multi-server FRC bot with per-server team tracking, live match alerts, and EPA monitoring.

---

## Features

| Feature | Command | Who sees it |
|---|---|---|
| Team info, blue banners | `/team <number>` | 🔒 You only (ephemeral) |
| Event list | `/events <number> [year]` | 🔒 You only |
| Event info | `/event <event_key>` | 🔒 You only |
| Match results | `/matches <number> <event>` | 🔒 You only |
| Robot names | `/robots <number>` | 🔒 You only |
| Event ranking | `/ranking <number> <event>` | 🔒 You only |
| Statbotics EPA | `/epa <number> [year]` | 🔒 You only |
| Tracked teams list | `/listteams` | 🔒 You only |
| EPA tracked teams | `/epalist` | 🔒 You only |
| **Live match alerts** | auto | 📢 Server channel |
| **EPA change alerts** | auto | 📢 Server channel |

### Admin commands (Manage Server or configured admin role)

| Command | Description |
|---|---|
| `/setup channel <#channel>` | Set the announcement channel |
| `/setup adminrole <@role>` | Grant a role bot-admin access |
| `/addteam <number>` | Track a team (live alerts) |
| `/removeteam <number>` | Stop tracking a team |
| `/trackepa <number>` | Track EPA changes |
| `/untrackepa <number>` | Stop EPA tracking |
| `/serverinfo` | Show bot config for this server |

---

## Deploying on Railway

### 1. Create a new Railway project
Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** and connect your repo.

### 2. Add a PostgreSQL database
In your project dashboard → **+ New** → **Database** → **PostgreSQL**.
Railway will automatically inject `DATABASE_URL` into your bot's environment.

### 3. Set environment variables
In your Railway service → **Variables**, add:

| Variable | Value |
|---|---|
| `DISCORD_BOT_TOKEN` | Your bot token from the Discord Developer Portal |
| `TBA_KEY` | Your Blue Alliance API key |
| `NEXUS_AUTH` | Your frc.nexus API key |

> `DATABASE_URL` is set automatically by Railway — do not add it manually.

### 4. Deploy
Push to your connected branch. Railway builds with Nixpacks and runs `python app.py` automatically.

### 5. First-time server setup (admin)
1. `/setup channel #your-announcements-channel`
2. `/setup adminrole @YourAdminRole` *(optional)*
3. `/addteam 5987` or `/addepa 25`

---

## Local development

```bash
pip install -r requirements.txt

export DISCORD_BOT_TOKEN="your-discord-bot-token"
export TBA_KEY="your-tba-api-key"
export NEXUS_AUTH="your-nexus-api-key"
export DATABASE_URL="postgresql://user:pass@localhost:5432/frcbot"

python app.py
```

Or set `TBA_KEY` via `keys.json` instead of an env var:
```json
{ "tbaKey": "your-tba-key" }
```

---

## Architecture

```
app.py            – bot entry point, loads all cogs
database.py       – SQLite persistence (server config, tracked teams, EPA)
tba.py            – async TBA API wrapper
cogs/
  online.py       – on_ready handler
  help.py         – /help command
  config.py       – admin setup commands
  team_info.py    – lookup commands (all ephemeral)
  epa.py          – EPA lookup + background change tracking
  live_watch.py   – Nexus + TBA polling → channel announcements
```

### Privacy model
- **Lookup commands** (`/team`, `/epa`, etc.) are always `ephemeral=True` – Discord shows them only to the invoking user.  Nobody else in the server sees them.
- **Live announcements** (match alerts, EPA changes) are sent to the admin-configured channel and are visible to everyone in the server.

### Multi-server
Every guild gets its own tracked team list and announce channel stored in `frc_bot.db`.  One bot instance serves all servers independently.

---

## Database

SQLite, auto-created at `frc_bot.db` (override with `BOT_DB_PATH` env var).

| Table | Purpose |
|---|---|
| `server_config` | Channel & admin-role per guild |
| `tracked_teams` | Which teams each guild follows |
| `epa_tracking` | EPA-tracked teams + last known EPA |
