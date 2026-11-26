# Changelog

## 1.2.0

Brings croner-py up to date with croner (JS) 11.0.1, plus the fixes on its dev branch since, and croner-rust 5.0.1.

- `fixed_time_rule` option, which decides which jobs are fixed-time jobs in DST handling. The default,
  `"single-value"`, is unchanged. With `"no-wildcard"`, a job without a wildcard (`*` or `?`) or step in
  second, minute and hour is a fixed-time job, so `30 2,14 * * *` runs at the end of a DST gap and once
  in a repeated hour, close to Vixie cron. With `"all"`, every job is a fixed-time job, as in croner 2.x.
  `"single-value"` and `"no-wildcard"` match `fixedTimeRule` in croner (JS), and all three match
  `FixedTimeRule` in croner-rust. Also a `CronPattern` argument.
- The `interval` option counts elapsed time, so a DST change in between no longer shortens or stretches
  it. Before, the interval was added to the wall clock: after a spring forward the next run could come
  minutes after the last one, in a repeated hour the interval was ignored, and a 24 hour interval gave 23
  or 25 hours. As in croner (JS) 11.0.1.
- `previous_runs()` includes a run earlier in the same second as a reference with a fraction of a second,
  so `* * * * * *` from `00:00:05.500` returns `00:00:05` first. With `interval`, also of one second, that
  run is too close to the reference and is not returned.
- A month or day name has to stand alone. It was replaced by its number wherever it was, so `SUN6` meant
  `6`, `JANFEB` meant `12` and `*/FRI` meant `*/5`. These patterns raise `CronError` now.
- `SUN-SUN` matches Sundays only. It was read as `0-7` and matched every day.
- With `alternative_weekdays=True`, day-of-week `8` raises `CronError`. It was read as Sunday. Quartz
  weekdays are 1-7.
- `L` and `LW` in day-of-month have to be values of their own. An `L` anywhere else in the field was
  dropped, so `5L` meant the 5th and the last day; it raises `CronError` now.
- `LW` can be in a day-of-month list, as in croner-rust: `L,LW` is the last day and the last weekday,
  `1W,15W,LW` three days a month. It raised `CronError`.
- With `alternative_weekdays=True`, a day-of-week range whose end is before its start wraps around the
  week, as in Quartz and croner-rust: `SAT-SUN` is Saturday and Sunday, `FRI-MON` Friday to Monday, and
  `FRI-TUE/2` Friday, Sunday and Tuesday. These raised `CronError`, since Sunday is 1 in that mode.
- A fixed-time job in a DST gap runs at the end of the gap if that date matches the day, month and year
  fields, as in croner-rust. Before, it had to be the same day, so a gap that ends at midnight dropped the
  run: `30 23 * * *` in `America/Nuuk` had no run on 2024-03-30, and `0 12 * * *` in `Pacific/Apia` none
  for the day Samoa skipped in 2011. They now run at 00:00 the next day.
- An nth weekday with more than one `#` or nothing after it (`5##2`, `5#`) raises an error that says so.
- `describe()` calls a stepped field "every N" only when it holds the values of `*/N`, as in croner-rust.
  `0-10/2 * * * *` was "At every 2 minutes.", and `*/15,7 * * * *` dropped the 7. In the month field,
  `0 0 * 6-12/2 *` is now "in June, August, October, and December".
- `tools/compare_with_js.py` also covers `interval` across DST changes, `fixed_time_rule`,
  `alternative_weekdays` and the patterns above. It reports separately where croner-py follows
  croner-rust instead of croner (JS).

## 1.1.0

More Pythonic APIs. Everything from 1.0 keeps working.

- The decorator returns the job instead of the function, so `@Cron(...)` gives a name to pause, stop
  and query the job by. Calling the job calls the function, and it carries the function's `__name__`,
  `__doc__` and `__wrapped__`.
- `time_to_next()` returns the time to the next run as a `timedelta`. `ms_to_next()` remains.
- `once` property, the same as `get_once()`.
- `daemon` option, an alias of `unref`, and a `daemon` attribute.
- `interval` and `utc_offset` accept a `timedelta`. Values that are not whole seconds (or minutes)
  raise `CronError` instead of being truncated.
- `datetime.timezone` fixed offsets passed as `timezone` skip the DST checks.
- `CronPattern` objects compare equal when they match the same times: `CronPattern("@daily") ==
  CronPattern("0 0 * * *")`. They are hashable.
- `python -m croner PATTERN` describes a pattern and lists its next or previous runs.
- Error messages name the Python options (`utc_offset`, `day_offset`, `day_of_week`), without the
  `CronOptions:` / `CronPattern:` / `CronDate:` prefixes.
- Passes `mypy --strict`. Linting with ruff and type checking with mypy run in CI.

## 1.0.1

- Fixed `pytz` time zones passed as `timezone`. They were used without `localize()`, which gives
  local mean time, so `0 12 * * *` in `pytz.timezone("Europe/Stockholm")` ran at 13:07. They are now
  read through `zoneinfo`.
- Fixed `@weekly` with `alternative_weekdays=True` raising `CronError`. It runs on Sundays, like
  croner-rust.
- `interval` with a `start_at` far in the past is much faster: the runs since `start_at` are no longer
  walked one by one on days without a DST change. A year of runs every other second took about a
  minute and a half, now under two seconds. The runs are the same.
- Documented the deviations from OCPS, and how wildcard steps in the year field count.

## 1.0.0

First release. A Python port of [croner](https://github.com/hexagon/croner) (JavaScript) and
[croner-rust](https://github.com/hexagon/croner-rust).

- Parse and evaluate cron patterns following OCPS 1.0 - 1.4: optional seconds and years, `L`, `LW`, `W`,
  `#`, `+`, `?`, month and weekday names, nicknames, Quartz-style weekdays, field count modes and
  sloppy ranges.
- `next_run()`, `next_runs()`, `previous_runs()`, `enumerate()`, `ms_to_next()` and `match()`, in any
  IANA time zone, a fixed UTC offset or system local time, with the same DST handling as croner (JS)
  and croner-rust.
- Scheduling in threads, with `max_runs`, `interval`, `start_at`, `stop_at`, `day_offset`, `protect`,
  `catch`, `context`, `paused`, `unref`, one-off dates, named jobs and coroutine functions.
- `describe()` for human readable descriptions.
- No dependencies.
