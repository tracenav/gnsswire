"""Record tables of ANTEX 1.4: fixed columns, kept as text.

Source: "ANTEX: The Antenna Exchange Format, Version 1.4" (M. Rothacher,
R. Schmid, 15 September 2010), section 4, "ANTEX version 1.4 format
definitions": one table of every record, with its label (columns 61 to 80),
its description and its Fortran format.

A labelled line is a :class:`Record`: 60 columns of content and the label.
The content's layout depends on the label; ``TABLE`` gives, per label, the
frozen dataclass of its columns, and :func:`fields` cuts a record's content
into it. A field's value is the text in its columns, blanks included, so
that every column belongs to exactly one field and joining the fields gives
back the content. Nothing is converted; :func:`number` turns a numeric field
into the integer of its digits when the caller wants one.

How the table's formats are divided into fields:

- one field per item of the description, with the format printed on that
  item's rows, so skipped columns (``X``) that follow an item belong to it:
  the format version is ``F8.1,12X``, the number of calibrated antennas
  ``I6,4X``, the PCV type ``A1,19X``;
- skipped columns that lead a record belong to its first field (``2X,F6.1``
  for DAZI and ZEN1, ``3X,A1,I2`` for a frequency code);
- skipped columns that end a record are its ``blank`` field. They are kept,
  not checked.

The two unlabelled lines of a frequency section, the NOAZI row (``3X,A5,
mF8.2``) and an azimuth row (``F8.1,mF8.2``), are a :class:`Row`.
"""

from __future__ import annotations

import dataclasses
import re
import typing
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

T = TypeVar("T")


class Error(ValueError):
    """Base of every exception this codec raises for a file, a record or a field."""


class Invalid(Error):
    """The text is not an ANTEX file as section 4 of ANTEX 1.4 describes it."""


class Unsupported(Error, LookupError):
    """An ANTEX file of a format version this codec has no tables for."""


class Col:
    """A field of ``width`` columns, written in Fortran ``fmt`` in the table."""

    __slots__ = ("width", "fmt")

    def __init__(self, width: int, fmt: str) -> None:
        self.width = width
        self.fmt = fmt

    def __repr__(self) -> str:
        return f"Col({self.width}, {self.fmt!r})"


@dataclass(frozen=True, slots=True)
class Record:
    """One labelled line: 60 columns of content, the label in 61 to 80.

    A label may be shorter than 20 columns when the line's trailing blanks
    were cut. :func:`fields` reads the content by the label.
    """

    content: Annotated[str, Col(60, "A60")]
    label: Annotated[str, Col(20, "A20")]


# --- the content of each labelled record ------------------------------------------------

@dataclass(frozen=True, slots=True)
class Version:
    """ANTEX VERSION / SYST: ``F8.1,12X,A1,39X``.

    ``system`` is G (GPS), R (GLONASS), E (Galileo), C (Compass), J (QZSS),
    S (SBAS) or M (mixed).
    """

    version: Annotated[str, Col(20, "F8.1,12X")]
    system: Annotated[str, Col(1, "A1")]
    blank: Annotated[str, Col(39, "39X")] = " " * 39


@dataclass(frozen=True, slots=True)
class PcvType:
    """PCV TYPE / REFANT: ``A1,19X,A20,A20``.

    ``pcv_type`` is A (absolute values) or R (relative values); ``refant`` is
    the reference antenna type for relative values ("blank: AOAD/M_T") and
    ``refant_serial`` its serial number (optional).
    """

    pcv_type: Annotated[str, Col(20, "A1,19X")]
    refant: Annotated[str, Col(20, "A20")]
    refant_serial: Annotated[str, Col(20, "A20")]


@dataclass(frozen=True, slots=True)
class Comment:
    """COMMENT: ``A60``."""

    text: Annotated[str, Col(60, "A60")]


@dataclass(frozen=True, slots=True)
class Blank:
    """END OF HEADER, START OF ANTENNA and END OF ANTENNA: ``60X``."""

    blank: Annotated[str, Col(60, "60X")] = " " * 60


@dataclass(frozen=True, slots=True)
class TypeSerial:
    """TYPE / SERIAL NO: ``A20,A20,A10,A10``.

    Receiver antenna: ``type`` is the IGS antenna and radome code,
    ``serial`` the serial number ("blank: all representatives of the
    specified antenna type"), and ``svn`` and ``cospar`` are blank.
    Satellite antenna: ``type`` is the IGS satellite antenna code (``BLOCK
    IIA``), ``serial`` the satellite code "sNN" (``G05``; blank: all
    representatives), ``svn`` the satellite code "sNNN" (optional) and
    ``cospar`` the COSPAR ID "YYYY-XXXA" (optional).
    """

    type: Annotated[str, Col(20, "A20")]
    serial: Annotated[str, Col(20, "A20")]
    svn: Annotated[str, Col(10, "A10")]
    cospar: Annotated[str, Col(10, "A10")]


