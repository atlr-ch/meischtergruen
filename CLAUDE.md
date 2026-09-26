# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Meischtergruen syncs Mr. Green recycling pickup dates to Google Calendar and/or a CalDAV calendar (Nextcloud). It's a single Python script running in a Docker container — no web UI. It fetches dates from the Mr. Green API, clears existing calendar events, and creates new all-day events. Runs on startup and then on a weekly schedule.

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
- `GOOGLE_CALENDAR_ID` - Google Calendar ID to sync events to (needs service account JSON at `./credentials/service-account.json`)
- `CALDAV_URL` + `CALDAV_USERNAME` + `CALDAV_PASSWORD` - full CalDAV calendar URL and credentials (Nextcloud app password)

At least one target is required; the script exits otherwise.

## Architecture

Single file: `meischtergruen.py` with five sections:

1. **Config & constants** (lines 1-60) - Env vars, subscription type map, German month map, API URL
2. **Mr. Green API client** (lines 63-103) - POST to `https://api-service.mr-green.ch/api/system/pickup-dates` with `zip`/`type`, parse German date strings ("20. Januar 2025")
3. **Google Calendar ops** (lines 106-167) - Service account auth, delete future events (paginated), create all-day events (transparent, 6hr popup reminder)
4. **CalDAV ops** (lines 170-233) - `caldav` library, delete future events via time-range search, create all-day VEVENTs built as raw iCalendar text (TRANSP:TRANSPARENT, VALARM -PT6H)
5. **Main loop** (lines 236-304) - Fetch once, then sync each enabled target independently (one failing doesn't block the other); sync on startup, then `schedule` library for recurring runs

### Mr. Green API

The old `api.mr-green.ch` backend was shut down in July 2026. The current endpoint is the one the Shopify site's Abholtermine page (`mr-green.ch/pages/abholtermine`) calls.

- Endpoint: `POST https://api-service.mr-green.ch/api/system/pickup-dates`
- Request: `zip` and `type` sent both as query params and as a form body (mirrors the site)
- Subscription types (`SUBSCRIPTION_MAP`), lowercase:
  - `monthly`: `Home Light`, `Home Smart`, `Pinkbag`, `Office Light`
  - `biweekly`: `Home Basic`, `Home Plus`, `Office Basic`, `Office Medium`
  - `weekly`: `Office Plus`
  - Unmapped values are passed through as the raw `type`
- Response: `{"success": true, "data": [{"date": ["16. Februar 2026", ...], "town": "Dietikon", ...}]}` — only `data[0]` is used
- Dates are in German with umlauts (e.g. "März")

### Google Calendar

- Uses service account auth (no browser/OAuth flow)
- All-day events with `transparency: "transparent"` (show as free)
- 6-hour popup reminder
- Sync is idempotent: deletes all events from today onward, then recreates

## CI/CD

GitHub Actions workflow (`.github/workflows/docker.yml`) builds and pushes to `ghcr.io` on pushes to main. Image is private — NAS pulls with a classic PAT (`read:packages`).