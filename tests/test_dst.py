"""DST behaviour, ported from croner (JS) test/dst-croner-rust.test.ts.

- Fixed-time jobs (single second, minute and hour) run once in a repeated hour, at the first
  occurrence, and run at the end of a DST gap.
- Interval jobs run on both occurrences in a repeated hour, and skip times in a DST gap.
- Searches move in real time, so they never answer with a time they have passed.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from croner import Cron


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(dates):
    return [d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for d in dates]


OVERLAPS = [
    ("Europe/Paris", "2024-10-27T00:30:00Z", "2024-10-27T01:30:00Z"),
    ("Australia/Lord_Howe", "2024-04-06T14:40:00Z", "2024-04-06T15:10:00Z"),
    ("Pacific/Chatham", "2024-04-06T13:35:00Z", "2024-04-06T14:35:00Z"),
]


@pytest.mark.parametrize("tz,first,second", OVERLAPS)
def test_search_never_answers_with_a_passed_time(tz, first, second):
    job = Cron("* * * * *", timezone=tz)
    assert job.next_run(utc(second)) > utc(second)
    assert job.previous_runs(1, utc(first))[0] < utc(first)


@pytest.mark.parametrize("tz,first,second", OVERLAPS)
def test_iterators_cover_every_instant_once(tz, first, second):
    job = Cron("* * * * *", timezone=tz)
    forward = job.next_runs(200, utc(first))
    # Aware datetimes sharing a tzinfo subtract as wall clock times, so compare in UTC
    instants = [d.astimezone(timezone.utc) for d in forward]
    for a, b in zip(instants, instants[1:]):
        assert b - a == timedelta(minutes=1)
    backward = job.previous_runs(199, forward[199])
    assert iso(reversed(backward)) == iso(forward[:199])


@pytest.mark.parametrize("tz,first,second", OVERLAPS)
def test_duplicated_minute_comes_round_twice(tz, first, second):
    job = Cron("* * * * *", timezone=tz)
    runs = job.next_runs(201, utc(first) - timedelta(milliseconds=1))
    zone = ZoneInfo(tz)
    wanted = utc(first).astimezone(zone).replace(tzinfo=None)
    assert sum(1 for d in runs if d.astimezone(zone).replace(tzinfo=None) == wanted) == 2


def test_later_overlap_takes_its_real_order():
    job = Cron("*/30 2 26-27 10 *", timezone="Europe/Paris")
    assert iso([job.next_run(utc("2024-10-27T01:45:00Z"))]) == ["2025-10-26T00:00:00Z"]


def test_fixed_time_once_interval_twice():
    start = utc("2025-11-02T04:00:00Z")
    tz = "America/New_York"
    assert iso(Cron("0 30 1 * * *", timezone=tz).next_runs(2, start)) == [
        "2025-11-02T05:30:00Z",
        "2025-11-03T06:30:00Z",
    ]
    assert iso(Cron("0 30 1,2 * * *", timezone=tz).next_runs(3, start)) == [
        "2025-11-02T05:30:00Z",
        "2025-11-02T06:30:00Z",
        "2025-11-02T07:30:00Z",
    ]
    assert iso(Cron("0 */20 * * * *", timezone=tz).next_runs(6, utc("2025-11-02T05:30:00Z"))) == [
        "2025-11-02T05:40:00Z",
        "2025-11-02T06:00:00Z",
        "2025-11-02T06:20:00Z",
        "2025-11-02T06:40:00Z",
        "2025-11-02T07:00:00Z",
        "2025-11-02T07:20:00Z",
    ]


def test_search_inside_repeated_hour_stays_on_its_pass():
    job = Cron("0 */20 * * * *", timezone="America/New_York")
    assert iso([job.next_run(utc("2025-11-02T06:10:00Z"))]) == ["2025-11-02T06:20:00Z"]
    assert iso(job.previous_runs(3, utc("2025-11-02T06:10:00Z"))) == [
        "2025-11-02T06:00:00Z",
        "2025-11-02T05:40:00Z",
        "2025-11-02T05:20:00Z",
    ]
    assert job.ms_to_next("2025-11-02T06:10:00Z") == job.ms_to_next(utc("2025-11-02T06:10:00Z"))


def test_fixed_time_in_gap_runs_at_end_of_gap():
    job = Cron("0 30 2 * * *", timezone="America/New_York")
    assert iso(job.next_runs(2, utc("2025-03-09T05:00:00Z"))) == [
        "2025-03-09T07:00:00Z",
        "2025-03-10T06:30:00Z",
    ]
    assert iso(job.previous_runs(2, utc("2025-03-10T00:00:00Z"))) == [
        "2025-03-09T07:00:00Z",
        "2025-03-08T07:30:00Z",
    ]


def test_interval_job_skips_gap():
    tz = "America/New_York"
    start = utc("2025-03-09T06:30:00Z")
    assert iso(Cron("0 */20 * * * *", timezone=tz).next_runs(4, start)) == [
        "2025-03-09T06:40:00Z",
        "2025-03-09T07:00:00Z",
        "2025-03-09T07:20:00Z",
        "2025-03-09T07:40:00Z",
    ]
    assert iso(Cron("0 30 * * * *", timezone=tz).next_runs(3, start)) == [
        "2025-03-09T07:30:00Z",
        "2025-03-09T08:30:00Z",
        "2025-03-09T09:30:00Z",
    ]


def test_lord_howe_cadence():
    job = Cron("0 */20 * * * *", timezone="Australia/Lord_Howe")
    assert iso([job.next_run(utc("2026-04-04T14:40:00Z"))]) == ["2026-04-04T15:10:00Z"]


@pytest.mark.parametrize(
    "tz,reference,expected",
    [
        ("America/New_York", "2026-11-01T05:30:00Z", "2026-11-01T05:29:59Z"),
        ("America/New_York", "2026-11-01T06:30:00Z", "2026-11-01T06:29:59Z"),
        ("Europe/Stockholm", "2026-10-25T00:30:00Z", "2026-10-25T00:29:59Z"),
        ("Europe/Stockholm", "2026-10-25T01:30:00Z", "2026-10-25T01:29:59Z"),
    ],
)
def test_previous_runs_in_repeated_hour(tz, reference, expected):
    job = Cron("* * * * * *", timezone=tz)
    assert iso(job.previous_runs(1, utc(reference))) == [expected]


def test_previous_then_next_in_same_pass():
    job = Cron("0 * * * * *", timezone="America/New_York")
    previous = job.previous_runs(1, utc("2026-11-01T06:29:50Z"))[0]
    assert iso([previous]) == ["2026-11-01T06:29:00Z"]
    assert iso([job.next_run(previous)]) == ["2026-11-01T06:30:00Z"]


def test_naive_reference_is_read_in_job_timezone():
    job = Cron("0 0 12 * * *", timezone="Asia/Tokyo")
    nxt = job.next_run(datetime(2024, 1, 1, 0, 0))
    assert nxt == datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert nxt.tzinfo == ZoneInfo("Asia/Tokyo")


def test_utc_offset():
    job = Cron("0 0 12 * * *", utc_offset=-300)
    nxt = job.next_run("2024-01-01T00:00:00Z")
    assert iso([nxt]) == ["2024-01-01T17:00:00Z"]
    assert nxt.utcoffset() == timedelta(minutes=-300)