@dataclass(frozen=True, slots=True)
class Method:
    """METH / BY / # / DATE: ``A20,A20,I6,4X,A10``.

    ``method`` is CHAMBER, FIELD, ROBOT, COPIED, CONVERTED or blank;
    ``count`` the number of individual antennas calibrated.
    """

    method: Annotated[str, Col(20, "A20")]
    agency: Annotated[str, Col(20, "A20")]
    count: Annotated[str, Col(10, "I6,4X")]
    date: Annotated[str, Col(10, "A10")]


@dataclass(frozen=True, slots=True)
class Dazi:
    """DAZI: ``2X,F6.1,52X``. The increment of the azimuth in degrees; 0.0 for none."""

    dazi: Annotated[str, Col(8, "2X,F6.1")]
    blank: Annotated[str, Col(52, "52X")] = " " * 52


@dataclass(frozen=True, slots=True)
class Grid:
    """ZEN1 / ZEN2 / DZEN: ``2X,3F6.1,40X``.

    Zenith distance (receiver antenna) or nadir angle (satellite antenna)
    from ``zen1`` to ``zen2`` with increment ``dzen``, in degrees.
    """

    zen1: Annotated[str, Col(8, "2X,F6.1")]
    zen2: Annotated[str, Col(6, "F6.1")]
    dzen: Annotated[str, Col(6, "F6.1")]
    blank: Annotated[str, Col(40, "40X")] = " " * 40


@dataclass(frozen=True, slots=True)
class Frequencies:
    """# OF FREQUENCIES: ``I6,54X``."""

    count: Annotated[str, Col(6, "I6")]
    blank: Annotated[str, Col(54, "54X")] = " " * 54


@dataclass(frozen=True, slots=True)
class Epoch:
    """VALID FROM and VALID UNTIL: ``5I6,F13.7,17X``, in GPS time."""

    year: Annotated[str, Col(6, "I6")]
    month: Annotated[str, Col(6, "I6")]
    day: Annotated[str, Col(6, "I6")]
    hour: Annotated[str, Col(6, "I6")]
    minute: Annotated[str, Col(6, "I6")]
    second: Annotated[str, Col(13, "F13.7")]
    blank: Annotated[str, Col(17, "17X")] = " " * 17


@dataclass(frozen=True, slots=True)
class SinexCode:
    """SINEX CODE: ``A10,50X``."""

    code: Annotated[str, Col(10, "A10")]
    blank: Annotated[str, Col(50, "50X")] = " " * 50


@dataclass(frozen=True, slots=True)
class FrequencyCode:
    """START OF FREQUENCY, END OF FREQUENCY, START OF FREQ RMS, END OF FREQ RMS.

    ``3X,A1,I2,54X``: the satellite system flag and the frequency number,
    ``G01``, after three blanks.
    """

    code: Annotated[str, Col(6, "3X,A1,I2")]
    blank: Annotated[str, Col(54, "54X")] = " " * 54


@dataclass(frozen=True, slots=True)
class Offset:
    """NORTH / EAST / UP: ``3F10.2,30X``, in millimetres.

    Receiver antenna: the mean phase centre relative to the antenna
    reference point, north, east and up. Satellite antenna: relative to the
    centre of mass, in X, Y and Z, in the same three fields. In an rms
    section, the rms of those.
    """

    north: Annotated[str, Col(10, "F10.2")]
    east: Annotated[str, Col(10, "F10.2")]
    up: Annotated[str, Col(10, "F10.2")]
    blank: Annotated[str, Col(30, "30X")] = " " * 30


VERSION = "ANTEX VERSION / SYST"
PCV_TYPE = "PCV TYPE / REFANT"
COMMENT = "COMMENT"
END_OF_HEADER = "END OF HEADER"
START_OF_ANTENNA = "START OF ANTENNA"
TYPE_SERIAL = "TYPE / SERIAL NO"
METHOD = "METH / BY / # / DATE"
DAZI = "DAZI"
GRID = "ZEN1 / ZEN2 / DZEN"
FREQUENCIES_COUNT = "# OF FREQUENCIES"
VALID_FROM = "VALID FROM"
VALID_UNTIL = "VALID UNTIL"
SINEX_CODE = "SINEX CODE"
START_OF_FREQUENCY = "START OF FREQUENCY"
OFFSET = "NORTH / EAST / UP"
END_OF_FREQUENCY = "END OF FREQUENCY"
START_OF_FREQ_RMS = "START OF FREQ RMS"
END_OF_FREQ_RMS = "END OF FREQ RMS"
END_OF_ANTENNA = "END OF ANTENNA"

