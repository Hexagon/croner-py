from datetime import datetime, timezone

import pytest

from croner import Cron, CronError, CronPattern

UTC = timezone.utc
REF = "2024-01-01T00:00:00Z"  # a Monday


def runs(pattern, n=3, ref=REF, **kw):
    kw.setdefault("timezone", "UTC")
    return [d.strftime("%Y-%m-%d %H:%M:%S") for d in Cron(pattern, **kw).next_runs(n, ref)]


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "* * * *",
        "* * * * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 32 * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * 0 *",
        "* * * * 8",
        "* * * * * * 0",
        "* * * * * * 10000",
        "a * * * *",
        "*/0 * * * *",
        "*/61 * * * *",
        "5-1 * * * *",
        "1-2-3 * * * *",
        "0/10 * * * *",
        "/10 * * * *",
        "* * * * +",
        "* * 15W-20 * *",
        "* * W * *",
        "1W * * * *",
        "* * * * 1#6",
        "* * * * 1#0",
        "* 1#1 * * *",
        "@reboot",
        "@foo",
        "1, * * * *",
    ],
)
def test_invalid_patterns(pattern):
    with pytest.raises(CronError):
        Cron(pattern)


def test_cron_error_is_value_error():
    assert issubclass(CronError, ValueError)


def test_five_six_seven_parts():
    assert runs("*/30 * * * *", 2) == ["2024-01-01 00:30:00", "2024-01-01 01:00:00"]
    assert runs("*/30 * * * * *", 2) == ["2024-01-01 00:00:30", "2024-01-01 00:01:00"]
    assert runs("0 0 0 1 1 * 2030", 2) == ["2030-01-01 00:00:00"]


def test_whitespace_and_tabs():
    assert runs("0\t12   * * *", 1) == ["2024-01-01 12:00:00"]


@pytest.mark.parametrize(
    "nickname,expected",
    [
        ("@yearly", "2025-01-01 00:00:00"),
        ("@annually", "2025-01-01 00:00:00"),
        ("@monthly", "2024-02-01 00:00:00"),
        ("@weekly", "2024-01-07 00:00:00"),
        ("@daily", "2024-01-02 00:00:00"),
        ("@midnight", "2024-01-02 00:00:00"),
        ("@hourly", "2024-01-01 01:00:00"),
        ("@HOURLY", "2024-01-01 01:00:00"),
    ],
)
def test_nicknames(nickname, expected):
    assert runs(nickname, 1) == [expected]


def test_names_are_case_insensitive():
    assert runs("0 0 * jan,Feb mon", 2) == ["2024-01-08 00:00:00", "2024-01-15 00:00:00"]
    assert runs("0 0 * * FRI-SUN", 3) == [
        "2024-01-05 00:00:00",
        "2024-01-06 00:00:00",
        "2024-01-07 00:00:00",
    ]


def test_sunday_as_7():
    assert runs("0 0 * * 7", 1) == runs("0 0 * * 0", 1) == ["2024-01-07 00:00:00"]
    assert runs("0 0 * * 5-7", 3) == [
        "2024-01-05 00:00:00",
        "2024-01-06 00:00:00",
        "2024-01-07 00:00:00",
    ]


def test_question_mark_is_wildcard():
    assert runs("0 0 ? * MON", 1) == ["2024-01-08 00:00:00"]
    assert runs("? 0 0 ? * ?", 1) == runs("* 0 0 * * *", 1)


def test_ranges_and_steps():
    assert runs("0 0 10-20/5 * * *", 4) == [
        "2024-01-01 10:00:00",
        "2024-01-01 15:00:00",
        "2024-01-01 20:00:00",
        "2024-01-02 10:00:00",
    ]
    assert runs("0 0 0 */10 * *", 4) == [
        "2024-01-11 00:00:00",
        "2024-01-21 00:00:00",
        "2024-01-31 00:00:00",
        "2024-02-01 00:00:00",
    ]


