"""The Cron class: pattern evaluation and scheduling."""

from __future__ import annotations

import asyncio
import calendar
import inspect
import threading
import warnings
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

from ._errors import CronError
from ._pattern import LAST_OCCURRENCE, MODES, OCCURRENCE_BITMASKS, CronPattern
from ._zone import UTC, Zone, parse_iso

__all__ = ["Cron", "CronIterator", "scheduled_jobs"]

DateLike = Union[datetime, date, str]

_ONE_SECOND = timedelta(seconds=1)
_ONE_MICROSECOND = timedelta(microseconds=1)
_ONE_DAY = timedelta(days=1)
_MAX_DELAY = 30.0  # never sleep longer than this, to survive suspend and clock steps
_SEARCH_YEARS = 400  # without a year field, the calendar repeats every 400 years

#: All named jobs. A job is added when created with a ``name``, and removed by ``stop()``.
scheduled_jobs: List["Cron"] = []
_registry_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _weekday(year: int, month: int, day: int) -> int:
    """0 = Sunday ... 6 = Saturday"""
    return (date(year, month, day).weekday() + 1) % 7


class Cron:
    """A cron job, or a cron pattern to evaluate.

    :param pattern: A cron pattern (``"0 */5 * * * *"``), or a ``datetime`` /
        ISO 8601 string to run once.
    :param fn: Optional function to schedule. Called as ``fn(job, context)``;
        functions taking fewer arguments get fewer. Coroutine functions are run
        to completion in the worker thread.

    Keyword options mirror croner (JavaScript), in snake_case:

    :param name: Register the job in :data:`scheduled_jobs` under this name.
    :param paused: Start paused.
    :param kill: Start stopped.
    :param catch: ``True`` to ignore errors from ``fn``, or a callable ``catch(error, job)``.
    :param unref: Run the scheduler in a daemon thread, so it does not keep the process alive.
    :param max_runs: Maximum number of runs.
    :param interval: Minimum number of seconds between runs.
    :param protect: Skip a run while the previous one is still running.
        ``True``, or a callable ``protect(job)`` called for each skipped run.
    :param start_at: Earliest run (inclusive). Naive datetimes and strings are read in the job's time zone.
    :param stop_at: Stop before this time (exclusive).
    :param timezone: IANA time zone name (``"Europe/Stockholm"``) or a ``tzinfo``.
    :param utc_offset: Fixed UTC offset in minutes. Cannot be combined with ``timezone``.
    :param dom_and_dow: Combine day-of-month and day-of-week with AND instead of OR.
    :param legacy_mode: Deprecated inverse of ``dom_and_dow``.
    :param day_offset: Shift every run by a number of days.
    :param mode: Field count mode: ``"auto"``, ``"5-part"``, ``"6-part"``, ``"7-part"``,
        ``"5-or-6-parts"`` or ``"6-or-7-parts"``.
    :param context: Passed as the second argument to ``fn``.
    :param alternative_weekdays: Quartz-style weekdays (1 = Sunday ... 7 = Saturday).
    :param sloppy_ranges: Accept non-standard steps like ``/10`` and ``5/10``.
    :param allow_past: Let a one-off job dated in the past run immediately.

    Times without a time zone (naive datetimes and ISO strings without an offset)
    are read in the job's time zone, or in system local time if none is set.
    Returned datetimes are aware, in the job's time zone.
    """

    def __init__(
        self,
        pattern: Union[str, datetime, date],
        fn: Optional[Callable[..., Any]] = None,
        *,
        name: Optional[str] = None,
        paused: bool = False,
        kill: bool = False,
        catch: Union[bool, Callable[[BaseException, "Cron"], Any]] = False,
        unref: bool = False,
        max_runs: Optional[int] = None,
        interval: int = 0,
        protect: Union[bool, Callable[["Cron"], Any]] = False,
        start_at: Optional[DateLike] = None,
        stop_at: Optional[DateLike] = None,
        timezone: Union[None, str, tzinfo] = None,
        utc_offset: Optional[int] = None,
        dom_and_dow: Optional[bool] = None,
        legacy_mode: Optional[bool] = None,
        day_offset: int = 0,
        mode: str = "auto",
        context: Any = None,
        alternative_weekdays: bool = False,
        sloppy_ranges: bool = False,
        allow_past: bool = False,
    ) -> None:
        if fn is not None and not callable(fn):
            raise CronError("Cron: Invalid argument passed for fn. Should be a callable.")

        # ---- options
        if legacy_mode is not None:
            warnings.warn(
                "Cron: legacy_mode is deprecated, use dom_and_dow instead",
                DeprecationWarning,
                stacklevel=2,
            )
            if dom_and_dow is None:
                dom_and_dow = not legacy_mode
        self.dom_and_dow: bool = bool(dom_and_dow)

        if mode not in MODES:
            raise CronError(
                "CronOptions: mode must be one of 'auto', '5-part', '6-part', '7-part', "
                "'5-or-6-parts', or '6-or-7-parts'."
            )
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            raise CronError("CronOptions: Supplied value for interval is not a number") from None
        if interval < 0:
            raise CronError("CronOptions: Supplied value for interval can not be negative")
        try:
            day_offset = int(day_offset)
        except (TypeError, ValueError):
            raise CronError(
                "CronOptions: Invalid value passed for dayOffset, should be a number representing days to offset."
            ) from None
        if timezone == "":
            timezone = None
        if utc_offset is not None:
            try:
                utc_offset = int(utc_offset)
            except (TypeError, ValueError):
                raise CronError(
                    "CronOptions: Invalid value passed for utcOffset, should be number representing minutes offset from UTC."
                ) from None
            if not -870 <= utc_offset <= 870:
                raise CronError("CronOptions: utcOffset out of bounds.")
            if timezone is not None:
                raise CronError("CronOptions: Combining 'utcOffset' with 'timezone' is not allowed.")
        if max_runs is not None and max_runs != float("inf"):
            max_runs = int(max_runs)
        elif max_runs == float("inf"):
            max_runs = None
        if not isinstance(unref, bool):
            raise CronError("CronOptions: Unref should be either True or False.")

        self.name: Optional[str] = name
        self.interval: int = interval
        self.day_offset: int = day_offset
        self.mode: str = mode
        self.context: Any = context
        self.catch = catch
        self.protect = protect
        self.unref: bool = unref
        self.allow_past: bool = allow_past
        self.alternative_weekdays: bool = alternative_weekdays
        self.sloppy_ranges: bool = sloppy_ranges
        self.timezone = timezone
        self.utc_offset = utc_offset
        self._zone = Zone(utc_offset if utc_offset is not None else timezone)

        # startAt and stopAt are read in the job's time zone, and runs are on whole seconds
        self._start_at_rounding = timedelta(0)
        self.start_at: Optional[datetime] = None
        self.stop_at: Optional[datetime] = None
        if start_at:
            exact = self._to_instant(start_at)
            self.start_at = self._to_whole_second(exact)
            self._start_at_rounding = self.start_at - exact
        if stop_at:
            self.stop_at = self._to_whole_second(self._to_instant(stop_at))

        # ---- state
        self._lock = threading.RLock()
        self._kill = bool(kill)
        self._blocking = False
        self._previous_run: Optional[datetime] = None
        self._current_run: Optional[datetime] = None
        self._max_runs: Optional[int] = max_runs
        self._paused = bool(paused)
        self._timer: Optional[threading.Timer] = None
        self._once: Optional[datetime] = None
        self.fn: Optional[Callable[..., Any]] = None

        if isinstance(pattern, (datetime, date)) or (
            isinstance(pattern, str) and pattern.find(":") > 0
        ):
            self._once = self._to_instant(pattern)
            self.pattern = CronPattern("* * * * *")
        else:
            self.pattern = CronPattern(
                pattern,
                mode=mode,
                alternative_weekdays=alternative_weekdays,
                sloppy_ranges=sloppy_ranges,
            )
        p = self.pattern
        self._nearest_days = [i + 1 for i, v in enumerate(p.nearest_weekdays) if v]

        if self.name:
            with _registry_lock:
                if any(j.name == self.name for j in scheduled_jobs):
                    raise CronError(
                        f"Cron: Tried to initialize new named job '{self.name}', but name already taken."
                    )
                scheduled_jobs.append(self)

        if fn is not None:
            self.fn = fn
            self.schedule()

    # ================================================================ public API

    def next_run(self, start: Optional[DateLike] = None) -> Optional[datetime]:
        """The next run after ``start`` (default: now), or ``None``."""
        return self._output(self._next_target(start, _now()))

    def next_runs(self, n: int, start: Optional[DateLike] = None) -> List[datetime]:
        """The next ``n`` runs after ``start`` (default: the current run, or now)."""
        if self._max_runs is not None and n > self._max_runs:
            n = self._max_runs
        reference = start if start is not None else self._current_run
        return [self._zone.aware(d) for d in self._enumerate(n, reference, 1)]

    def previous_runs(self, n: int, reference: Optional[DateLike] = None) -> List[datetime]:
        """The ``n`` scheduled runs before ``reference`` (default: now), most recent first."""
        return [self._zone.aware(d) for d in self._enumerate(n, reference, -1)]

    def enumerate(self, start: Optional[DateLike] = None) -> "CronIterator":
        """A stateful iterator over runs strictly after ``start`` (default: now)."""
        return CronIterator(self, start)

    def __iter__(self) -> "CronIterator":
        return CronIterator(self)

    def ms_to_next(self, start: Optional[DateLike] = None) -> Optional[int]:
        """Milliseconds from ``start`` (default: now) to the next run, or ``None``."""
        now = _now()
        nxt = self._next_target(start, now)
        if nxt is None:
            return None
        reference = self._to_instant(start) if start is not None else now
        return int((nxt - reference) / timedelta(milliseconds=1))

    def match(self, value: DateLike) -> bool:
        """Whether a date matches the pattern (or the one-off date), to the second."""
        instant = self._to_instant(value).replace(microsecond=0)
        if self._once is not None:
            return instant == self._once.replace(microsecond=0)
        return self._matches_wall(self._zone.wall(instant))

    def describe(self) -> str:
        """A human readable, English, description of the pattern."""
        from ._describe import describe

        return describe(self.pattern, self.dom_and_dow)

    def get_pattern(self) -> Optional[str]:
        """The original pattern, or ``None`` for a one-off job."""
        return None if self._once is not None else self.pattern.pattern

    def get_once(self) -> Optional[datetime]:
        """The date of a one-off job, or ``None``."""
        return self._output(self._once)

    def is_running(self) -> bool:
        """Scheduled, and neither paused nor stopped, with a run ahead."""
        return (
            not self._paused
            and not self._kill
            and self.fn is not None
            and self._next_target(self._current_run, _now()) is not None
        )

    def is_stopped(self) -> bool:
        """Permanently stopped through ``stop()``."""
        return self._kill

    def is_busy(self) -> bool:
        """The scheduled function is currently running."""
        return self._blocking

    def current_run(self) -> Optional[datetime]:
        """Start time of the current, or last, run."""
        return self._output(self._current_run)

    def previous_run(self) -> Optional[datetime]:
        """Start time of the previous run."""
        return self._output(self._previous_run)

    def runs_left(self) -> Optional[int]:
        """Number of runs left, ``None`` for unlimited."""
        return self._max_runs

    def stop(self) -> None:
        """Stop permanently, and remove the job from :data:`scheduled_jobs`."""
        with self._lock:
            self._kill = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        with _registry_lock:
            if self in scheduled_jobs:
                scheduled_jobs.remove(self)

    def pause(self) -> bool:
        """Pause. Returns False if the job is stopped."""
        self._paused = True
        return not self._kill

    def resume(self) -> bool:
        """Resume. Returns False if the job is stopped."""
        self._paused = False
        return not self._kill

    def schedule(self, fn: Optional[Callable[..., Any]] = None) -> "Cron":
        """Schedule ``fn`` (or the function given to the constructor)."""
        with self._lock:
            if fn is not None and self.fn is not None:
                raise CronError(
                    "Cron: It is not allowed to schedule two functions using the same Croner instance."
                )
            if fn is not None:
                if not callable(fn):
                    raise CronError("Cron: fn must be callable.")
                self.fn = fn
            self._schedule()
        return self

    def __call__(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Use the job as a decorator: ``@Cron("* * * * *")``."""
        self.schedule(fn)
        return fn

    def trigger(self) -> None:
        """Run the function now, in the calling thread."""
        now = _now()
        self._begin_run(now)
        self._run(now)

    def __repr__(self) -> str:
        what = self._once.isoformat() if self._once is not None else self.pattern.pattern
        return f"Cron({what!r})"

    # ============================================================ scheduling

    def _schedule(self, now: Optional[datetime] = None) -> None:
        with self._lock:
            if self._kill:
                return
            current = now or _now()
            nxt = self._next_target(None, current)
            if nxt is None:
                return
            wait = (nxt - current).total_seconds()

            # If the clock has stepped back past the current run, search from now
            previous = self._current_run
            if previous is not None and previous > current:
                previous = None
            target = self._next_target(previous, current)
            if target is None:
                return

            wait = min(wait, _MAX_DELAY)
            if wait < 0:
                wait = 1.0 if self._paused else 0.0

            timer = threading.Timer(wait, self._check_trigger, args=(target,))
            timer.daemon = self.unref
            self._timer = timer
            timer.start()

    def _check_trigger(self, target: datetime) -> None:
        with self._lock:
            if self._kill:
                return
            now = _now()
            should_run = not self._paused and now >= target
            blocked = self._blocking and bool(self.protect)
            if should_run and not blocked:
                if self._max_runs is not None:
                    self._max_runs -= 1
                self._begin_run(now)
                worker = threading.Thread(target=self._run, args=(now,), daemon=self.unref)
                worker.start()
            elif should_run and blocked and callable(self.protect):
                threading.Thread(target=self._call_protect, daemon=self.unref).start()
            self._schedule(None if should_run else now)

    def _call_protect(self) -> None:
        self.protect(self)  # type: ignore[operator]

    def _begin_run(self, now: datetime) -> None:
        self._blocking = True
        self._current_run = now

    def _run(self, now: datetime) -> None:
        try:
            if self.catch:
                try:
                    self._call_fn()
                except Exception as e:  # noqa: BLE001
                    if callable(self.catch):
                        try:
                            self.catch(e, self)
                        except Exception:  # noqa: BLE001
                            pass
            else:
                self._call_fn()
        finally:
            self._previous_run = now
            self._blocking = False

    def _call_fn(self) -> None:
        fn = self.fn
        if fn is None:
            return
        result = fn(*_arguments(fn, self, self.context))
        if inspect.isawaitable(result):
            _run_awaitable(result)

    # ================================================================ search

    def _output(self, instant: Optional[datetime]) -> Optional[datetime]:
        return None if instant is None else self._zone.aware(instant)

    def _to_instant(self, value: DateLike) -> datetime:
        """An exact instant (aware, UTC). Naive values are read in the job's time zone."""
        if isinstance(value, str):
            value = parse_iso(value)
        elif isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)
        elif not isinstance(value, datetime):
            raise CronError(f"CronDate: Invalid type ({type(value).__name__}) passed as date")
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value.astimezone(UTC)
        return self._zone.to_instant(value.replace(tzinfo=None))

    @staticmethod
    def _to_whole_second(instant: datetime) -> datetime:
        if instant.microsecond:
            return instant.replace(microsecond=0) + _ONE_SECOND
        return instant

    def _enumerate(self, n: int, reference: Optional[DateLike], direction: int) -> List[datetime]:
        runs: List[datetime] = []
        now = _now()
        current: Optional[DateLike] = reference
        while n > 0:
            n -= 1
            run = (
                self._next_target(current, now)
                if direction == 1
                else self._previous_target(current, now)
            )
            if run is None:
                break
            runs.append(run)
            current = run
        return runs

    def _offset(self) -> timedelta:
        return timedelta(days=self.day_offset)

    def _shift(self, value: Optional[Union[DateLike]]) -> Optional[datetime]:
        if value is None:
            return None
        return self._to_instant(value) - self._offset()

    def _next_target(self, reference: Optional[DateLike], now: datetime) -> Optional[datetime]:
        """The next actual run after ``reference`` (default: ``now``), with day_offset applied."""
        try:
            found = self._next(
                self._shift(reference),
                now - self._offset(),
                self._shift(self.start_at),
                self._shift(self.stop_at),
            )
        except OverflowError:
            return None
        return found + self._offset() if found is not None else None

    def _previous_target(self, reference: Optional[DateLike], now: datetime) -> Optional[datetime]:
        try:
            found = self._previous(
                self._shift(reference if reference is not None else now),
                self._shift(self.start_at),
                self._shift(self.stop_at),
            )
        except OverflowError:
            return None
        return found + self._offset() if found is not None else None

    def _next(
        self,
        previous: Optional[datetime],
        now: datetime,
        start_at: Optional[datetime],
        stop_at: Optional[datetime],
    ) -> Optional[datetime]:
        is_enumerating = previous is not None
        has_previous = previous is not None or self._current_run is not None

        # With start_at and interval and no previous run, find where the last run would have been
        start_in_future_with_interval = False
        if previous is None and start_at is not None and self.interval:
            previous = self._calculate_previous_run(start_at, now)
            if previous is not None:
                has_previous = True
            start_in_future_with_interval = previous is None

        reference = previous if previous is not None else now

        # Never search from before start_at
        if start_at is not None and reference < start_at:
            reference = start_at if start_in_future_with_interval else start_at - _ONE_SECOND

        if self._once is not None:
            found: Optional[datetime] = self._once
            once = self._once
            past = reference - once
            if (
                (start_at is not None and once < start_at - self._start_at_rounding)
                or (
                    self._current_run is not None
                    and once + self._offset() <= self._current_run
                )
                or (
                    past >= timedelta(0)
                    if is_enumerating
                    else (past > _ONE_SECOND and not self.allow_past)
                )
            ):
                return None
        elif start_in_future_with_interval:
            found = reference
        else:
            found = self._find_occurrence(reference, 1, has_previous)

        if (
            found is None
            or (self._max_runs is not None and self._max_runs <= 0)
            or self._kill
            or (stop_at is not None and found >= stop_at)
        ):
            return None
        return found

    def _previous(
        self,
        reference: Optional[datetime],
        start_at: Optional[datetime],
        stop_at: Optional[datetime],
    ) -> Optional[datetime]:
        ref = reference if reference is not None else _now()
        if stop_at is not None and ref > stop_at:
            ref = stop_at
        if self._once is not None:
            return self._once if self._once < ref else None
        found = self._find_occurrence(ref, -1)
        if found is None or (start_at is not None and found < start_at):
            return None
        return found

    def _calculate_previous_run(self, start_at: datetime, now: datetime) -> Optional[datetime]:
        """The last run, counted from ``start_at``, that has no successor at or before ``now``.

        Each run is the first match at least ``interval`` after the one before, so the runs
        are walked one by one. On ordinary days (see :meth:`_ordinary_days`), the runs of a
        day only depend on the time of its first run, so the first run of the next day is
        remembered by that time, and whole days are skipped once a time comes round again.
        """
        if start_at > now:
            return None
        step = timedelta(seconds=self.interval)
        skip_days = self.interval < 86400
        zone = self._zone
        next_first: Dict[time, time] = {}  # time of the first run of a day -> of the next day
        first: Optional[datetime] = None  # wall clock time of the first run of the current day
        at_first = False  # ``previous`` is ``first``
        previous = start_at
        while previous + step <= now:
            if at_first and first is not None and skip_days:
                while True:
                    tod = next_first.get(first.time())
                    if tod is None or not self._ordinary_days(first.date()):
                        break
                    wall = datetime.combine(first.date() + _ONE_DAY, tod)
                    instant = zone.to_instant(wall)
                    if instant > now:
                        break
                    previous, first = instant, wall
                if previous + step > now:
                    break
            nxt = self._walk(previous, previous, 1, True)
            if nxt is None:
                break
            wall = zone.wall(nxt)
            if wall.date() != zone.wall(previous).date():
                if (
                    first is not None
                    and skip_days
                    and wall.date() == first.date() + _ONE_DAY
                    and self._ordinary_days(first.date())
                ):
                    next_first[first.time()] = wall.time()
                first = wall
                at_first = True
            else:
                at_first = False
            previous = nxt
        return previous

    def _ordinary_days(self, day: date) -> bool:
        """``day`` and the day after both match the date fields of the pattern, and the
        UTC offset stays the same through both."""
        p = self.pattern
        days = (day, day + _ONE_DAY)
        for d in days:
            if (
                (not p.star_year and not p.year[d.year])
                or not p.month[d.month - 1]
                or not self._day_match(d.year, d.month, d.day)
            ):
                return False
        zone = self._zone
        if zone.is_fixed:
            return True
        midnight = datetime.combine(day, time())
        offset = zone.utcoffset(zone.to_instant(midnight))
        return all(
            zone.utcoffset(zone.to_instant(midnight + timedelta(hours=h))) == offset
            for h in range(3, 49, 3)
        )

    # ---------------------------------------------------- DST aware search

    def _find_occurrence(
        self, reference: datetime, direction: int, has_previous: bool = False
    ) -> Optional[datetime]:
        """The first run after (direction 1) or before (-1) ``reference``.

        When the clock goes back, a range of wall clock times repeats, and one walk
        of the wall clock covers only one pass of it. If the reference is on the pass
        the search meets first, the other pass still lies ahead, so it is walked too,
        and the nearer match wins. Same algorithm as croner (JS) and croner-rust.
        """
        zone = self._zone
        found = self._walk(reference, reference, direction, has_previous)

        if (self.pattern.is_fixed_time and direction == 1) or zone.is_fixed:
            return found
        if zone.fold_of(reference) != ("earlier" if direction == 1 else "later"):
            return found

        ref = reference.replace(microsecond=0)
        if direction == 1:
            edge = zone.find_offset_change(ref, ref + _ONE_DAY)
        else:
            edge = zone.find_offset_change(ref - _ONE_DAY, ref) - _ONE_SECOND

        if found is not None and (edge - found) * direction > timedelta(0):
            return found

        other = self._walk(edge, edge - _ONE_MICROSECOND * direction, direction, False, True)
        if found is None or other is None:
            return found if found is not None else other
        return other if (found - other) * direction > timedelta(0) else found

    def _walk(
        self,
        start: datetime,
        reference: datetime,
        direction: int,
        has_previous: bool,
        inclusive: bool = False,
    ) -> Optional[datetime]:
        """Walk the wall clock from ``start`` to the first match that runs after
        (direction 1) or before (-1) ``reference``."""
        try:
            wall = self._zone.wall(start).replace(microsecond=0)
        except (OverflowError, ValueError, OSError):
            return None

        def step_size(first: bool) -> int:
            if self.interval > 1 and (direction == -1 or (first and has_previous)):
                return self.interval
            return 1

        limit_year = wall.year
        if inclusive and self._matches_wall(wall):
            candidate: Optional[datetime] = wall
        else:
            candidate = self._search(wall, step_size(True) * direction, direction, limit_year)
        while candidate is not None:
            run = self._run_at(candidate, reference, direction)
            if run is not None:
                return run
            candidate = self._search(candidate, step_size(False) * direction, direction, limit_year)
        return None

    def _run_at(self, wall: datetime, reference: datetime, direction: int) -> Optional[datetime]:
        """When a matching wall clock time runs, if that is ahead of ``reference``.

        DST rules, shared with croner (JS) and croner-rust:

        * A time that occurs twice (fall back) runs once, at its first occurrence, for
          fixed-time jobs, and on both occurrences for interval jobs.
        * A time that doesn't exist (spring forward) is skipped by interval jobs, and runs
          when the clock has jumped forward for fixed-time jobs, if that is on the same day.
        """
        zone = self._zone

        def ahead(instant: datetime) -> bool:
            return (instant - reference) * direction > timedelta(0)

        try:
            resolved = zone.resolve(wall)
        except (OverflowError, ValueError, OSError):
            return None
        fixed_time = self.pattern.is_fixed_time

        if len(resolved) == 1:
            return resolved[0] if ahead(resolved[0]) else None
        if len(resolved) == 2:
            earlier, later = resolved
            if fixed_time:
                order = [earlier]
            elif direction == 1:
                order = [earlier, later]
            else:
                order = [later, earlier]
            for instant in order:
                if ahead(instant):
                    return instant
            return None
        if not fixed_time:
            return None
        # In a gap: the instants with the offsets after and before the change surround it
        after_offset = zone._at(wall, 1)
        before_offset = zone._at(wall, 0)
        gap_end = zone.find_offset_change(min(after_offset, before_offset), max(after_offset, before_offset))
        if zone.wall(gap_end).date() == wall.date() and ahead(gap_end):
            return gap_end
        return None

    # -------------------------------------------------- wall clock search

    def _search(self, wall: datetime, step: int, direction: int, start_year: int) -> Optional[datetime]:
        """Step ``step`` seconds from ``wall``, then find the nearest matching wall
        clock time in ``direction``, inclusive."""
        try:
            return self._find_wall(wall + timedelta(seconds=step), direction, start_year)
        except (OverflowError, ValueError):
            return None

    def _find_wall(self, c: datetime, direction: int, start_year: int) -> Optional[datetime]:
        p = self.pattern
        forward = direction == 1
        while True:
            if p.star_year and abs(c.year - start_year) > _SEARCH_YEARS:
                return None

            # Year
            if not p.star_year and not p.year[c.year]:
                years = range(c.year + 1, 10000) if forward else range(c.year - 1, 0, -1)
                year = next((y for y in years if p.year[y]), None)
                if year is None:
                    return None
                c = datetime(year, 1, 1) if forward else datetime(year, 12, 31, 23, 59, 59)

            # Month
            if not p.month[c.month - 1]:
                if forward:
                    first = c.replace(day=1, hour=0, minute=0, second=0)
                    c = first + timedelta(days=_days_in_month(c.year, c.month))
                else:
                    c = c.replace(day=1, hour=23, minute=59, second=59) - _ONE_DAY
                continue

            # Day
            if not self._day_match(c.year, c.month, c.day):
                if forward:
                    c = c.replace(hour=0, minute=0, second=0) + _ONE_DAY
                else:
                    c = c.replace(hour=23, minute=59, second=59) - _ONE_DAY
                continue

            # Hour
            hour = _find(p.hour, c.hour, direction)
            if hour is None:
                if forward:
                    c = c.replace(hour=0, minute=0, second=0) + _ONE_DAY
                else:
                    c = c.replace(hour=23, minute=59, second=59) - _ONE_DAY
                continue
            if hour != c.hour:
                c = c.replace(hour=hour, minute=0, second=0) if forward else c.replace(hour=hour, minute=59, second=59)

            # Minute
            minute = _find(p.minute, c.minute, direction)
            if minute is None:
                if forward:
                    c = c.replace(minute=0, second=0) + timedelta(hours=1)
                else:
                    c = c.replace(minute=59, second=59) - timedelta(hours=1)
                continue
            if minute != c.minute:
                c = c.replace(minute=minute, second=0 if forward else 59)

            # Second
            second = _find(p.second, c.second, direction)
            if second is None:
                if forward:
                    c = c.replace(second=0) + timedelta(minutes=1)
                else:
                    c = c.replace(second=59) - timedelta(minutes=1)
                continue
            return c.replace(second=second)

    def _matches_wall(self, w: datetime) -> bool:
        p = self.pattern
        if not p.star_year and not p.year[w.year]:
            return False
        return bool(
            p.month[w.month - 1]
            and p.hour[w.hour]
            and p.minute[w.minute]
            and p.second[w.second]
            and self._day_match(w.year, w.month, w.day)
        )

    def _day_match(self, year: int, month: int, day: int) -> bool:
        p = self.pattern
        match = bool(p.day[day - 1])
        month_length = 0

        if not match and self._nearest_days:
            month_length = _days_in_month(year, month)
            for pattern_day in self._nearest_days:
                if _nearest_weekday(year, month, pattern_day, month_length) == day:
                    match = True
                    break

        if p.last_weekday or p.last_day_of_month:
            month_length = month_length or _days_in_month(year, month)
            if p.last_weekday and day == _last_weekday(year, month, month_length):
                match = True
            if p.last_day_of_month and day == month_length:
                match = True

        if not p.star_dow:
            bits = p.day_of_week[_weekday(year, month, day)]
            dow_match = False
            if bits:
                occurrence = (day - 1) // 7
                if occurrence < 5 and bits & OCCURRENCE_BITMASKS[occurrence]:
                    dow_match = True
                elif bits & LAST_OCCURRENCE:
                    month_length = month_length or _days_in_month(year, month)
                    dow_match = day + 7 > month_length
            if p.use_and_logic or self.dom_and_dow or p.star_dom:
                match = match and dow_match
            else:
                match = match or dow_match

        return match


