import os
import sys
import logging
import time
from datetime import date

import requests
import schedule
from google.oauth2 import service_account
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("meischtergruen")

# Configuration
MR_GREEN_ZIP = os.environ.get("MR_GREEN_ZIP", "8004")
MR_GREEN_SUBSCRIPTION = os.environ.get("MR_GREEN_SUBSCRIPTION", "Home Plus")
GOOGLE_CALENDAR_ID = os.environ["GOOGLE_CALENDAR_ID"]  # Required
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/credentials/service-account.json")
EVENT_TITLE = os.environ.get("EVENT_TITLE", "Mr. Green Pickup")
EVENT_LOCATION = os.environ.get("EVENT_LOCATION", "")
EVENT_DESCRIPTION = os.environ.get("EVENT_DESCRIPTION", "")
SCHEDULE_CRON = os.environ.get("SCHEDULE_CRON", "friday")
RUN_ON_STARTUP = os.environ.get("RUN_ON_STARTUP", "true").lower() == "true"

SUBSCRIPTION_MAP = {
    "Home Plus": "Biweekly",
    "Home Light": "Monthly",
    "Office Plus": "Weekly",
}

GERMAN_MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Juli": 7, "August": 8,
    "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

MR_GREEN_API_URL = "https://api.mr-green.ch/api/get-pickup-dates-new-main"


def parse_german_date(date_str: str) -> date:
    """Parse '20. Januar 2025' into a date object."""
    parts = date_str.split()
    if len(parts) != 3:
        raise ValueError(f"Unexpected date format: '{date_str}'")
    day = int(parts[0].rstrip("."))
    month = GERMAN_MONTHS.get(parts[1])
    if month is None:
        raise ValueError(f"Unknown German month: '{parts[1]}' in '{date_str}'")
    year = int(parts[2])
    return date(year, month, day)


def fetch_pickup_dates(zip_code: str, subscription: str) -> list[date]:
    """Fetch pickup dates from Mr. Green API."""
    api_type = SUBSCRIPTION_MAP.get(subscription, subscription)
    log.info(f"Fetching dates for ZIP {zip_code}, type '{api_type}'")

    response = requests.post(
        MR_GREEN_API_URL,
        json={"zip": int(zip_code), "type": api_type},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        raise ValueError(f"API returned success=false: {data.get('msg', 'unknown error')}")

    dates_data = data.get("dates_data", [])
    if not dates_data:
        raise ValueError("API returned empty dates_data")

    raw_dates = dates_data[0].get("date", [])
    town = dates_data[0].get("town", "unknown")
    log.info(f"Town: {town}, received {len(raw_dates)} date strings")

    parsed = sorted(parse_german_date(d) for d in raw_dates)
    return parsed


def get_calendar_service():
    """Build authenticated Google Calendar API service."""
    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def clear_future_events(service, calendar_id: str):
    """Delete all future events from the calendar."""
    now = date.today().isoformat() + "T00:00:00Z"
    log.info("Clearing future events...")

    page_token = None
    deleted = 0
    while True:
        events = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            singleEvents=True,
            pageToken=page_token,
            maxResults=250,
        ).execute()

        for event in events.get("items", []):
            service.events().delete(
                calendarId=calendar_id,
                eventId=event["id"],
            ).execute()
            deleted += 1

        page_token = events.get("nextPageToken")
        if not page_token:
            break

    log.info(f"Deleted {deleted} future events")


def create_pickup_events(service, calendar_id: str, dates: list[date]):
    """Create all-day events for each pickup date."""
    for d in dates:
        event_body = {
            "summary": EVENT_TITLE,
            "start": {"date": d.isoformat()},
            "end": {"date": d.isoformat()},
            "transparency": "transparent",
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 360},
                ],
            },
        }
        if EVENT_LOCATION:
            event_body["location"] = EVENT_LOCATION
        if EVENT_DESCRIPTION:
            event_body["description"] = EVENT_DESCRIPTION

        service.events().insert(calendarId=calendar_id, body=event_body).execute()

    log.info(f"Created {len(dates)} pickup events")


def sync():
    """Fetch dates, clear calendar, create events."""
    try:
        log.info("=== Starting Mr. Green calendar sync ===")

        dates = fetch_pickup_dates(MR_GREEN_ZIP, MR_GREEN_SUBSCRIPTION)
        if not dates:
            log.warning("No pickup dates returned")
            return

        today = date.today()
        future_dates = [d for d in dates if d >= today]
        log.info(f"Total dates: {len(dates)}, future dates: {len(future_dates)}")

        if not future_dates:
            log.warning("No future pickup dates found")
            return

        service = get_calendar_service()
        clear_future_events(service, GOOGLE_CALENDAR_ID)
        create_pickup_events(service, GOOGLE_CALENDAR_ID, future_dates)

        log.info(f"=== Sync complete. Next pickup: {future_dates[0].isoformat()} ===")
    except Exception:
        log.exception("Sync failed")


def main():
    log.info("Mr. Green Calendar Sync")
    log.info(f"  ZIP: {MR_GREEN_ZIP}")
    log.info(f"  Subscription: {MR_GREEN_SUBSCRIPTION}")
    log.info(f"  Calendar: {GOOGLE_CALENDAR_ID}")
    log.info(f"  Schedule: {SCHEDULE_CRON}")

    if RUN_ON_STARTUP:
        sync()

    day = SCHEDULE_CRON.lower().strip()
    if day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        getattr(schedule.every(), day).at("08:00").do(sync)
        log.info(f"Scheduled: every {day} at 08:00")
    elif day == "daily":
        schedule.every().day.at("08:00").do(sync)
        log.info("Scheduled: daily at 08:00")
    elif ":" in day:
        schedule.every().day.at(day).do(sync)
        log.info(f"Scheduled: daily at {day}")
    else:
        schedule.every().friday.at("08:00").do(sync)
        log.info("Scheduled: every friday at 08:00 (default)")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
