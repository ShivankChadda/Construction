"""Single source of 'now' so tests can freeze time."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_tz = ZoneInfo("Asia/Kolkata")
_frozen: datetime | None = None


def set_timezone(name: str) -> None:
    global _tz
    _tz = ZoneInfo(name)


def tz() -> ZoneInfo:
    return _tz


def now() -> datetime:
    return _frozen if _frozen is not None else datetime.now(_tz)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def freeze(dt: datetime | None) -> None:
    """Freeze the clock (tests). Pass None to unfreeze."""
    global _frozen
    _frozen = dt


def parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def fmt(iso: str | None, with_time: bool = True) -> str:
    if not iso:
        return "-"
    dt = parse(iso).astimezone(_tz)
    return dt.strftime("%d %b %Y, %I:%M %p") if with_time else dt.strftime("%d %b %Y")
