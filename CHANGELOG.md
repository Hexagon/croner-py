# Changelog

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
