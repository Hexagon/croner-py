"""Time zone handling.

Croner searches on the wall clock (naive ``datetime`` objects) and resolves
wall clock times to instants (aware UTC ``datetime`` objects) through a
:class:`Zone`. Three kinds are supported:

* an IANA time zone (``zoneinfo.ZoneInfo``), from the ``timezone`` option
* a fixed UTC offset in minutes, from the ``utc_offset`` option
* the system local time zone, when neither is given
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Optional, Union

from ._errors import CronError

UTC = timezone.utc
_FRACTION = re.compile(r"[.,](\d+)")
_ONE_SECOND = timedelta(seconds=1)


class Zone:
    """Converts between instants and wall clock times in one time zone."""

    def __init__(self, tz: Union[str, int, tzinfo, None] = None) -> None:
        self.offset: Optional[int] = None
        self.tzinfo: Optional[tzinfo] = None
        self.name: Union[str, int, None] = None
        if tz is None:
            return
        if isinstance(tz, bool):
            raise CronError("timezone must be a str or a tzinfo, not a bool")
        if isinstance(tz, int):
            self.offset = tz
            self.name = tz
            self.tzinfo = timezone(timedelta(minutes=tz))
        elif isinstance(tz, str):
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                self.tzinfo = ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError) as e:
                raise CronError(f"unknown time zone {tz!r}: {e}") from None
            self.name = tz
        elif isinstance(tz, tzinfo):
            zone = getattr(tz, "zone", None)
            if isinstance(zone, str) and hasattr(tz, "localize"):
                # A pytz zone gives wrong offsets unless used through localize(),
                # use the same zone from zoneinfo instead
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

                try:
                    tz = ZoneInfo(zone)
                except (ZoneInfoNotFoundError, ValueError) as e:
                    raise CronError(f"unknown time zone {zone!r}: {e}") from None
            self.tzinfo = tz
            self.name = getattr(tz, "key", None) or str(tz)
        else:
            raise CronError(f"timezone must be a str or a tzinfo, got {tz!r}")

    @property
    def is_fixed(self) -> bool:
        """True if the zone has no DST (a fixed UTC offset)."""
        return self.offset is not None or isinstance(self.tzinfo, timezone)

    # ----------------------------------------------------------- conversions

    def wall(self, instant: datetime) -> datetime:
        """The wall clock time (naive) of an instant."""
        if self.tzinfo is None:
            return instant.astimezone().replace(tzinfo=None)
        return instant.astimezone(self.tzinfo).replace(tzinfo=None)

    def aware(self, instant: datetime) -> datetime:
        """An instant expressed in this zone, for output."""
        if self.tzinfo is None:
            return instant.astimezone()
        return instant.astimezone(self.tzinfo)

    def _at(self, wall: datetime, fold: int) -> datetime:
        if self.tzinfo is None:
            return wall.replace(fold=fold).astimezone(UTC)
        return wall.replace(tzinfo=self.tzinfo, fold=fold).astimezone(UTC)

    def resolve(self, wall: datetime) -> list[datetime]:
        """The instants a wall clock time refers to.

        One instant normally, two (earlier first) when the clock goes back and the
        time occurs twice, and none when the clock jumps forward past it.
        """
        if self.offset is not None:
            return [(wall - timedelta(minutes=self.offset)).replace(tzinfo=UTC)]
        first = self._at(wall, 0)
        second = self._at(wall, 1)
        if first == second:
            return [first]
        if first < second:
            return [first, second]
        return []

    def to_instant(self, wall: datetime) -> datetime:
        """The instant of a wall clock time, honouring ``wall.fold`` for repeated times.

        A time in a gap is read with the offset from before the gap, as Python does.
        """
        if self.offset is not None:
            return (wall - timedelta(minutes=self.offset)).replace(tzinfo=UTC)
        return self._at(wall, wall.fold)

    def utcoffset(self, instant: datetime) -> timedelta:
        return self.aware(instant).utcoffset() or timedelta(0)

    # ------------------------------------------------------------------- DST

    def fold_of(self, instant: datetime) -> Optional[str]:
        """``"earlier"`` or ``"later"`` if the wall clock time of an instant occurs twice."""
        if self.is_fixed:
            return None
        resolved = self.resolve(self.wall(instant).replace(microsecond=0))
        if len(resolved) != 2:
            return None
        return "earlier" if instant < resolved[1] else "later"

    def find_offset_change(self, start: datetime, end: datetime) -> datetime:
        """The first whole second in ``(start, end]`` with another UTC offset than ``start``."""
        start_offset = self.utcoffset(start)
        while end - start > _ONE_SECOND:
            middle = start + timedelta(seconds=int((end - start).total_seconds() // 2))
            if self.utcoffset(middle) == start_offset:
                start = middle
            else:
                end = middle
        return end


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 date or date-time string.

    Strings ending in ``Z`` are UTC. Returns a naive datetime for strings without
    an offset, and an aware one otherwise.
    """
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # Python < 3.11 only reads 3 or 6 digit fractions
    text = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.combine(date.fromisoformat(text), datetime.min.time())
    except ValueError:
        raise CronError(f"invalid ISO 8601 date string {value!r}") from None
