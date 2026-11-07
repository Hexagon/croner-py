# Changelog

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
