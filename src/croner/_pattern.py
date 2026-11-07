"""Cron pattern parsing.

A faithful port of the pattern parser in croner (JavaScript) and croner-rust,
following the Open Cron Pattern Standard (OCPS) 1.0 - 1.4.
"""

from __future__ import annotations

import re
from typing import List, Optional, Union

from ._errors import CronError

__all__ = [
    "CronPattern",
    "LAST_OCCURRENCE",
    "ANY_OCCURRENCE",
    "OCCURRENCE_BITMASKS",
    "MODES",
]

#: Bit for the last occurrence of a weekday in its month (``5#L`` / ``5L``).
LAST_OCCURRENCE = 0b100000
#: Bits for the 1st to 5th occurrence of a weekday in its month (``5#1`` ... ``5#5``).
OCCURRENCE_BITMASKS = (0b00001, 0b00010, 0b00100, 0b01000, 0b10000)
#: Every occurrence of a weekday, i.e. a plain weekday.
ANY_OCCURRENCE = 0b00001 | 0b00010 | 0b00100 | 0b01000 | 0b10000 | LAST_OCCURRENCE

#: Accepted values for the ``mode`` option.
MODES = ("auto", "5-part", "6-part", "7-part", "5-or-6-parts", "6-or-7-parts")

_MODE_PARTS = {
    "5-part": (5,),
    "6-part": (6,),
    "7-part": (7,),
    "5-or-6-parts": (5, 6),
    "6-or-7-parts": (6, 7),
}

# Names are replaced in this order, so "-sun" must come before "sun": Sunday as
# the upper bound of a range is 7, so that e.g. FRI-SUN is a valid range.
_DAY_NAMES = (
    ("-sun", "-7"),
    ("sun", "0"),
    ("mon", "1"),
    ("tue", "2"),
    ("wed", "3"),
    ("thu", "4"),
    ("fri", "5"),
    ("sat", "6"),
)

_DAY_NAMES_QUARTZ = (
    ("sun", "1"),
    ("mon", "2"),
    ("tue", "3"),
    ("wed", "4"),
    ("thu", "5"),
    ("fri", "6"),
    ("sat", "7"),
)

_MONTH_NAMES = (
    ("jan", "1"),
    ("feb", "2"),
    ("mar", "3"),
    ("apr", "4"),
    ("may", "5"),
    ("jun", "6"),
    ("jul", "7"),
    ("aug", "8"),
    ("sep", "9"),
    ("oct", "10"),
    ("nov", "11"),
    ("dec", "12"),
)

_NICKNAMES = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

_DIGITS = re.compile(r"^\d+$")
_RANGE_STEP = re.compile(r"^(\d+)-(\d+)/(\d+)$")
_ILLEGAL_DOM = re.compile(r"[^/*0-9,\-WwLl]")
_ILLEGAL_DOW = re.compile(r"[^/*0-9,\-#Ll]")
_ILLEGAL = re.compile(r"[^/*0-9,\-]")

_Nth = Union[int, str, None]


def _int(value: str, what: str, conf: str) -> int:
    if not _DIGITS.match(value):
        raise CronError(f"CronPattern: {what} is not a number: '{conf}'")
    return int(value)


