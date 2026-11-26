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


# fixed_time_rule, checked against croner-rust (FixedTimeRule) and croner (JS) (fixedTimeRule)


def test_no_wildcard_list_runs_once_in_repeated_hour():
    job = Cron("30 1,13 * * *", timezone="Europe/Stockholm", fixed_time_rule="no-wildcard")
    # 02:30 local happens twice on 2024-10-27, but 01:30 and 13:30 only once; 1:30 is before it
    assert iso(job.next_runs(4, "2024-10-26T20:00:00Z")) == [
        "2024-10-26T23:30:00Z",
        "2024-10-27T12:30:00Z",
        "2024-10-28T00:30:00Z",
        "2024-10-28T12:30:00Z",
    ]
    job = Cron("30 2,14 * * *", timezone="Europe/Stockholm", fixed_time_rule="no-wildcard")
    assert iso(job.next_runs(3, "2024-10-26T20:00:00Z")) == [
        "2024-10-27T00:30:00Z",  # once, on the first pass
        "2024-10-27T13:30:00Z",
        "2024-10-28T01:30:00Z",
    ]
    default = Cron("30 2,14 * * *", timezone="Europe/Stockholm")
    assert iso(default.next_runs(3, "2024-10-26T20:00:00Z")) == [
        "2024-10-27T00:30:00Z",
        "2024-10-27T01:30:00Z",  # and again on the second pass
        "2024-10-27T13:30:00Z",
    ]


def test_no_wildcard_list_runs_at_end_of_gap():
    job = Cron("30 2,14 * * *", timezone="Europe/Stockholm", fixed_time_rule="no-wildcard")
    assert iso(job.next_runs(4, "2024-03-30T20:00:00Z")) == [
        "2024-03-31T01:00:00Z",  # 02:30 does not exist, runs at 03:00
        "2024-03-31T12:30:00Z",
        "2024-04-01T00:30:00Z",
        "2024-04-01T12:30:00Z",
    ]
    job = Cron("30 2,14 * * *", timezone="Europe/Stockholm")
    assert iso(job.next_runs(2, "2024-03-30T20:00:00Z")) == [
        "2024-03-31T12:30:00Z",  # an interval job skips the gap
        "2024-04-01T00:30:00Z",
    ]


def test_no_wildcard_step_is_still_an_interval_job():
    job = Cron("0 0-23/2 * * *", timezone="Europe/Stockholm", fixed_time_rule="no-wildcard")
    assert iso(job.next_runs(4, "2024-10-26T20:00:00Z")) == [
        "2024-10-26T22:00:00Z",
        "2024-10-27T00:00:00Z",
        "2024-10-27T01:00:00Z",
        "2024-10-27T03:00:00Z",
    ]


def test_all_rule_runs_repeated_hour_once():
    job = Cron("*/30 * * * *", timezone="Europe/Stockholm", fixed_time_rule="all")
    assert iso(job.next_runs(5, "2024-10-26T23:10:00Z")) == [
        "2024-10-26T23:30:00Z",
        "2024-10-27T00:00:00Z",
        "2024-10-27T00:30:00Z",
        "2024-10-27T02:00:00Z",
        "2024-10-27T02:30:00Z",
    ]
    # Started on the second pass of the repeated hour, a search never goes back in time
    assert iso(job.next_runs(2, "2024-10-27T01:10:00Z")) == ["2024-10-27T02:00:00Z", "2024-10-27T02:30:00Z"]
    assert iso(job.previous_runs(3, "2024-10-27T01:10:00Z")) == [
        "2024-10-27T00:30:00Z",
        "2024-10-27T00:00:00Z",
        "2024-10-26T23:30:00Z",
    ]


def test_all_rule_runs_once_after_gap():
    job = Cron("*/30 2 * * *", timezone="Europe/Stockholm", fixed_time_rule="all")
    assert iso(job.next_runs(4, "2024-03-30T20:00:00Z")) == [
        "2024-03-31T01:00:00Z",
        "2024-04-01T00:00:00Z",
        "2024-04-01T00:30:00Z",
        "2024-04-02T00:00:00Z",
    ]


# The interval option is elapsed time, as in croner (JS) 11.0.1