def _find(table, value: int, direction: int) -> Optional[int]:
    if direction == 1:
        for i in range(value, len(table)):
            if table[i]:
                return i
    else:
        for i in range(value, -1, -1):
            if table[i]:
                return i
    return None


def _last_weekday(year: int, month: int, month_length: int) -> int:
    weekday = _weekday(year, month, month_length)
    if weekday == 0:
        return month_length - 2
    if weekday == 6:
        return month_length - 1
    return month_length


def _nearest_weekday(year: int, month: int, day: int, month_length: int) -> int:
    """The weekday (Mon-Fri) nearest to ``day``, within the month, or -1."""
    if day > month_length:
        return -1
    weekday = _weekday(year, month, day)
    if weekday == 0:  # Sunday
        return day - 2 if day == month_length else day + 1
    if weekday == 6:  # Saturday
        return day + 2 if day == 1 else day - 1
    return day


def _arguments(fn: Callable[..., Any], job: Cron, context: Any) -> tuple:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return (job, context)
    positional = 0
    for param in params:
        if param.kind == param.VAR_POSITIONAL:
            return (job, context)
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            positional += 1
    return (job, context)[: min(positional, 2)]


def _run_awaitable(awaitable: Any) -> None:
    async def runner() -> Any:
        return await awaitable

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(runner())
        return
    # A loop is already running in this thread, run the coroutine in a thread of its own
    errors: List[BaseException] = []

    def target() -> None:
        try:
            asyncio.run(runner())
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]


