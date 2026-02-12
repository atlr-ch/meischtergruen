# Meischtergruen

Syncs [Mr. Green](https://mr-green.ch) recycling pickup dates to Google Calendar.

Runs as a Docker container — fetches pickup dates on startup and weekly, creates all-day calendar events with a 6-hour reminder.

## Quick Start

1. Set up a Google Cloud service account ([instructions below](#google-cloud-setup))
2. Copy `.env.example` to `.env` and fill in `GOOGLE_CALENDAR_ID`
3. Place your service account JSON at `./credentials/service-account.json`
4. Run:

```bash
docker compose up --build
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CALENDAR_ID` | **yes** | - | Target calendar ID (`abc@group.calendar.google.com`) |
| `MR_GREEN_ZIP` | no | `8004` | Zip code for pickup dates |
| `MR_GREEN_SUBSCRIPTION` | no | `Home Plus` | `Home Plus`, `Home Light`, or `Office Plus` |
| `GOOGLE_CREDENTIALS_FILE` | no | `/credentials/service-account.json` | Path to service account JSON |
| `EVENT_TITLE` | no | `Mr. Green Pickup` | Calendar event title |
| `EVENT_LOCATION` | no | | Calendar event location |
| `EVENT_DESCRIPTION` | no | | Calendar event description |
| `SCHEDULE_CRON` | no | `friday` | Day of week, `daily`, or `HH:MM` for daily at specific time |
| `RUN_ON_STARTUP` | no | `true` | Run sync immediately on container start |

## Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com) and create a project
2. Enable the **Google Calendar API**
3. Go to **IAM & Admin > Service Accounts**, create a service account
4. Under the service account's **Keys** tab, create a JSON key and download it
5. In [Google Calendar](https://calendar.google.com), create a new calendar
6. Share the calendar with the service account email (grant **Make changes to events**)
7. Copy the **Calendar ID** from the calendar's settings (Integrate calendar section)
