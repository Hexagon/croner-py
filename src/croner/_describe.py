"""Human readable descriptions of cron patterns, ported from croner-rust."""

from __future__ import annotations

from typing import Optional

from ._pattern import ANY_OCCURRENCE, LAST_OCCURRENCE, OCCURRENCE_BITMASKS, CronPattern

_DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_FIELD_SIZE = {"second": 60, "minute": 60, "hour": 24, "month": 12, "year": 9999}


def describe(pattern: CronPattern, dom_and_dow: bool = False) -> str:
    parts = [
        p
        for p in (
            _describe_time(pattern),
            _describe_day(pattern, dom_and_dow),
            _describe_month(pattern),
            _describe_year(pattern),
        )
        if p
    ]
    text = ", ".join(parts)
    if not text:
        return text
    return text[0].upper() + text[1:] + "."


def _values(p: CronPattern, kind: str) -> list[int]:
    return p.values(kind)


def _is_all_set(p: CronPattern, kind: str) -> bool:
    if p.steps[kind] != 1:
        return False
    if kind == "year":
        return p.star_year
    return len(_values(p, kind)) == _FIELD_SIZE[kind]


def _stepped_from_start(p: CronPattern, kind: str, values: list[int]) -> bool:
    minimum = 1 if kind == "month" else 0
    return p.steps[kind] > 1 and bool(values) and values[0] == minimum


def _text_list(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _number_list(values: list[int]) -> str:
    values = sorted(values)
    items: list[str] = []
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[j] + 1:
            j += 1
        if j > i + 1:
            items.append(f"{values[i]}-{values[j]}")
        else:
            items.extend(str(v) for v in values[i : j + 1])
        i = j + 1
    return _text_list(items)


def _time_of_day(hour: int, minute: int, second: Optional[int] = None) -> str:
    if second is None:
        return f"{hour:02}:{minute:02}"
    return f"{hour:02}:{minute:02}:{second:02}"


def _describe_time(p: CronPattern) -> str:
    sec = _values(p, "second")
    mins = _values(p, "minute")
    hours = _values(p, "hour")

    default_seconds = p.steps["second"] == 1 and sec == [0]
    every_second = _is_all_set(p, "second")
    all_minutes = _is_all_set(p, "minute")
    all_hours = _is_all_set(p, "hour")

    if every_second and all_minutes and all_hours:
        return "Every second"
    if default_seconds and all_minutes and all_hours:
        return "Every minute"
    if default_seconds and _stepped_from_start(p, "minute", mins) and all_hours:
        return f"At every {p.steps['minute']} minutes"

    if (
        not every_second
        and p.steps["hour"] == 1
        and len(hours) == 1
        and p.steps["minute"] == 1
        and len(mins) == 1
    ):
        time = _time_of_day(hours[0], mins[0])
        if not default_seconds:
            if _stepped_from_start(p, "second", sec):
                return f"At {time}, every {p.steps['second']} seconds"
            if len(sec) == 1:
                return f"At {_time_of_day(hours[0], mins[0], sec[0])}"
            return f"At {time}, at second {_number_list(sec)}"
        return f"At {time}"

    def hour_desc() -> str:
        if _stepped_from_start(p, "hour", hours):
            return f"of every {p.steps['hour']} hours"
        return f"hour {_number_list(hours)}"

    if default_seconds and all_minutes and not all_hours:
        return f"Every minute past {hour_desc()}"
    if every_second and all_minutes and not all_hours:
        return f"Every second past {hour_desc()}"

    parts: list[str] = []
    if every_second:
        parts.append("Every second")
    elif not default_seconds:
        if _stepped_from_start(p, "second", sec):
            parts.append(f"every {p.steps['second']} seconds")
        else:
            parts.append(f"second {_number_list(sec)}")

    if _stepped_from_start(p, "minute", mins):
        parts.append(f"every {p.steps['minute']} minutes")
    elif not all_minutes:
        desc = f"minute {_number_list(mins)}"
        parts.append(f"{desc} past every hour" if all_hours else desc)

    if not all_hours:
        if _stepped_from_start(p, "hour", hours):
            parts.append(f"of every {p.steps['hour']} hours")
        else:
            parts.append(f"of hour {_number_list(hours)}")

    if not parts:
        return "Every minute"
    if len(parts) > 1 and parts[0] == "Every second":
        return ", ".join(parts)
    return "At " + ", ".join(parts)


def _describe_dom(p: CronPattern) -> str:
    parts: list[str] = []
    days = _values(p, "day")
    if days:
        parts.append(f"day {_number_list(days)}")
    if p.last_day_of_month:
        parts.append("the last day of the month")
    if p.last_weekday:
        parts.append("the last weekday of the month")
    nearest = [i + 1 for i, v in enumerate(p.nearest_weekdays) if v]
    if nearest:
        parts.append(f"the weekday nearest day {_number_list(nearest)}")
    return _text_list(parts)


def _describe_dow_parts(p: CronPattern) -> list[str]:
    parts: list[str] = []
    dow = p.day_of_week
    last = [_DAY_NAMES[i] for i, v in enumerate(dow) if v != ANY_OCCURRENCE and v & LAST_OCCURRENCE]
    if last:
        parts.append(f"the last {_text_list(last)} of the month")
    suffixes = {1: "st", 2: "nd", 3: "rd"}
    for n, bit in enumerate(OCCURRENCE_BITMASKS, start=1):
        names = [_DAY_NAMES[i] for i, v in enumerate(dow) if v != ANY_OCCURRENCE and v & bit]
        if names:
            parts.append(f"the {n}{suffixes.get(n, 'th')} {_text_list(names)} of the month")
    regular = [_DAY_NAMES[i] for i, v in enumerate(dow) if v == ANY_OCCURRENCE]
    if regular:
        parts.append(_text_list(regular))
    return parts


def _describe_day(p: CronPattern, dom_and_dow: bool) -> str:
    star_dom = p.star_dom
    star_dow = p.star_dow
    if star_dom and star_dow:
        return ""
    dom = _describe_dom(p)
    if star_dow:
        return f"on {dom}"
    dow_parts = _describe_dow_parts(p)
    dow = _text_list(dow_parts)
    if star_dom:
        return f"on {dow}"
    if not dom:
        return f"on {dow}"
    if p.use_and_logic or dom_and_dow:
        if len(dow_parts) > 1:
            return f"on {dom} (if it is also one of: {dow})"
        return f"on {dom} (if it is also {dow})"
    return f"on {dom} or {dow}"


def _describe_month(p: CronPattern) -> str:
    if _is_all_set(p, "month"):
        return ""
    if p.steps["month"] > 1:
        return f"in every {p.steps['month']} months"
    return "in " + _text_list([_MONTH_NAMES[m - 1] for m in _values(p, "month")])


def _describe_year(p: CronPattern) -> str:
    if p.star_year:
        return ""
    if p.steps["year"] > 1:
        return f"in year every {p.steps['year']}"
    return f"in year {_number_list(_values(p, 'year'))}"