def test_interval_is_elapsed_time_across_spring_forward():
    job = Cron("* * * * *", interval=3600, timezone="Europe/Stockholm")
    # 01:30, then an hour later, which is 03:30 on the wall clock
    assert iso(job.next_runs(3, "2024-03-31T00:30:00Z")) == [
        "2024-03-31T01:30:00Z",
        "2024-03-31T02:30:00Z",
        "2024-03-31T03:30:00Z",
    ]
    assert iso(job.previous_runs(2, "2024-03-31T01:30:00Z")) == ["2024-03-31T00:30:00Z", "2024-03-30T23:30:00Z"]


def test_interval_is_elapsed_time_across_fall_back():
    job = Cron("0 * * * *", interval=86400, timezone="Europe/Stockholm")
    # 24 hours, not 25, across the repeated hour
    assert iso(job.next_runs(2, "2024-10-26T10:00:00Z")) == ["2024-10-27T10:00:00Z", "2024-10-28T10:00:00Z"]
    job = Cron("*/10 * * * *", interval=1800, timezone="Europe/Stockholm")
    assert iso(job.next_runs(4, "2024-10-27T00:20:00Z")) == [
        "2024-10-27T00:50:00Z",
        "2024-10-27T01:20:00Z",  # in the repeated hour
        "2024-10-27T01:50:00Z",
        "2024-10-27T02:20:00Z",
    ]


def test_previous_runs_include_the_same_second():
    reference = "2025-01-02T00:00:05.500Z"
    job = Cron("* * * * * *", timezone="Europe/Stockholm")
    assert iso(job.previous_runs(2, reference)) == ["2025-01-02T00:00:05Z", "2025-01-02T00:00:04Z"]
    assert iso(job.previous_runs(1, "2025-01-02T00:00:05Z")) == ["2025-01-02T00:00:04Z"]
    # With an interval, also of one second, that run is too close to the reference
    job = Cron("* * * * * *", interval=1, timezone="UTC")
    assert iso(job.previous_runs(2, reference)) == ["2025-01-02T00:00:04Z", "2025-01-02T00:00:03Z"]
    job = Cron("* * * * * *", interval=2, timezone="UTC")
    assert iso(job.previous_runs(2, reference)) == ["2025-01-02T00:00:03Z", "2025-01-02T00:00:01Z"]


def test_previous_runs_stop_at_year_one():
    job = Cron("* * * * * *", timezone="UTC")
    assert job.previous_runs(5, "0001-01-01T00:00:02Z") == [
        datetime(1, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        datetime(1, 1, 1, tzinfo=timezone.utc),
    ]
    assert Cron("* * * * * *", interval=10, timezone="UTC").previous_runs(1, "0001-01-01T00:00:05Z") == []


# A fixed-time run in a gap runs at its end if that date matches the pattern, as in croner-rust


def test_fixed_time_in_gap_of_a_whole_day():
    # Samoa skipped 2011-12-30: 12:00 that day runs when the gap ends, at 2011-12-31 00:00 +14:00
    job = Cron("0 12 * * *", timezone="Pacific/Apia")
    assert iso(job.next_runs(3, "2011-12-29T00:00:00Z")) == [
        "2011-12-29T22:00:00Z",
        "2011-12-30T10:00:00Z",
        "2011-12-30T22:00:00Z",
    ]
    assert iso(job.previous_runs(4, "2012-01-02T00:00:00Z")) == [
        "2012-01-01T22:00:00Z",
        "2011-12-31T22:00:00Z",
        "2011-12-30T22:00:00Z",
        "2011-12-30T10:00:00Z",
    ]
    # Restricted to the 30th, the end of the gap does not match, so the next run is a month later
    job = Cron("0 12 30 * *", timezone="Pacific/Apia")
    assert iso(job.next_runs(1, "2011-12-29T00:00:00Z")) == ["2012-01-29T22:00:00Z"]


def test_fixed_time_in_gap_ending_at_midnight():
    # Nuuk went from -02 to -01 at 23:00 on 2024-03-30, the gap ends at midnight
    job = Cron("30 23 * * *", timezone="America/Nuuk")
    assert iso(job.next_runs(3, "2024-03-30T12:00:00Z")) == [
        "2024-03-31T01:00:00Z",  # 00:00 on the 31st
        "2024-04-01T00:30:00Z",
        "2024-04-02T00:30:00Z",
    ]
    job = Cron("30 23 30 * *", timezone="America/Nuuk")
    assert iso(job.next_runs(1, "2024-03-29T12:00:00Z")) == ["2024-05-01T00:30:00Z"]
