"""Command line interface: ``python -m croner PATTERN``.

Prints a description of the pattern and its next (or previous) runs.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from . import __version__
from ._cron import Cron
from ._errors import CronError


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m croner",
        description="Describe a cron pattern and list its next runs.",
    )
    parser.add_argument("pattern", help='cron pattern, e.g. "0 9 * * MON-FRI", or an ISO 8601 date')
    parser.add_argument("-n", "--count", type=int, default=5, help="number of runs to list (default: 5)")
    parser.add_argument("-t", "--timezone", help="IANA time zone, e.g. Europe/Stockholm (default: system local)")
    parser.add_argument("-s", "--start", help="list runs after this ISO 8601 date (default: now)")
    parser.add_argument("-p", "--previous", action="store_true", help="list previous runs instead, most recent first")
    parser.add_argument("--version", action="version", version=f"croner {__version__}")
    args = parser.parse_args(argv)

    try:
        job = Cron(args.pattern, timezone=args.timezone)
        if args.previous:
            runs = job.previous_runs(args.count, args.start)
        else:
            runs = job.next_runs(args.count, args.start)
    except CronError as e:
        parser.error(str(e))

    if job.get_pattern() is not None:
        print(job.describe())
    for run in runs:
        print(run.isoformat())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
