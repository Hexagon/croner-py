# Croner - Cron for Python

Trigger functions or evaluate cron expressions in Python. No dependencies. Most features. Python 3.9+.

This is the Python flavor of [croner](https://github.com/hexagon/croner) (JavaScript/TypeScript) and
[croner-rust](https://github.com/hexagon/croner-rust). All three parse the same patterns and schedule the
same runs, DST included.

*   Schedule functions, or just evaluate patterns: next runs, previous runs, matching.
*   Works in any time zone, or a fixed UTC offset, with well defined DST behavior.
*   Follows the [Open Cron Pattern Standard](https://github.com/open-source-cron/ocps) (OCPS) 1.0 - 1.4,
    with optional seconds and years, `L`, `W`, `#`, `+` and `?`, with a few
    [deviations](#ocps-conformance) shared with croner (JS).
*   Over-run protection, error handling, pausing, max runs, intervals, start and stop dates, day offsets.
*   Human readable descriptions of patterns.
*   No dependencies, only the Python standard library. Fully typed.

Quick examples:

```python
from croner import Cron

# Basic: run a function at the fifth second of every minute
job = Cron("5 * * * * *", lambda: print("This will run every fifth second"))

# Enumeration: what dates do the next 100 sundays occur on?
next_sundays = Cron("0 0 0 * * 7").next_runs(100)

# Days left to a specific date
ms_left = Cron("59 59 23 24 DEC *").ms_to_next()
print(f"{ms_left // 86_400_000} days left to next christmas eve")

# Run a function once, at a specific date and time
job = Cron("2027-01-23T00:00:00", lambda: print("Yay!"), timezone="Asia/Kolkata")

# As a decorator, with over-run protection
@Cron("*/5 * * * * *", protect=True)
def every_five_seconds(job):
    print("Every five seconds, never overlapping. Next run:", job.next_run())

# Describe a pattern
print(Cron("0 12 * * MON-FRI").describe())  # At 12:00, on Monday, Tuesday, Wednesday, Thursday, and Friday.
```

## Installation

```bash
pip install croner
```

On Windows, which has no system time zone database, also install `tzdata` to use the `timezone` option:
`pip install croner[tzdata]`.

## Documentation

### Signature

`Cron` takes a pattern, an optional function, and keyword options:

```python
# - pattern: Cron pattern, datetime (run once), or ISO 8601 string (run once)
# - fn: Optional function to schedule
# - options: Keyword options (optional)
job = Cron("* * * * * *", max_runs=1)

# If the function is omitted, it can be scheduled later
job.schedule(lambda job, context: None)
```

The function is called with the job and `options.context`, `fn(job, context)`. A function that takes fewer
arguments gets fewer: `fn(job)` or `fn()`. Coroutine functions (`async def`) are run to completion.

Each run happens in a thread of its own, so a slow run does not delay the schedule (use `protect` to
prevent overlapping runs). The scheduler keeps the process alive while a job is scheduled, like a
JavaScript timer, unless you pass `unref=True`.

#### Status

```python
job.next_run(start=None)              # The next run (datetime), or None.
job.next_runs(10, start=None)         # The next 10 runs.
job.previous_runs(10, reference=None) # The 10 previous scheduled runs, most recent first.
job.enumerate(start=None)             # A stateful iterator, for loops: for run in job.enumerate(): ...
job.ms_to_next(start=None)            # Milliseconds to the next run, or None.
job.current_run()                     # When the current (or last) run started.
job.previous_run()                    # When the previous run started.
job.runs_left()                       # Runs left, None for unlimited.

job.match(date)                       # Whether a datetime or ISO 8601 string matches the pattern.

job.is_running()                      # Scheduled, and not paused or stopped.
job.is_stopped()                      # Stopped with stop().
job.is_busy()                         # The function is running right now.

job.get_pattern()                     # The original pattern, or None for one-off jobs.
job.get_once()                        # The date of a one-off job, or None.
job.describe()                        # Human readable description of the pattern.
```

#### Control functions

```python
job.trigger()   # Run the function now, in the calling thread.
job.pause()     # Pause.
job.resume()    # Resume.
job.stop()      # Stop permanently. Also removes a named job from scheduled_jobs.
```

#### Dates and time zones

Every method that takes a date accepts a `datetime`, a `date` or an ISO 8601 string.

*   Aware datetimes, and strings with `Z` or an offset, are exact instants.
*   Naive datetimes, dates, and strings without an offset are wall clock times in the job's time zone
    (the `timezone` or `utc_offset` option), or in system local time if neither is set.

Returned datetimes are aware, in the job's time zone (`zoneinfo.ZoneInfo`), so they print in local time
and compare correctly as instants.

> **Note**
> Python subtracts two aware datetimes that share a `tzinfo` as wall clock times, ignoring DST.
> Convert to UTC first, `a.astimezone(timezone.utc) - b.astimezone(timezone.utc)`, to get the real
> time between two runs across a DST change.

#### Options

| Key                  | Default | Type                | Remarks |
|----------------------|---------|---------------------|---------|
| name                 | None    | str                 | Keep a reference to the job in `croner.scheduled_jobs`. The reference is removed on `stop()`. |
| max_runs             | None    | int                 | Maximum number of runs, None for unlimited. |
| catch                | False   | bool \| callable    | Catch errors raised by the function. `True` silently ignores them, a callable is called as `catch(error, job)`. |
| timezone             | None    | str \| tzinfo       | Time zone in Europe/Stockholm format, or a `tzinfo` (`zoneinfo`, `dateutil`, or `pytz`, which is read through `zoneinfo`). |
| utc_offset           | None    | int                 | Schedule with a fixed UTC offset in minutes. This does not take DST into account, you probably want `timezone`. |
| start_at             | None    | datetime \| str     | Earliest run. Inclusive, a run exactly at `start_at` is included (except when `interval` is set). |
| stop_at              | None    | datetime \| str     | Stop before this date. Exclusive, a run exactly at `stop_at` is not included. |
| interval             | 0       | int                 | Minimum number of seconds between runs. |
| paused               | False   | bool                | Start paused. |
| context              | None    | Any                 | Passed as the second argument to the function. |
| dom_and_dow          | False   | bool                | Combine day-of-month and day-of-week with AND (True) or OR (False). |
| legacy_mode          | -       | bool                | **Deprecated:** use `dom_and_dow`. Inverse of `dom_and_dow`. |
| unref                | False   | bool                | Run the scheduler in daemon threads, so the process can exit while the job is scheduled. |
| protect              | False   | bool \| callable    | Over-run protection: skip runs while a previous run is still going. A callable is called as `protect(job)` for each skipped run. |
| alternative_weekdays | False   | bool                | Quartz-style weekday numbering (1 = Sunday, 2 = Monday, ..., 7 = Saturday). |
| allow_past           | False   | bool                | Let a one-off job dated in the past run immediately. Otherwise only one dated within the last second does. |
| day_offset           | 0       | int                 | Shift every run by a number of days, e.g. `-1` for the day before each match. All methods and `start_at` / `stop_at` refer to the shifted time. |
| mode                 | "auto"  | str                 | How many fields the pattern has: `"auto"`, `"5-part"`, `"6-part"`, `"7-part"`, `"5-or-6-parts"` or `"6-or-7-parts"`. |
| sloppy_ranges        | False   | bool                | Accept non-standard steps, like `/10`, `5/5` or `30/30`. By default only `*/step` and `min-max/step` are allowed. |

Invalid patterns and options raise `croner.CronError`, a subclass of `ValueError`.

#### Pattern

Croner uses [Vixie cron](https://en.wikipedia.org/wiki/Cron#CRON_expression) based expressions, with these extensions:

```
┌──────────────── (optional) second (0 - 59)
│ ┌────────────── minute (0 - 59)
│ │ ┌──────────── hour (0 - 23)
│ │ │ ┌────────── day of month (1 - 31)
│ │ │ │ ┌──────── month (1 - 12, JAN-DEC)
│ │ │ │ │ ┌────── day of week (0 - 6, SUN-SAT)
│ │ │ │ │ │       (0 to 6 are Sunday to Saturday; 7 is Sunday, the same as 0)
│ │ │ │ │ │ ┌──── (optional) year (1 - 9999)
│ │ │ │ │ │ │
* * * * * * *
```

*   **Optional second and year fields**: 6 fields add seconds first, 7 fields also add a year last.
*   **L**: Last day of month, or last occurrence of a weekday. `L` in day-of-month is the last day of the
    month, `LW` the last weekday (Mon-Fri) of the month, and `5#L`, `5L` or `FRI#L` the last Friday of the month.
*   **W**: Nearest weekday. `15W` is the weekday closest to the 15th, never crossing into another month.
*   **#**: Nth occurrence of a weekday. `5#2` is the second Friday, `MON#1` the first Monday of the month.
*   **+**: Prefix the day-of-week field to combine it with day-of-month using AND:
    `0 12 1 * +MON` only runs when the 1st is a Monday.
*   **?**: An alias for `*`. Non-portable, avoid it in patterns meant for other systems.
*   **DST**, the same as croner (JS), croner-rust and Vixie cron, deviating from OCPS 1.4 §4.3.1:
    *   **Fixed-time jobs**, with a single value in each of second, minute and hour (e.g. `0 30 2 * * *`):
        a time that occurs twice (fall back) runs once, at the first occurrence. A time that doesn't
        exist (spring forward) runs at the first valid time after the gap, on the same day.
    *   **Interval jobs**, with a wildcard, step, range or list in second, minute or hour
        (e.g. `*/5 * * * *` or `0 30 1,2 * * *`): a time that occurs twice runs on both occurrences.
        A time that doesn't exist is skipped.
    *   `next_run()`, `next_runs()`, `previous_runs()` and `enumerate()` move in real time. They never
        return a time they have passed, and cover the first pass through a repeated hour before the second.

By default, day-of-month and day-of-week are combined with OR: `0 20 1 * MON` runs on the 1st of the month
and on Mondays. Use the `+` modifier or `dom_and_dow=True` for AND.

| Field        | Required | Allowed values  | Special characters | Remarks |
|--------------|----------|-----------------|--------------------|---------|
| Seconds      | Optional | 0-59            | * , - / ?          | Defaults to 0 |
| Minutes      | Yes      | 0-59            | * , - / ?          | |
| Hours        | Yes      | 0-23            | * , - / ?          | |
| Day of Month | Yes      | 1-31            | * , - / ? L W      | L = last day, W = nearest weekday |
| Month        | Yes      | 1-12 or JAN-DEC | * , - / ?          | |
| Day of Week  | Yes      | 0-7 or SUN-SAT  | * , - / ? L # +    | 0 and 7 = Sunday, 1-7 = Sunday-Saturday with `alternative_weekdays` |
| Year         | Optional | 1-9999          | * , - /            | Defaults to *. `*/2` matches even years, see below. |

Weekday and month names are case-insensitive.

**Nicknames**:

| Nickname               | Same as       |
|------------------------|---------------|
| @yearly / @annually    | `0 0 1 1 *`   |
| @monthly               | `0 0 1 * *`   |
| @weekly                | `0 0 * * 0`   (Sundays, also with `alternative_weekdays`) |
| @daily / @midnight     | `0 0 * * *`   |
| @hourly                | `0 * * * *`   |
| @reboot                | Recognized, but raises `CronError`, as croner can't detect system startup. |

#### OCPS conformance

Croner passes the [OCPS conformance tests](https://github.com/open-source-cron/ocps/blob/main/data/conformance-tests.json),
except where it keeps the behavior of croner (JS):

*   **DST**: follows Vixie cron instead of OCPS 1.4 §4.3.1, as described above.
*   **`?`** is accepted in every field, as an alias for `*`. OCPS 1.4 only allows it in day-of-month
    and day-of-week.
*   **Nicknames** are case-insensitive, `@Daily` works. OCPS 1.1 makes them case-sensitive.
*   **`@reboot`** is rejected when the pattern is parsed. OCPS 1.1 accepts it at parse time and lets the
    runtime reject it.
*   **Years**: the supported range is 1-9999, wider than the portable 1970-2199. Wildcard steps in the
    year field count from year 0 (which is never matched itself), so `*/2` matches even years, as OCPS
    requires. Other steps can match other years than counting from 1970 would: `*/4` matches 2024,
    2028, ..., where 1970-2199 gives 2026, 2030, .... Use a range, like `2026-2199/4`, to be portable.

### Pattern objects

`croner.CronPattern` parses a pattern on its own. `job.pattern` is the parsed pattern of a job.

```python
from croner import CronPattern

pattern = CronPattern("0 9-11 * * 1-5")
pattern.values("hour")         # [9, 10, 11]
pattern.values("day_of_week")  # [1, 2, 3, 4, 5]
pattern.is_fixed_time          # False
```

## Development

```bash
pip install -e . pytest
python -m pytest
```

`tools/compare_with_js.py` compares random patterns with croner (JavaScript), run from source with
Node.js, see the script for details.

## Other implementations

Croner is available in several languages. The implementations share pattern syntax, DST rules and test cases:

- **JavaScript / TypeScript**: [croner](https://github.com/Hexagon/croner), Node, Deno, Bun and browsers, on [npm](https://www.npmjs.com/package/croner) and [JSR](https://jsr.io/@hexagon/croner)
- **Rust**: [croner-rust](https://github.com/Hexagon/croner-rust), on [crates.io](https://crates.io/crates/croner)
- **Python**: croner-py (this repository)
- **.NET**: [croner-dotnet](https://github.com/Hexagon/croner-dotnet), on [NuGet](https://www.nuget.org/packages/Croner)
- **C++**: [croner-cpp](https://github.com/Hexagon/croner-cpp), header-only, C++17

## License

MIT License
