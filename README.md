# FRC Webhook Bot

Event-driven FRC match notifications via **TBA webhooks** and **Nexus webhooks** — no polling.

## How it's different from the polling bot

| | Polling bot | Webhook bot |
|---|---|---|
| Match results | Checks TBA every 30s | TBA pushes instantly on score post |
| Queue alerts | Checks Nexus every 30s | Nexus pushes on status change |
| API calls | Continuous | Only when events happen |
| Latency | Up to 30s | Near-instant |

---

## Setup

### 1. Railway deployment

1. Create a new Railway project
2. Add a **Postgres** service and link it
3. Deploy this repo as a service
4. Set a **custom domain** (needed for webhook URLs) in Railway → Settings → Networking

### 2. Environment variables

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Your bot token |
| `TBA_KEY` | Blue Alliance API key |
| `TBA_HMAC_SECRET` | Secret you set when registering the TBA webhook |
| `NEXUS_AUTH` | frc.nexus API key |
| `WEBHOOK_BASE_URL` | Your public Railway URL, e.g. `https://yourapp.up.railway.app` |
| `FRC_SEASON` | Optional, defaults to `2026` |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` | Auto-injected by Railway |

### 3. Register the TBA webhook

1. Go to https://www.thebluealliance.com/account
2. Under **Webhooks**, click **Add Webhook**
3. URL: `https://yourapp.up.railway.app/webhook/tba`
4. Set a secret — save it as `TBA_HMAC_SECRET` in Railway
5. TBA will send a verification ping — the bot logs it and responds automatically

### 4. Register Nexus webhooks

For each event you want queue alerts from, run in Discord:
```
/setup nexus-webhook 2026isde1
```
The bot calls the Nexus API and registers your URL automatically. You need to do this per-event.

### 5. First-time server setup

```
/setup channel #announcements
/setup adminrole @Admins       (optional)
/addteam 5987
```

---

## Webhook endpoints

| Route | Purpose |
|---|---|
| `POST /webhook/tba` | Receives TBA match_score, upcoming_match, starting_comp_level, ping, verification |
| `POST /webhook/nexus` | Receives Nexus queue status updates |
| `GET /health` | Health check |

---

## File structure

```
app.py                  Main entry — Discord bot + aiohttp server in one process
webhook_server.py       HTTP routes, HMAC verification, event dispatch
event_router.py         Maps team numbers → interested guilds/users
database.py             PostgreSQL persistence
tba.py                  TBA REST API wrapper (for /nextmatch and enrichment)
cogs/
  online.py             on_ready
  help.py               /help (dynamic)
  config.py             /setup, /addteam, /addepa, /removeteam, /listteams, /serverinfo
  my_teams.py           /myteam add/remove/list/clear
  team_info.py          /nextmatch
  notifications.py      Webhook event listeners → Discord embeds
```
