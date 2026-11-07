# croner-py 2.0 plan

1.1 added Pythonic alternatives next to the APIs inherited from the JavaScript implementation. 2.0
removes the inherited ones and the things that can't change without breaking callers. Behavior,
meaning which runs a pattern schedules, does not change.

Order of work:

1. **1.2**: emit `DeprecationWarning` for everything removed in 2.0 that has a replacement, so users
   see what to change while their code still works.
2. **2.0**: the removals and breaking changes below, in one release.
3. Scheduler and asyncio work can land in any 1.x release, it does not depend on 2.0.

## Python 3.10+

Drop Python 3.9 (end of life since October 2025).

- `requires-python = ">=3.10"`, remove 3.9 from the classifiers and the CI matrix.
- Use `X | None` and `X | Y` in annotations and type aliases. Remove `keep-runtime-typing` from the ruff
  configuration and let `ruff check --fix` rewrite `Optional` / `Union`.
- `parse_iso()` can drop the fraction padding for Python < 3.11 only once 3.10 is dropped too, so that
  stays.

## Removals (deprecated in 1.2)

| Inherited API                    | Replacement               | Note |
|----------------------------------|---------------------------|------|
| `ms_to_next()`                   | `time_to_next()`          | Returns a `timedelta`. |
| `get_once()`                     | `once`                    | Property. |
| `unref=`, `job.unref`            | `daemon=`, `job.daemon`   | `unref` is a Node.js term. |
| `legacy_mode=`                   | `dom_and_dow=`            | Deprecated since 1.0.0 already. |
| `kill=`                          | none                      | Undocumented, from the JavaScript internals. Create the job and call `stop()`. |
| `max_runs=float("inf")`          | `max_runs=None`           | JavaScript `Infinity`. |

## Breaking changes without a deprecation path

These change a type or a return value, so 1.2 can only document them.

- **`scheduled_jobs` becomes a read-only `Mapping[str, Cron]`** (a `types.MappingProxyType` over a
  dict) instead of a list that is searched by name. `scheduled_jobs["backup"]` and
  `"backup" in scheduled_jobs` then work, and a lookup no longer walks every job.
- **`pause()` and `resume()` return `None`.** Today they return whether the job is stopped, which
  `is_stopped()` already tells.
- **`get_pattern()`**: `job.pattern` is the parsed `CronPattern`, and `str(job.pattern)` the original
  text. For one-off jobs `job.pattern` is a placeholder `* * * * *` today. In 2.0 it becomes `None`
  for one-off jobs, and `get_pattern()` is removed.
- **Parameter names**: `next_runs(n, start)` and `previous_runs(n, reference)` name the same thing
  differently. Use `start` in both. 1.2 can accept `reference` as a keyword with a warning, so only
  the removal breaks.

## Kept as they are

- `current_run()`, `previous_run()`, `runs_left()`, `is_running()`, `is_stopped()`, `is_busy()` stay
  methods. They read state that changes from other threads, like `threading.Thread.is_alive()`, and
  turning them into properties can't be done without breaking every caller at once.
- The `context` option. `functools.partial` or a closure does the same, but it costs nothing to keep and
  matches the other implementations.
- `mode` strings (`"5-part"`, ...) and the `CronPattern` lookup tables.

## Scheduler (any 1.x)

Today every job keeps a `threading.Timer` alive and replaces it at least every 30 seconds, and every run
starts a new thread. With many jobs that is many threads.

- One scheduler thread per process, with a heap of `(next run, job)`, woken by a `threading.Condition`
  when a job is added, paused, resumed or stopped. Still capped at 30 seconds of sleep, to survive
  suspend and clock steps.
- Runs keep starting in threads of their own, so a slow run does not delay others. Optionally a
  bounded `concurrent.futures.ThreadPoolExecutor`, passed as an option.
- The scheduler thread is a daemon thread. Non-daemon jobs keep the process alive through a
  non-daemon helper thread that exits when the last non-daemon job stops, so `daemon` keeps its
  meaning.
- Uncaught errors from a function, without `catch`, go to the `croner` logger
  (`logging.getLogger("croner")`) instead of only `threading.excepthook`.

## asyncio (any 1.x)

Coroutine functions run with `asyncio.run()` in a worker thread, in an event loop of their own. They
can't share objects bound to the application's loop.

- `async for run in job.aiter()`: waits for each run with `asyncio.sleep()`, in the caller's loop.
  Covers most asyncio use without a scheduler thread.
- A job created while an event loop is running, with a coroutine function, schedules each run with
  `loop.call_soon_threadsafe()` on that loop instead of `asyncio.run()` in a thread. Opt in with an
  option (for example `loop=`) first, and make it the default in 2.0 if it works out.

## Release checklist

- [ ] 1.2: deprecation warnings, tests that they are emitted, CHANGELOG, README marks the old names.
- [ ] 2.0: removals, `scheduled_jobs` mapping, `pause()` / `resume()` return values, one-off
      `job.pattern`, Python 3.10+.
- [ ] Migration section in the CHANGELOG, with the table above.
- [ ] `python tools/compare_with_js.py 1 1000` agrees, as before.