# Every label of section 4, in the table's order, with the columns of its content.
TABLE: dict[str, type] = {
    VERSION: Version,
    PCV_TYPE: PcvType,
    COMMENT: Comment,
    END_OF_HEADER: Blank,
    START_OF_ANTENNA: Blank,
    TYPE_SERIAL: TypeSerial,
    METHOD: Method,
    DAZI: Dazi,
    GRID: Grid,
    FREQUENCIES_COUNT: Frequencies,
    VALID_FROM: Epoch,
    VALID_UNTIL: Epoch,
    SINEX_CODE: SinexCode,
    START_OF_FREQUENCY: FrequencyCode,
    OFFSET: Offset,
    END_OF_FREQUENCY: FrequencyCode,
    START_OF_FREQ_RMS: FrequencyCode,
    END_OF_FREQ_RMS: FrequencyCode,
    END_OF_ANTENNA: Blank,
}

NOAZI = "   NOAZI"   # 3X,A5


@dataclass(frozen=True, slots=True)
class Row:
    """One line of pattern values, in millimetres, from ZEN1 to ZEN2.

    ``azimuth`` is the line's first eight columns: ``"   NOAZI"`` (``3X,A5``)
    for the non-azimuth-dependent pattern, otherwise the azimuth angle
    (``F8.1``). ``values`` are the ``mF8.2`` fields after it, one per zenith
    (or nadir) angle of the antenna's grid. ``trailing`` holds blanks that
    follow the last value in the file, if any.
    """

    azimuth: str
    values: tuple[str, ...]
    trailing: str = ""


def columns(cls: type) -> tuple[tuple[str, Col], ...]:
    """The fields of a record dataclass with their columns, in order."""
    hints = typing.get_type_hints(cls, include_extras=True)
    out = []
    for f in dataclasses.fields(cls):
        meta = [m for m in getattr(hints[f.name], "__metadata__", ()) if isinstance(m, Col)]
        if len(meta) != 1:
            raise TypeError(f"{cls.__qualname__}.{f.name}: needs exactly one Col")
        out.append((f.name, meta[0]))
    return tuple(out)


_WIDTHS: dict[type, tuple[int, ...]] = {}


def cut(cls: type[T], text: str) -> T:
    """Split ``text`` into the fields of ``cls``, which it must fill exactly."""
    widths = _WIDTHS.get(cls)
    if widths is None:
        widths = _WIDTHS[cls] = tuple(col.width for _, col in columns(cls))
    if len(text) != sum(widths):
        raise Invalid(f"{cls.__qualname__}: {len(text)} columns, needs {sum(widths)}")
    values = []
    at = 0
    for width in widths:
        values.append(text[at:at + width])
        at += width
    return cls(*values)


def join(record: Any) -> str:
    """The text of a record: its fields joined, each as wide as its columns."""
    out = []
    for name, col in columns(type(record)):
        value = getattr(record, name)
        where = f"{type(record).__qualname__}.{name}"
        if not isinstance(value, str):
            raise Invalid(f"{where}: needs a str, got {value!r}")
        if "\n" in value or "\r" in value:
            raise Invalid(f"{where}: holds a line break")
        if len(value) != col.width:
            raise Invalid(f"{where}: {value!r} is not {col.width} columns")
        out.append(value)
    return "".join(out)


def label(record: Record) -> str:
    """A record's label without its trailing blanks."""
    return record.label.rstrip()


def fields(record: Record) -> Any:
    """The content of ``record`` as the columns ``TABLE`` gives its label.

    ``fields(Record("BLOCK IIA".ljust(20) + "G01".ljust(40), "TYPE / SERIAL NO"))``
    is a :class:`TypeSerial`. A label that is not in the table is
    :class:`Invalid`.
    """
    cls = TABLE.get(label(record))
    if cls is None:
        raise Invalid(f"{record.label!r} is not a label of ANTEX 1.4")
    return cut(cls, record.content)


def record(label: str, content: Any = Blank()) -> Record:
    """The :class:`Record` of ``label`` whose content is the fields ``content``.

    ``record("DAZI", Dazi("     5.0"))``; the label is padded to 20 columns.
    ``content`` must be of the class ``TABLE`` gives the label.
    """
    cls = TABLE.get(label)
    if cls is None:
        raise Invalid(f"{label!r} is not a label of ANTEX 1.4")
    if type(content) is not cls:
        raise Invalid(f"{label}: needs a {cls.__qualname__}, got {content!r}")
    return Record(join(content), label.ljust(20))


_NUMBER = re.compile(r" *([+-]?)(\d*)(?:\.(\d*))?")


def number(field: str, decimals: int = 0) -> int | None:
    """A numeric field as the integer of its digits, in units of 10**-decimals.

    ``number("     -0.87", 2) == -87`` (a NORTH / EAST / UP field, in units
    of 0.01 mm); ``number("    90.0", 1) == 900``; ``number("     3", 0) ==
    3``. A blank field is ``None``. The field must have exactly ``decimals``
    digits after the point (none, and no point, for ``decimals=0``), as its
    Fortran format writes them. Blanks around the number are not counted.
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
