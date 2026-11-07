import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from croner import Cron, CronError, scheduled_jobs

UTC = timezone.utc


def fmt(dates):
    return [d.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S") for d in dates]


# ------------------------------------------------------------------- options


def test_start_at_is_inclusive_stop_at_exclusive():
    job = Cron(
        "0 0 12 * * *",
        timezone="UTC",
        start_at="2024-01-02T12:00:00",
        stop_at="2024-01-04T12:00:00",
    )
    assert fmt(job.next_runs(5, "2024-01-01T00:00:00Z")) == [
        "2024-01-02 12:00:00",
        "2024-01-03 12:00:00",
    ]
    assert fmt(job.previous_runs(5, "2024-02-01T00:00:00Z")) == [
        "2024-01-03 12:00:00",
        "2024-01-02 12:00:00",
    ]


def test_start_at_is_read_in_job_timezone():
    job = Cron("0 0 * * * *", timezone="Asia/Tokyo", start_at="2024-01-01T09:00:00")
    assert fmt([job.next_run("2023-01-01T00:00:00Z")]) == ["2024-01-01 00:00:00"]


def test_start_at_with_sub_second_rounds_up():
    job = Cron("* * * * * *", timezone="UTC", start_at="2024-01-01T00:00:00.5Z")
    assert fmt([job.next_run("2023-01-01T00:00:00Z")]) == ["2024-01-01 00:00:01"]


def test_interval():
    job = Cron("* * * * * *", interval=10, timezone="UTC")
    assert fmt(job.next_runs(3, "2024-01-01T00:00:00Z")) == [
        "2024-01-01 00:00:10",
        "2024-01-01 00:00:20",
        "2024-01-01 00:00:30",
    ]


def test_interval_with_start_at_in_the_future():
    job = Cron("* * * * * *", interval=60, timezone="UTC", start_at="2099-01-01T00:00:00Z")
    assert fmt([job.next_run()]) == ["2099-01-01 00:00:00"]


def test_max_runs_limits_next_runs():
    job = Cron("* * * * * *", max_runs=2)
    assert len(job.next_runs(10)) == 2
    assert job.runs_left() == 2
    assert len(list(job.enumerate())) == 2


def test_day_offset():
    job = Cron("0 0 0 L * *", timezone="UTC", day_offset=-1)
    assert fmt(job.next_runs(2, "2024-01-01T00:00:00Z")) == [
        "2024-01-30 00:00:00",
        "2024-02-28 00:00:00",
    ]
    assert fmt(job.previous_runs(1, "2024-02-01T00:00:00Z")) == ["2024-01-30 00:00:00"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval": -1},
        {"interval": "x"},
        {"utc_offset": 900},
        {"utc_offset": 60, "timezone": "UTC"},
        {"timezone": "Not/AZone"},
        {"mode": "foo"},
        {"day_offset": "x"},
        {"unref": "yes"},
    ],
)
def test_invalid_options(kwargs):
    with pytest.raises(CronError):
        Cron("* * * * *", **kwargs)


def test_tzinfo_object_as_timezone():
    from zoneinfo import ZoneInfo

    job = Cron("0 0 12 * * *", timezone=ZoneInfo("Europe/Stockholm"))
    assert fmt([job.next_run("2024-01-01T00:00:00Z")]) == ["2024-01-01 11:00:00"]


def test_empty_timezone_means_local():
    assert Cron("* * * * *", timezone="").timezone is None


def test_inputs_types():
    job = Cron("0 0 12 * * *", timezone="UTC")
    expected = ["2024-01-01 12:00:00"]
    assert fmt([job.next_run("2024-01-01")]) == expected
    assert fmt([job.next_run("2024-01-01T00:00:00Z")]) == expected
    assert fmt([job.next_run("2024-01-01T01:00:00+01:00")]) == expected
    assert fmt([job.next_run(datetime(2024, 1, 1))]) == expected
    assert fmt([job.next_run(datetime(2024, 1, 1).date())]) == expected
    with pytest.raises(CronError):
        job.next_run("not a date")
    with pytest.raises(CronError):
        job.next_run(12345)  # type: ignore[arg-type]


def test_ms_to_next():
    job = Cron("0 0 12 * * *", timezone="UTC")
    assert job.ms_to_next("2024-01-01T11:59:59.5Z") == 500


# ---------------------------------------------------------------- one-off jobs


def test_once_job():
    future = datetime.now(UTC) + timedelta(days=1)
    job = Cron(future)
    assert job.get_pattern() is None
    assert job.get_once() == future
    assert job.next_run() == future
    assert job.next_runs(3) == [future]
    assert job.match(future)
    assert job.previous_runs(1, future + timedelta(seconds=1)) == [future]


