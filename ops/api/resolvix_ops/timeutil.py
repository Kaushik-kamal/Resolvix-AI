"""UTC time helpers.

SQLite stores naive datetimes; everything stored is UTC. Inputs with an offset are converted
to UTC on the way in, and every datetime leaves the API as ISO-8601 with an explicit offset.
"""
from datetime import datetime, timezone


def now_utc() -> datetime:
    """Current UTC time as a naive datetime (the storage convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    """Convert an aware datetime to naive UTC; naive input is assumed to be UTC already."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def iso_utc(dt: datetime | None) -> str | None:
    """ISO-8601 string with +00:00 offset for a stored (naive UTC) datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
