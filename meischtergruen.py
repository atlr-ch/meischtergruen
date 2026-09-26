import os
import sys
import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import caldav
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
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/credentials/service-account.json")
EVENT_TITLE = os.environ.get("EVENT_TITLE", "Mr. Green Pickup")
EVENT_LOCATION = os.environ.get("EVENT_LOCATION", "")
EVENT_DESCRIPTION = os.environ.get("EVENT_DESCRIPTION", "")
SCHEDULE_CRON = os.environ.get("SCHEDULE_CRON", "friday")
RUN_ON_STARTUP = os.environ.get("RUN_ON_STARTUP", "true").lower() == "true"
# CalDAV (e.g. Nextcloud): full URL of a dedicated calendar
CALDAV_URL = os.environ.get("CALDAV_URL", "")
CALDAV_USERNAME = os.environ.get("CALDAV_USERNAME", "")
CALDAV_PASSWORD = os.environ.get("CALDAV_PASSWORD", "")

if not GOOGLE_CALENDAR_ID and not CALDAV_URL:
    sys.exit("Set GOOGLE_CALENDAR_ID and/or CALDAV_URL")

# Plan names → API type codes, as used by mr-green.ch/pages/abholtermine
SUBSCRIPTION_MAP = {
    "Home Light": "monthly",
    "Home Smart": "monthly",
    "Home Basic": "biweekly",
    "Home Plus": "biweekly",
    "Pinkbag": "monthly",
    "Office Light": "monthly",
    "Office Basic": "biweekly",
    "Office Medium": "biweekly",
    "Office Plus": "weekly",
}

GERMAN_MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Juli": 7, "August": 8,
    "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

# Mr. Green shut down api.mr-green.ch (July 2026); this is the endpoint the
# Shopify site's Abholtermine page calls.
MR_GREEN_API_URL = "https://api-service.mr-green.ch/api/system/pickup-dates"


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

    # The site sends zip/type both as query params and form body; mirror that.
    response = requests.post(
        MR_GREEN_API_URL,
        params={"zip": zip_code, "type": api_type},
        data={"zip": zip_code, "type": api_type},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        raise ValueError(f"API returned success=false: {data.get('message', 'unknown error')}")

    dates_data = data.get("data", [])
    if not dates_data:
        raise ValueError("API returned empty data")

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


def get_caldav_calendar():
    """Connect to the CalDAV calendar at CALDAV_URL."""
    client = caldav.DAVClient(url=CALDAV_URL, username=CALDAV_USERNAME, password=CALDAV_PASSWORD)
    return client.calendar(url=CALDAV_URL)


def clear_future_caldav_events(calendar):
    """Delete all future events from the CalDAV calendar."""
    today = date.today()
    start = datetime(today.year, today.month, today.day)
    events = calendar.search(start=start, end=start + timedelta(days=5 * 365), event=True)
    for event in events:
        event.delete()
    log.info(f"Deleted {len(events)} future CalDAV events")


def ical_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def create_caldav_events(calendar, dates: list[date]):
    """Create all-day events for each pickup date, mirroring the Google ones."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for d in dates:
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//meischtergruen//EN",
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{ical_escape(EVENT_TITLE)}",
            "TRANSP:TRANSPARENT",
        ]
        if EVENT_LOCATION:
            lines.append(f"LOCATION:{ical_escape(EVENT_LOCATION)}")
        if EVENT_DESCRIPTION:
            lines.append(f"DESCRIPTION:{ical_escape(EVENT_DESCRIPTION)}")
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{ical_escape(EVENT_TITLE)}",
            "TRIGGER:-PT6H",
            "END:VALARM",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        calendar.save_event("\r\n".join(lines))

    log.info(f"Created {len(dates)} CalDAV pickup events")


def sync_google(dates: list[date]):
    service = get_calendar_service()
    clear_future_events(service, GOOGLE_CALENDAR_ID)
    create_pickup_events(service, GOOGLE_CALENDAR_ID, dates)


def sync_caldav(dates: list[date]):
    calendar = get_caldav_calendar()
    clear_future_caldav_events(calendar)
    create_caldav_events(calendar, dates)


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

    except Exception:
        log.exception("Sync failed")
        return

    # Each target syncs independently so one failing doesn't block the other
    targets = []
    if GOOGLE_CALENDAR_ID:
        targets.append(("Google", sync_google))
    if CALDAV_URL:
        targets.append(("CalDAV", sync_caldav))
    for name, sync_target in targets:
        try:
            sync_target(future_dates)
        except Exception:
            log.exception(f"{name} sync failed")

    log.info(f"=== Sync complete. Next pickup: {future_dates[0].isoformat()} ===")


def main():
    log.info("Mr. Green Calendar Sync")
    log.info(f"  ZIP: {MR_GREEN_ZIP}")
    log.info(f"  Subscription: {MR_GREEN_SUBSCRIPTION}")
    log.info(f"  Google calendar: {GOOGLE_CALENDAR_ID or '(disabled)'}")
    log.info(f"  CalDAV calendar: {CALDAV_URL or '(disabled)'}")
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