def test_once_job_from_string_in_timezone():
    job = Cron("2099-06-01T12:00:00", timezone="Asia/Tokyo")
    assert fmt([job.get_once()]) == ["2099-06-01 03:00:00"]


def test_once_job_in_the_past():
    past = datetime.now(UTC) - timedelta(days=1)
    assert Cron(past).next_run() is None
    assert Cron(past, allow_past=True).next_run() == past


# ------------------------------------------------------------------- iterator


def test_enumerate_and_peek():
    job = Cron("0 0 * * * *", timezone="UTC")
    it = job.enumerate("2024-01-01T00:00:00Z")
    assert fmt([it.peek()]) == ["2024-01-01 01:00:00"]
    first, second = next(it), next(it)
    assert fmt([first, second]) == ["2024-01-01 01:00:00", "2024-01-01 02:00:00"]
    it.reset("2024-06-01T00:00:00Z")
    assert fmt([next(it)]) == ["2024-06-01 01:00:00"]


def test_enumerate_ends():
    job = Cron("0 0 0 1 1 * 2030-2031", timezone="UTC")
    assert fmt(job.enumerate("2024-01-01T00:00:00Z")) == [
        "2030-01-01 00:00:00",
        "2031-01-01 00:00:00",
    ]


# -------------------------------------------------------------- named jobs


def test_named_jobs():
    job = Cron("* * * * *", name="named-job-test")
    assert job in scheduled_jobs
    with pytest.raises(CronError):
        Cron("* * * * *", name="named-job-test")
    job.stop()
    assert job not in scheduled_jobs
    assert job.is_stopped()
    Cron("* * * * *", name="named-job-test").stop()


# ----------------------------------------------------------------- scheduling


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_schedule_runs_and_max_runs():
    calls = []
    job = Cron("* * * * * *", lambda j, ctx: calls.append(ctx), max_runs=2, context="ctx", unref=True)
    try:
        assert wait_for(lambda: len(calls) == 2, 4)
        time.sleep(1.2)
        assert calls == ["ctx", "ctx"]
        assert job.runs_left() == 0
        assert job.previous_run() is not None
        assert not job.is_running()
    finally:
        job.stop()


def test_callback_arity():
    calls = []
    jobs = [
        Cron("* * * * * *", lambda: calls.append(0), max_runs=1, unref=True),
        Cron("* * * * * *", lambda j: calls.append(1), max_runs=1, unref=True),
    ]
    try:
        assert wait_for(lambda: sorted(calls) == [0, 1], 3)
    finally:
        for j in jobs:
            j.stop()


def test_decorator_and_trigger():
    calls = []
    job = Cron("0 0 0 1 1 * 2099", paused=True, unref=True)

    @job
    def task(j):
        calls.append(j)

    try:
        assert job.fn is task
        job.trigger()
        assert calls == [job]
        assert job.current_run() is not None
        with pytest.raises(CronError):
            job.schedule(lambda: None)
    finally:
        job.stop()


def test_async_function():
    done = threading.Event()

    async def task():
        await asyncio.sleep(0)
        done.set()

    job = Cron("* * * * * *", task, max_runs=1, unref=True)
    try:
        assert done.wait(3)
    finally:
        job.stop()


def test_catch():
    errors = []

    def boom():
        raise RuntimeError("boom")

    job = Cron("* * * * * *", boom, max_runs=1, catch=lambda e, j: errors.append(str(e)), unref=True)
    try:
        assert wait_for(lambda: errors == ["boom"], 3)
        assert not job.is_busy()
    finally:
        job.stop()


def test_protect():
    blocked = []
    release = threading.Event()
    job = Cron(
        "* * * * * *",
        lambda: release.wait(5),
        protect=lambda j: blocked.append(j),
        unref=True,
    )
    try:
        assert wait_for(lambda: len(blocked) >= 1, 4)
        assert job.is_busy()
    finally:
        release.set()
        job.stop()


def test_pause_resume_stop():
    calls = []
    job = Cron("* * * * * *", lambda: calls.append(1), paused=True, unref=True)
    try:
        time.sleep(1.5)
        assert calls == []
        assert not job.is_running()
        assert job.resume()
        assert job.is_running()
        assert wait_for(lambda: len(calls) >= 1, 3)
        job.stop()
        count = len(calls)
        time.sleep(1.5)
        assert len(calls) == count
        assert not job.pause()
        assert not job.resume()
    finally:
        job.stop()