class CronPattern:
    """A parsed cron pattern.

    Field values are kept as lookup tables in the same layout as croner (JavaScript):

    * ``second``, ``minute`` - 60 entries, index = value
    * ``hour`` - 24 entries, index = value
    * ``day`` - 31 entries, index = day of month - 1
    * ``month`` - 12 entries, index = month - 1
    * ``day_of_week`` - 7 entries, index 0 = Sunday, values are occurrence bitmasks
    * ``year`` - 10000 entries, index = year (1 - 9999)

    :param pattern: The cron pattern, e.g. ``"*/5 * * * *"``.
    :param mode: Field count mode, one of :data:`MODES`.
    :param alternative_weekdays: Quartz-style weekday numbering (1 = Sunday ... 7 = Saturday).
    :param sloppy_ranges: Accept non-standard steps like ``/10`` or ``5/10``.
    :raises CronError: If the pattern is invalid.
    """

    def __init__(
        self,
        pattern: str,
        *,
        mode: str = "auto",
        alternative_weekdays: bool = False,
        sloppy_ranges: bool = False,
    ) -> None:
        if not isinstance(pattern, str):
            raise CronError("CronPattern: Pattern has to be of type string.")
        if mode not in MODES:
            raise CronError(
                "CronPattern: mode must be one of " + ", ".join(repr(m) for m in MODES) + "."
            )

        self.pattern: str = pattern
        self.mode: str = mode
        self.alternative_weekdays: bool = alternative_weekdays
        self.sloppy_ranges: bool = sloppy_ranges

        self.second: List[int] = [0] * 60
        self.minute: List[int] = [0] * 60
        self.hour: List[int] = [0] * 24
        self.day: List[int] = [0] * 31
        self.month: List[int] = [0] * 12
        self.day_of_week: List[int] = [0] * 7
        self.year: bytearray = bytearray(10000)
        self.nearest_weekdays: List[int] = [0] * 31

        self.last_day_of_month: bool = False
        self.last_weekday: bool = False
        self.star_dom: bool = False
        self.star_dow: bool = False
        self.star_year: bool = False
        #: OCPS 1.4 ``+`` prefix in the day-of-week field: combine DOM and DOW with AND.
        self.use_and_logic: bool = False
        #: Single, non-wildcard, non-stepped value in each of second, minute and hour.
        #: Fixed-time and interval jobs handle DST transitions differently.
        self.is_fixed_time: bool = False

        # Step and wildcard information, used by describe()
        self.steps = {"second": 1, "minute": 1, "hour": 1, "day": 1, "month": 1, "day_of_week": 1, "year": 1}
        self.wildcards = {k: False for k in self.steps}

        self._parse()

    # ------------------------------------------------------------------ parsing

    def _parse(self) -> None:
        source = self.pattern
        if "@" in source:
            source = self._handle_nicknames(source).strip()

        parts = source.split() or [""]
        count = len(parts)

        if count < 5 or count > 7:
            raise CronError(
                f"CronPattern: invalid configuration format ('{source}'), exactly five, six, "
                "or seven space separated parts are required."
            )

        if self.mode != "auto":
            expected = _MODE_PARTS[self.mode]
            if count not in expected:
                expected_str = " or ".join(str(e) for e in expected)
                raise CronError(
                    f"CronPattern: mode '{self.mode}' requires exactly {expected_str} parts, "
                    f"but pattern '{source}' has {count} parts."
                )

        if len(parts) == 5:
            parts.insert(0, "0")
        if len(parts) == 6:
            parts.append("*")

        # OCPS 1.4: '?' is an alias for '*'
        parts = [p.replace("?", "*") for p in parts]

        # L / LW in day-of-month
        if parts[3].upper() == "LW":
            self.last_weekday = True
            parts[3] = ""
        elif "L" in parts[3].upper():
            parts[3] = re.sub("l", "", parts[3], flags=re.IGNORECASE)
            self.last_day_of_month = True

        if parts[3] == "*":
            self.star_dom = True
        if parts[6] == "*":
            self.star_year = True

        if len(parts[4]) >= 3:
            parts[4] = self._replace_alpha(parts[4], _MONTH_NAMES)
        if len(parts[5]) >= 3:
            parts[5] = self._replace_alpha(
                parts[5], _DAY_NAMES_QUARTZ if self.alternative_weekdays else _DAY_NAMES
            )

        # OCPS 1.4: '+' prefix in day-of-week for explicit AND logic
        if parts[5].startswith("+"):
            self.use_and_logic = True
            parts[5] = parts[5][1:]
            if parts[5] == "":
                raise CronError("CronPattern: Day-of-week field cannot be empty after '+' modifier.")

        if parts[5] == "*":
            self.star_dow = True

        if self.mode == "5-part":
            parts[0] = "0"
            parts[6] = "*"
        elif self.mode in ("6-part", "5-or-6-parts"):
            parts[6] = "*"
        if parts[6] == "*":
            self.star_year = True

        self._throw_at_illegal_characters(parts)

        self._part_to_array("second", parts[0], 0, 1)
        self._part_to_array("minute", parts[1], 0, 1)
        self._part_to_array("hour", parts[2], 0, 1)
        self._part_to_array("day", parts[3], -1, 1)
        self._part_to_array("month", parts[4], -1, 1)
        self._part_to_array(
            "day_of_week", parts[5], -1 if self.alternative_weekdays else 0, ANY_OCCURRENCE
        )
        self._part_to_array("year", parts[6], 0, 1)

        def is_fixed(part: str, values: List[int]) -> bool:
            return "*" not in part and "/" not in part and sum(1 for v in values if v) == 1

        self.is_fixed_time = (
            is_fixed(parts[0], self.second)
            and is_fixed(parts[1], self.minute)
            and is_fixed(parts[2], self.hour)
        )

    def _table(self, kind: str):
        return getattr(self, kind)

    def _size(self, kind: str) -> int:
        return len(self._table(kind))

    def _part_to_array(self, kind: str, conf: str, offset: int, default: int) -> None:
        if conf == "" and not (kind == "day" and (self.last_day_of_month or self.last_weekday)):
            raise CronError(
                f"CronPattern: configuration entry {kind} ({conf}) is empty, check for trailing spaces."
            )

        if conf == "*":
            self.wildcards[kind] = True
            table = self._table(kind)
            start = 1 if kind == "year" else 0
            for i in range(start, self._size(kind)):
                table[i] = default
            return

        split = conf.split(",")
        if len(split) > 1:
            for part in split:
                self._part_to_array(kind, part, offset, default)
        elif "-" in conf and "/" in conf:
            self._handle_range_with_stepping(conf, kind, offset, default)
        elif "-" in conf:
            self._handle_range(conf, kind, offset, default)
        elif "/" in conf:
            self._handle_stepping(conf, kind, offset, default)
        elif conf != "":
            self._handle_number(conf, kind, offset, default)

    def _throw_at_illegal_characters(self, parts: List[str]) -> None:
        for i, part in enumerate(parts):
            regex = _ILLEGAL_DOM if i == 3 else _ILLEGAL_DOW if i == 5 else _ILLEGAL
            if regex.search(part):
                raise CronError(
                    f"CronPattern: configuration entry {i} ({part}) contains illegal characters."
                )

    def _extract_nth(self, conf: str, kind: str):
        rest = conf
        nth: _Nth = None
        if "#" in rest:
            if kind != "day_of_week":
                raise CronError("CronPattern: nth (#) only allowed in day-of-week field")
            rest, _, nth_str = rest.partition("#")
            nth = nth_str
        elif rest.upper().endswith("L"):
            if kind != "day_of_week":
                raise CronError(
                    "CronPattern: L modifier only allowed in day-of-week field "
                    "(use L alone for day-of-month)"
                )
            nth = "L"
            rest = rest[:-1]
        return rest, nth

    def _handle_number(self, conf: str, kind: str, offset: int, default: int) -> None:
        rest, nth = self._extract_nth(conf, kind)
        if "W" in conf.upper():
            if kind != "day":
                raise CronError(
                    "CronPattern: Nearest weekday modifier (W) only allowed in day-of-month."
                )
            if not rest.upper().endswith("W"):
                raise CronError(f"CronPattern: Invalid nearest weekday value: '{conf}'")
            kind = "nearest_weekdays"
            rest = rest[:-1]
        index = _int(rest, kind, conf) + offset
        self._set_part(kind, index, nth if nth is not None else default)

    def _set_part(self, kind: str, index: int, value) -> None:
        if kind == "day_of_week":
            if index == 7:
                index = 0
            if index < 0 or index > 6:
                raise CronError(f"CronPattern: Invalid value for dayOfWeek: {index}")
            self._set_nth_weekday_of_month(index, value)
            return

        if kind in ("second", "minute"):
            valid = 0 <= index < 60
        elif kind == "hour":
            valid = 0 <= index < 24
        elif kind in ("day", "nearest_weekdays"):
            valid = 0 <= index < 31
        elif kind == "month":
            valid = 0 <= index < 12
        elif kind == "year":
            if not 1 <= index < 10000:
                raise CronError(
                    f"CronPattern: Invalid value for year: {index} (supported range: 1-9999)"
                )
            valid = True
        else:  # pragma: no cover - internal
            raise CronError(f"CronPattern: Invalid part specified: {kind}")
        if not valid:
            raise CronError(f"CronPattern: Invalid value for {kind}: {index}")
        self._table(kind)[index] = value

    def _validate_range(self, lower: int, upper: int, steps: Optional[int], kind: str, conf: str) -> None:
        if lower > upper:
            raise CronError(f"CronPattern: From value is larger than to value: '{conf}'")
        if steps is not None:
            if steps == 0:
                raise CronError("CronPattern: Syntax error, illegal stepping: 0")
            if steps > self._size(kind):
                raise CronError(
                    "CronPattern: Syntax error, steps cannot be greater than maximum value of part "
                    f"({self._size(kind)})"
                )

    def _handle_range_with_stepping(self, conf: str, kind: str, offset: int, default: int) -> None:
        if "W" in conf.upper():
            raise CronError("CronPattern: Syntax error, W is not allowed in ranges with stepping.")
        rest, nth = self._extract_nth(conf, kind)
        m = _RANGE_STEP.match(rest)
        if m is None:
            raise CronError(f"CronPattern: Syntax error, illegal range with stepping: '{conf}'")
        lower = int(m.group(1)) + offset
        upper = int(m.group(2)) + offset
        steps = int(m.group(3))
        self._validate_range(lower, upper, steps, kind, conf)
        self.steps[kind] = steps
        for i in range(lower, upper + 1, steps):
            self._set_part(kind, i, nth if nth is not None else default)

    def _handle_range(self, conf: str, kind: str, offset: int, default: int) -> None:
        if "W" in conf.upper():
            raise CronError("CronPattern: Syntax error, W is not allowed in a range.")
        rest, nth = self._extract_nth(conf, kind)
        split = rest.split("-")
        if len(split) != 2:
            raise CronError(f"CronPattern: Syntax error, illegal range: '{conf}'")
        lower = _int(split[0], "lower range", conf) + offset
        upper = _int(split[1], "upper range", conf) + offset
        self._validate_range(lower, upper, None, kind, conf)
        for i in range(lower, upper + 1):
            self._set_part(kind, i, nth if nth is not None else default)

    def _handle_stepping(self, conf: str, kind: str, offset: int, default: int) -> None:
        if "W" in conf.upper():
            raise CronError("CronPattern: Syntax error, W is not allowed in parts with stepping.")
        rest, nth = self._extract_nth(conf, kind)
        split = rest.split("/")
        if len(split) != 2:
            raise CronError(f"CronPattern: Syntax error, illegal stepping: '{conf}'")

        if not self.sloppy_ranges:
            if split[0] == "":
                raise CronError(
                    f"CronPattern: Syntax error, stepping with missing prefix ('{conf}') is not "
                    "allowed. Use wildcard (*/step) or range (min-max/step) instead."
                )
            if split[0] != "*":
                raise CronError(
                    f"CronPattern: Syntax error, stepping with numeric prefix ('{conf}') is not "
                    "allowed. Use wildcard (*/step) or range (min-max/step) instead."
                )
        elif split[0] == "":
            split[0] = "*"

        start = 0
        if split[0] != "*":
            start = _int(split[0], "start", conf) + offset
        else:
            self.wildcards[kind] = True

        steps = _int(split[1], "stepping", conf)
        self._validate_range(0, self._size(kind) - 1, steps, kind, conf)
        self.steps[kind] = steps

        for i in range(start, self._size(kind), steps):
            if kind == "year" and i == 0:
                continue  # There is no year 0
            self._set_part(kind, i, nth if nth is not None else default)

    @staticmethod
    def _replace_alpha(conf: str, mapping) -> str:
        for name, value in mapping:
            conf = re.sub(re.escape(name), value, conf, flags=re.IGNORECASE)
        return conf

    def _handle_nicknames(self, pattern: str) -> str:
        clean = pattern.strip().lower()
        if clean == "@weekly" and self.alternative_weekdays:
            return "0 0 * * 1"  # Sunday is 1 with Quartz-style weekdays
        if clean == "@reboot":
            raise CronError(
                "CronPattern: @reboot is not supported in this environment. "
                "This is an event-based trigger that requires system startup detection."
            )
        return _NICKNAMES.get(clean, pattern)

    def _set_nth_weekday_of_month(self, index: int, nth) -> None:
        dow = self.day_of_week
        if isinstance(nth, str):
            if nth.upper() == "L":
                dow[index] |= LAST_OCCURRENCE
                return
            if _DIGITS.match(nth):
                nth = int(nth)
            else:
                raise CronError(
                    f"CronPattern: nth weekday out of range, should be 1-5 or L. Value: {nth}"
                )
        if nth == ANY_OCCURRENCE:
            dow[index] = ANY_OCCURRENCE
        elif 0 < nth < 6:
            dow[index] |= OCCURRENCE_BITMASKS[nth - 1]
        else:
            raise CronError(
                f"CronPattern: nth weekday out of range, should be 1-5 or L. Value: {nth}"
            )

    # ----------------------------------------------------------------- helpers

    def values(self, kind: str) -> List[int]:
        """Return the plain values set in a field, in the units used in patterns.

        ``kind`` is one of ``second``, ``minute``, ``hour``, ``day``, ``month``,
        ``day_of_week`` (0 = Sunday) or ``year``. Values selected only through
        ``L``, ``W`` or ``#`` are not included.
        """
        table = self._table(kind)
        base = 1 if kind in ("day", "month") else 0
        if kind == "day_of_week":
            return [i for i, v in enumerate(table) if v == ANY_OCCURRENCE]
        return [i + base for i, v in enumerate(table) if v]

    def __str__(self) -> str:
        return self.pattern

    def __repr__(self) -> str:
        return f"CronPattern({self.pattern!r})"