def test_sloppy_ranges():
    assert runs("5/20 * * * * *", 3, sloppy_ranges=True) == [
        "2024-01-01 00:00:05",
        "2024-01-01 00:00:25",
        "2024-01-01 00:00:45",
    ]
    assert runs("/30 * * * * *", 2, sloppy_ranges=True) == [
        "2024-01-01 00:00:30",
        "2024-01-01 00:01:00",
    ]


def test_last_day_of_month():
    assert runs("0 0 L * *", 3) == [
        "2024-01-31 00:00:00",
        "2024-02-29 00:00:00",
        "2024-03-31 00:00:00",
    ]
    assert runs("0 0 L 2 *", 2) == ["2024-02-29 00:00:00", "2025-02-28 00:00:00"]


def test_last_weekday_of_month():
    # 2024-03-31 is a Sunday, 2024-08-31 is a Saturday
    assert runs("0 0 LW * *", 8) == [
        "2024-01-31 00:00:00",
        "2024-02-29 00:00:00",
        "2024-03-29 00:00:00",
        "2024-04-30 00:00:00",
        "2024-05-31 00:00:00",
        "2024-06-28 00:00:00",
        "2024-07-31 00:00:00",
        "2024-08-30 00:00:00",
    ]


def test_nearest_weekday():
    # 2024-06-01 is a Saturday -> Monday 3rd, 2024-09-01 is a Sunday -> Monday 2nd
    assert runs("0 0 1W 6 *", 1) == ["2024-06-03 00:00:00"]
    assert runs("0 0 1W 9 *", 1) == ["2024-09-02 00:00:00"]
    # 2024-06-15 is a Saturday -> Friday 14th, 2024-09-15 is a Sunday -> Monday 16th
    assert runs("0 0 15W 6 *", 1) == ["2024-06-14 00:00:00"]
    assert runs("0 0 15W 9 *", 1) == ["2024-09-16 00:00:00"]
    # 2024-03-31 is a Sunday -> Friday 29th, it doesn't cross into April
    assert runs("0 0 31W 3 *", 1) == ["2024-03-29 00:00:00"]


def test_nth_weekday():
    assert runs("0 0 * * FRI#2", 2) == ["2024-01-12 00:00:00", "2024-02-09 00:00:00"]
    # REF is Monday 2024-01-01 00:00, which is excluded
    assert runs("0 0 * * 1#1", 2) == ["2024-02-05 00:00:00", "2024-03-04 00:00:00"]
    assert runs("0 0 * * 5#L", 2) == ["2024-01-26 00:00:00", "2024-02-23 00:00:00"]
    assert runs("0 0 * * 5L", 2) == runs("0 0 * * 5#L", 2)
    assert runs("0 0 * * FRI#L", 2) == runs("0 0 * * 5#L", 2)
    assert runs("0 0 * * 5-6#L", 2) == ["2024-01-26 00:00:00", "2024-01-27 00:00:00"]
    assert runs("0 0 * * 2#5", 2) == ["2024-01-30 00:00:00", "2024-04-30 00:00:00"]


def test_dom_dow_or_by_default():
    assert runs("0 0 13 * FRI", 3) == [
        "2024-01-05 00:00:00",
        "2024-01-12 00:00:00",
        "2024-01-13 00:00:00",
    ]


def test_dom_dow_and():
    expected = ["2024-09-13 00:00:00", "2024-12-13 00:00:00"]
    assert runs("0 0 13 * FRI", 2, dom_and_dow=True) == expected
    assert runs("0 0 13 * +FRI", 2) == expected
    with pytest.deprecated_call():
        assert runs("0 0 13 * FRI", 2, legacy_mode=False) == expected


def test_alternative_weekdays():
    assert runs("0 0 * * 1", 1, alternative_weekdays=True) == ["2024-01-07 00:00:00"]
    assert runs("0 0 * * 2-6", 1, alternative_weekdays=True) == ["2024-01-02 00:00:00"]
    assert runs("0 0 * * MON", 1, alternative_weekdays=True) == ["2024-01-08 00:00:00"]
    with pytest.raises(CronError):
        Cron("0 0 * * 0", alternative_weekdays=True)