class CronIterator(Iterator[datetime]):
    """Stateful iterator over the runs of a :class:`Cron`, strictly after a start date."""

    def __init__(self, cron: Cron, start: Optional[DateLike] = None) -> None:
        self._cron = cron
        runs = cron.runs_left()
        self._initial_max_runs: float = runs if runs is not None else float("inf")
        self._cursor: Optional[DateLike] = None
        self._now: datetime = _now()
        self._done: bool = False
        self._remaining: float = self._initial_max_runs
        self.reset(start)

    def __iter__(self) -> "CronIterator":
        return self

    def __next__(self) -> datetime:
        if self._done or self._remaining <= 0:
            self._done = True
            raise StopIteration
        found = self._cron._next_target(self._cursor, self._now)
        if found is None:
            self._done = True
            raise StopIteration
        self._cursor = found
        self._remaining -= 1
        return self._cron._zone.aware(found)

    def peek(self) -> Optional[datetime]:
        """The next run, without advancing, or ``None``."""
        if self._done or self._remaining <= 0:
            return None
        return self._cron._output(self._cron._next_target(self._cursor, self._now))

    def reset(self, start: Optional[DateLike] = None) -> None:
        """Restart from ``start`` (default: now)."""
        self._cursor = start
        self._now = _now()
        self._done = False
        self._remaining = self._initial_max_runs
