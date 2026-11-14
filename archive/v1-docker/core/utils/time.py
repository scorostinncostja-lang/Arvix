from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Moscow")


def now_local() -> datetime:
    return datetime.now(UTC).astimezone(LOCAL_TZ)


def today_local() -> date:
    return now_local().date()
