"""Pythonic additions: timedelta options, properties, daemon, decorator, pattern equality, CLI."""

from datetime import datetime, timedelta, timezone

import pytest

from croner import Cron, CronError, CronPattern
from croner.__main__ import main

UTC = timezone.utc


def test_time_to_next():
    job = Cron("0 0 12 * * *", timezone="UTC")
    assert job.time_to_next("2024-01-01T11:59:30Z") == timedelta(seconds=30)
    assert job.ms_to_next("2024-01-01T11:59:30Z") == 30_000
    assert Cron("0 0 0 1 1 * 2000", timezone="UTC").time_to_next() is None


def test_once_property():
    job = Cron("2030-01-01T00:00:00Z", timezone="UTC")
    assert job.once == datetime(2030, 1, 1, tzinfo=UTC)
    assert job.get_once() == job.once
    assert Cron("* * * * *").once is None


def test_interval_and_utc_offset_accept_timedelta():
    a = Cron("* * * * * *", interval=timedelta(seconds=10), utc_offset=timedelta(hours=2))
    b = Cron("* * * * * *", interval=10, utc_offset=120)
    assert a.interval == b.interval == 10
    assert a.utc_offset == b.utc_offset == 120
    assert a.next_runs(3, "2024-01-01T00:00:00Z") == b.next_runs(3, "2024-01-01T00:00:00Z")
    assert Cron("* * * * *", utc_offset=timedelta(hours=-5, minutes=-30)).utc_offset == -330


@pytest.mark.parametrize(
    "options",
    [
        {"interval": timedelta(milliseconds=1500)},
        {"interval": 1.5},
        {"interval": True},
        {"interval": "ten"},
        {"utc_offset": timedelta(seconds=30)},
        {"utc_offset": timedelta(hours=15)},
    ],
)
def test_invalid_timedelta_options(options):
    with pytest.raises(CronError):
        Cron("* * * * *", **options)


def test_fixed_offset_tzinfo():
    job = Cron("0 0 12 * * *", timezone=timezone(timedelta(hours=2)))
    assert job.next_run("2024-06-01T00:00:00Z") == datetime(2024, 6, 1, 10, tzinfo=UTC)


def test_daemon_and_unref_are_aliases():
    assert Cron("* * * * *", daemon=True).unref is True
    assert Cron("* * * * *", unref=True).daemon is True
    assert Cron("* * * * *").daemon is False
    assert Cron("* * * * *", daemon=True, unref=True).daemon is True
    with pytest.raises(CronError):
        Cron("* * * * *", daemon=True, unref=False)
    with pytest.raises(CronError):
        Cron("* * * * *", daemon=1)


def test_decorator_returns_callable_job():
    job = Cron("0 0 0 1 1 * 2099", paused=True, daemon=True)

    @job
    def add(a, b=0):
        """Add two numbers."""
        return a + b

    try:
        assert add is job
        assert add(1, b=2) == 3
        assert add.__name__ == "add"
        assert add.__doc__ == "Add two numbers."
        assert add.next_run() is not None
    finally:
        job.stop()


def test_calling_a_job_without_function_needs_a_function():
    with pytest.raises(TypeError):
        Cron("* * * * *")(42)
    with pytest.raises(TypeError):
        Cron("* * * * *")()


def test_pattern_equality():
    assert CronPattern("@daily") == CronPattern("0 0 * * *")
    assert CronPattern("0 0 * * SUN") == CronPattern("0 0 0 * * 7")
    assert CronPattern("0 0 * * *") != CronPattern("0 1 * * *")
    # */60 only matches minute 0, but is an interval job, with other DST handling
    assert CronPattern("*/60 0 * * *") != CronPattern("0 0 * * *")
    assert len({CronPattern("@hourly"), CronPattern("0 * * * *"), CronPattern("5 * * * *")}) == 2
    assert CronPattern("* * * * *") != "* * * * *"


def test_error_messages_use_python_names():
    with pytest.raises(CronError, match="utc_offset"):
        Cron("* * * * *", utc_offset=1000)
    with pytest.raises(CronError, match="day_offset"):
        Cron("* * * * *", day_offset="x")
    with pytest.raises(CronError, match="day_of_week"):
        CronPattern("* * * * 8")


def test_cli_lists_runs(capsys):
    assert main(["0 12 * * MON-FRI", "-t", "UTC", "-n", "2", "-s", "2024-01-05T00:00:00"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "At 12:00, on Monday, Tuesday, Wednesday, Thursday, and Friday.",
        "2024-01-05T12:00:00+00:00",
        "2024-01-08T12:00:00+00:00",
    ]


def test_cli_previous_runs(capsys):
    assert main(["@daily", "-t", "UTC", "-n", "2", "-p", "-s", "2024-01-05T12:00:00"]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == ["2024-01-05T00:00:00+00:00", "2024-01-04T00:00:00+00:00"]


def test_cli_invalid_pattern(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["61 * * * *"])
    assert exit_info.value.code == 2
    assert "minute" in capsys.readouterr().err
