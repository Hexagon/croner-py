# croner-py - Agent Guide

## Project Overview

croner-py is the Python flavor of [croner](https://github.com/hexagon/croner) (JavaScript/TypeScript) and
[croner-rust](https://github.com/hexagon/croner-rust), published on PyPI as `croner`. It parses and
evaluates cron patterns and schedules functions.

The three libraries should parse the same patterns and schedule the same runs. When in doubt, croner (JS)
is the reference for behavior and options, translated to snake_case.

## Philosophy

- **No runtime dependencies.** Only the Python standard library (`zoneinfo`, `datetime`, `threading`).
  `tzdata` is an optional extra for Windows only.
- Keep it small and simple. Prefer plain functions and the standard library over abstractions.
- Python 3.9+.

## Project Structure

```
src/croner/
├── __init__.py    # Public API and __version__ (single source of the version)
├── _pattern.py    # CronPattern: pattern parser
├── _cron.py       # Cron, CronIterator: search, DST handling, scheduling
├── _zone.py       # Time zone resolution (zoneinfo, fixed offset, system local)
├── _describe.py   # Human readable descriptions (English)
└── _errors.py     # CronError
tests/             # pytest
tools/             # compare_with_js.py: differential test against croner (JS)
```

## Standards Compliance

Follows the **OCPS (Open Cron Pattern Standard)** 1.0 final and drafts 1.1-1.4
([github.com/open-source-cron/ocps](https://github.com/open-source-cron/ocps)).

Deliberate deviation: DST handling follows Vixie cron, croner (JS) and croner-rust rather than OCPS 1.4
§4.3.1 (fixed-time jobs in a DST gap run at the first valid time after it, interval jobs run on both
occurrences of a repeated time). Keep this behavior unless explicitly asked to change it.

## Development

```bash
pip install -e . pytest
python -m pytest
```

Also run the tests with a non-UTC system time zone, as CI does: `TZ=America/New_York python -m pytest`.

After changing search or parsing logic, compare with croner (JS), with a croner checkout next to this
repository and Node.js >= 22.6:

```bash
python tools/compare_with_js.py 1 1000
```

## Versioning

The version lives only in `src/croner/__init__.py` (`__version__`). Add an entry to `CHANGELOG.md` when
bumping it. Publishing to PyPI happens from `.github/workflows/publish.yml` when a GitHub release is published.

## Key Points

- Add tests for all changes.
- No new runtime dependencies.
- Update README.md when changing the public API.
