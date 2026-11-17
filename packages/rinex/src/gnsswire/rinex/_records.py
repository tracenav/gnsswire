"""Record tables of RINEX 3 and 4 observation files: fixed columns, kept as text.

Sources: RINEX 3.05 (IGS/RTCM RINEX WG, 1 December 2020) and RINEX 4.02
(IGS/RTCM RINEX Committee, 1 October 2024), Table A2 ("GNSS observation data
file - header section description") and Table A3 ("GNSS observation data
file - data record description"), and sections 6.3 to 6.7 of 3.05.

Each record is a frozen dataclass whose fields are the record's columns, in
order, each with its width and its Fortran format from the table in
``typing.Annotated`` metadata. A field's value is the text in its columns,
leading blanks included: a format such as ``1X,I4`` is one 5-column field,
so that every column of a record belongs to exactly one field and joining
the fields gives back the line. Nothing is converted; ``number`` turns a
numeric field into an integer of its digits when the caller wants one.

Trailing fields may be missing or short, because "trailing blanks may be
truncated from the record" (3.05 section 6.5) and "empty data fields at the
end of a record may be missing" (section 6.3): a field past the end of the
line is ``""``, a field cut by it is the part that is there.
"""

from __future__ import annotations

import dataclasses
import functools
import re
import typing
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

T = TypeVar("T")


class Error(ValueError):
    """Base of every exception this codec raises for a file, a record or a field."""


class Invalid(Error):
    """The text is not a RINEX file of the kind being read as the tables describe it."""


class Unsupported(Error, LookupError):
    """A RINEX file this codec has no tables for: another version or file type."""


class Col:
    """A field of ``width`` columns, written in Fortran ``fmt`` in the table."""

    __slots__ = ("width", "fmt")

    def __init__(self, width: int, fmt: str) -> None:
        self.width = width
        self.fmt = fmt

    def __repr__(self) -> str:
        return f"Col({self.width}, {self.fmt!r})"


@dataclass(frozen=True, slots=True)
class HeaderRecord:
    """One header line (Table A2): 60 columns of content, the label in 61 to 80.

    The content's layout depends on the label; :func:`obs_types` reads the
    one record this codec needs, SYS / # / OBS TYPES. A label may be short
    when the line's trailing blanks were truncated.
    """

    content: Annotated[str, Col(60, "A60")]
    label: Annotated[str, Col(20, "A20")]


@dataclass(frozen=True, slots=True)
class EpochRecord:
    """The EPOCH record of Table A3, after its record identifier ``>``.

    ``picoseconds`` ("additional 5 digits to append to 'seconds'", ``1X,I5.5``)
    is in RINEX 4.02 only; it is ``""`` in a RINEX 3 file. For flags 0, 1
    and 6, ``count`` is the number of satellite records that follow, for
    flags 2 to 5 the number of special records.
    """

    year: Annotated[str, Col(5, "1X,I4")]
    month: Annotated[str, Col(3, "1X,I2.2")]
    day: Annotated[str, Col(3, "1X,I2.2")]
    hour: Annotated[str, Col(3, "1X,I2.2")]
    minute: Annotated[str, Col(3, "1X,I2.2")]
    second: Annotated[str, Col(11, "F11.7")]
    flag: Annotated[str, Col(3, "2X,I1")]
    count: Annotated[str, Col(3, "I3")]
    reserved: Annotated[str, Col(6, "6X")]
    clock: Annotated[str, Col(15, "F15.12")]
    picoseconds: Annotated[str, Col(6, "1X,I5.5")]


@dataclass(frozen=True, slots=True)
class Observation:
    """One observation of a satellite record: ``F14.3,I1,I1`` (Table A3, section 6.7).

    ``lli`` is the loss of lock indicator, ``ssi`` the signal strength
    indicator, each one digit or blank.
    """

    value: Annotated[str, Col(14, "F14.3")]
    lli: Annotated[str, Col(1, "I1")]
    ssi: Annotated[str, Col(1, "I1")]


@dataclass(frozen=True, slots=True)
class SatelliteRecord:
    """An OBSERVATION record (or, under flag 6, a cycle slip record) of Table A3.

    ``sat`` is the satellite number, ``A1,I2.2`` (``G06``); ``obs`` holds the
    observations in the order of the system's SYS / # / OBS TYPES record. It
    may be shorter than that list when the record's trailing fields are
    missing, and its last observation may be cut short.
    """

    sat: str
    obs: tuple[Observation, ...]


@functools.cache
def columns(cls: type) -> tuple[tuple[str, Col], ...]:
    """The fields of a record dataclass with their columns, in order.

    Kept per class once read: the layout of a class does not change, and
    every line of a file asks for it.
    """
    hints = typing.get_type_hints(cls, include_extras=True)
    out = []
    for f in dataclasses.fields(cls):
        meta = [m for m in getattr(hints[f.name], "__metadata__", ()) if isinstance(m, Col)]
        if len(meta) != 1:
            raise TypeError(f"{cls.__qualname__}.{f.name}: needs exactly one Col")
        out.append((f.name, meta[0]))
    return tuple(out)


def cut(cls: type[T], text: str) -> T:
    """Split ``text`` into the fields of ``cls``; text past the last field is refused."""
    values = {}
    at = 0
    for name, col in columns(cls):
        values[name] = text[at:at + col.width]
        at += col.width
    if len(text) > at:
        raise Invalid(f"{cls.__qualname__}: {len(text) - at} characters past column {at}")
    return cls(**values)


def join(record: Any) -> str:
    """The text of a record: its fields joined. Only trailing fields may be short."""
    out = []
    short = None
    for name, col in columns(type(record)):
        value = getattr(record, name)
        where = f"{type(record).__qualname__}.{name}"
        if not isinstance(value, str):
            raise Invalid(f"{where}: needs a str, got {value!r}")
        if "\n" in value or "\r" in value:
            raise Invalid(f"{where}: holds a line break")
        if len(value) > col.width:
            raise Invalid(f"{where}: {value!r} is wider than {col.width} columns")
        if value and short is not None:
            raise Invalid(f"{where}: follows {short}, which is short")
        if len(value) < col.width:
            short = short or where
        out.append(value)
    return "".join(out)


_NUMBER = re.compile(r" *([+-]?)(\d*)(?:\.(\d*))?")


def number(field: str, decimals: int = 0) -> int | None:
    """A numeric field as the integer of its digits, in units of 10**-decimals.

    ``number("  23629347.915", 3) == 23629347915``; ``number("    -.353", 3)
    == -353``; ``number("  0", 0) == 0``. A blank field is ``None``. The
    field must have exactly ``decimals`` digits after the point (none, and no
    point, for ``decimals=0``), as its Fortran format writes them.
    """
    if not field.strip():
        return None
    m = _NUMBER.fullmatch(field.rstrip())
    if m is None or not (m[2] or m[3]):
        raise Error(f"{field!r} is not a number")
    sign, whole, frac = m[1], m[2], m[3]
    if (frac is None and decimals) or (frac is not None and len(frac) != decimals) or (
            frac is not None and decimals == 0):
        raise Error(f"{field!r} does not have {decimals} decimals")
    value = int((whole or "0") + (frac or ""))
    return -value if sign == "-" else value
