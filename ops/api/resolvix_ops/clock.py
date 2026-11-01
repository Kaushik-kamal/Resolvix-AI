"""Injectable clock. Routes use request.app.state.clock so tests can freeze the Asia/Kolkata date."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


class Clock:
    def __init__(self, tz_name: str = "Asia/Kolkata"):
        self._tz = ZoneInfo(tz_name)

    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        return datetime.now(timezone.utc)

    def today_ist(self) -> date:
        """Today's date in the college timezone (settings.timezone, Asia/Kolkata by default)."""
        return self.now().astimezone(self._tz).date()


class FrozenClock(Clock):
    def __init__(self, now: datetime, tz_name: str = "Asia/Kolkata"):
        super().__init__(tz_name)
        self._now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now
