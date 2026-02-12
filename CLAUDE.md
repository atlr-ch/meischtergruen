# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Meischtergruen syncs Mr. Green recycling pickup dates to Google Calendar. It's a single Python script running in a Docker container — no web UI. It fetches dates from the Mr. Green API, clears existing calendar events, and creates new all-day events. Runs on startup and then on a weekly schedule.

## Development Commands

```bash
# Start (builds if needed)
docker compose up --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Configuration

Copy `.env.example` to `.env` and set at minimum:
- `GOOGLE_CALENDAR_ID` (required) - Google Calendar ID to sync events to
- Place service account JSON at `./credentials/service-account.json`

## Architecture

Single file: `meischtergruen.py` with four sections:

1. **Config & constants** (lines 1-42) - Env vars, German month map, subscription type map
2. **Mr. Green API client** (lines 45-83) - POST to `https://api.mr-green.ch/api/get-pickup-dates-new-main` with `{zip, type}`, parse German date strings ("20. Januar 2025")
3. **Google Calendar ops** (lines 86-147) - Service account auth, delete future events (paginated), create all-day events (transparent, 6hr popup reminder)
4. **Main loop** (lines 150-207) - Sync on startup, then `schedule` library for recurring runs

### Mr. Green API

- Endpoint: `POST https://api.mr-green.ch/api/get-pickup-dates-new-main`
- Payload: `{"zip": 8953, "type": "Monthly"}` (zip as int)
- Subscription types: `Home Plus` -> `Biweekly`, `Home Light` -> `Monthly`, `Office Plus` -> `Weekly`
- Response: `{"success": true, "dates_data": [{"zip": 8953, "date": ["16. Februar 2026", ...], "town": "Dietikon"}]}`
- Dates are in German with umlauts (e.g. "März")

### Google Calendar

- Uses service account auth (no browser/OAuth flow)
- All-day events with `transparency: "transparent"` (show as free)
- 6-hour popup reminder
- Sync is idempotent: deletes all events from today onward, then recreates

## CI/CD

GitHub Actions workflow (`.github/workflows/docker.yml`) builds and pushes to `ghcr.io` on pushes to main. Image is private — NAS pulls with a classic PAT (`read:packages`).

## Deployment

Deployed on TrueNAS via the `nas` repo. Stack file: `apps/tools.yml` (service `meischtergruen`). Secrets in `apps/.secrets.yml` (`MEISCHTERGRUEN_CALENDAR_ID`). Credentials at `/mnt/ssd/apps/meischtergruen/credentials/service-account.json`.