def test_year_field():
    assert runs("0 0 0 29 2 * 2025-2029", 2) == ["2028-02-29 00:00:00"]
    assert runs("0 0 0 1 1 * */4", 2) == ["2028-01-01 00:00:00", "2032-01-01 00:00:00"]
    assert Cron("0 0 0 1 1 * 2020").next_run() is None


def test_impossible_pattern_returns_none():
    assert Cron("0 0 30 2 *").next_run() is None
    assert Cron("0 0 31 4 *").previous_runs(1) == []


@pytest.mark.parametrize(
    "mode,ok,bad",
    [
        ("5-part", "* * * * *", "* * * * * *"),
        ("6-part", "* * * * * *", "* * * * *"),
        ("7-part", "* * * * * * *", "* * * * * *"),
        ("5-or-6-parts", "* * * * * *", "* * * * * * *"),
        ("6-or-7-parts", "* * * * * * *", "* * * * *"),
    ],
)
def test_modes(mode, ok, bad):
    Cron(ok, mode=mode)
    with pytest.raises(CronError):
        Cron(bad, mode=mode)


def test_invalid_mode():
    with pytest.raises(CronError):
        Cron("* * * * *", mode="8-part")


def test_fixed_time_detection():
    assert CronPattern("0 30 2 * * *").is_fixed_time
    assert not CronPattern("0 30 1,2 * * *").is_fixed_time
    assert not CronPattern("0 */30 2 * * *").is_fixed_time
    assert not CronPattern("* 30 2 * * *").is_fixed_time


def test_pattern_values():
    p = CronPattern("0 9-11 * * 1-5")
    assert p.values("hour") == [9, 10, 11]
    assert p.values("day_of_week") == [1, 2, 3, 4, 5]
    assert p.values("month") == list(range(1, 13))


def test_match():
    job = Cron("0 0 12 * * MON", timezone="UTC")
    assert job.match("2024-01-01T12:00:00Z")
    assert job.match(datetime(2024, 1, 1, 12, 0, 0, 500000, tzinfo=UTC))
    assert not job.match("2024-01-01T12:00:01Z")
    assert not job.match("2024-01-02T12:00:00Z")
    assert Cron("0 0 0 * * * 2024", timezone="UTC").match("2024-05-01T00:00:00Z")
    assert not Cron("0 0 0 * * * 2024", timezone="UTC").match("2025-05-01T00:00:00Z")
    assert Cron("0 0 L * *", timezone="UTC").match("2024-02-29T00:00:00Z")


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("* * * * *", "Every minute."),
        ("*/15 * * * *", "At every 15 minutes."),
        ("0 * * * *", "At minute 0 past every hour."),
        ("0 14 * * *", "At 14:00."),
        ("2,4,6 * * * *", "At minute 2, 4, and 6 past every hour."),
        ("0 0-6 * * *", "At minute 0, of hour 0-6."),
        ("0 */2 * * *", "At minute 0, of every 2 hours."),
        ("* 0 * * *", "Every minute past hour 0."),
        ("* 0,12 * * *", "Every minute past hour 0 and 12."),
        ("*/10 * * * * *", "At every 10 seconds."),
        ("30 0 14 * * *", "At 14:00:30."),
        ("10-20 0 14 * * *", "At 14:00, at second 10-20."),
        ("* * 0 * * *", "Every second past hour 0."),
        ("0 0 0 1 1 * 2025", "At 00:00, on day 1, in January, in year 2025."),
        ("0 0 0 1 1 * 2025-2030", "At 00:00, on day 1, in January, in year 2025-2030."),
        ("0 12 * * MON-FRI", "At 12:00, on Monday, Tuesday, Wednesday, Thursday, and Friday."),
        ("0 0 L * *", "At 00:00, on the last day of the month."),
        ("0 0 15W * *", "At 00:00, on the weekday nearest day 15."),
        ("0 0 * * 5#L", "At 00:00, on the last Friday of the month."),
        ("0 0 * * MON#2", "At 00:00, on the 2nd Monday of the month."),
        ("0 0 1 * +MON", "At 00:00, on day 1 (if it is also Monday)."),
        ("0 0 1 * MON", "At 00:00, on day 1 or Monday."),
    ],
)
def test_describe(pattern, expected):
    assert Cron(pattern).describe() == expected
