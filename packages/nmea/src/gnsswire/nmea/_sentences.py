"""Sentence tables: GGA and ZDA, every field kept as the string on the wire.

Each class is the "Payload" table of the u-blox F9 HPG 1.51 Interface
Description (UBXDOC-963802114-13124 R01) cited in its docstring, which stands in for
NMEA 0183 v4.11 (sold by the NMEA, not freely available). Rows are in field order; the metadata string of
each row is the spec's field name. Field 0 of every table is the address
(``xxGGA``, "xx = current Talker ID"), kept here as ``talker``; the checksum
and CR LF rows are framing (``_frame``) and are not fields.

No numeric conversion: ``"08"`` stays ``"08"`` and a null field stays ``""``,
so ``encode(decode(frame))`` gives back the frame's bytes. Consumers differ on
how to parse numbers, so that is left to them.

Talker ID (section 2.5.1, "a two-letter message identifier"): any two
uppercase letters are accepted, not only the ones the table lists, because
section 2.4 says GGA is sent "for each of the Talker IDs" and other receivers
use others. AMBIGUOUS: an address starting with ``P`` is a proprietary
sentence (section 2.3, a manufacturer mnemonic after the ``P``), so
``PxGGA`` is not read as a GGA; NMEA 0183 defines no talker starting with
``P`` that the u-blox document mentions.

Field count: the "Number of fields" of each table counts the address,
checksum and CR LF; the data fields are that number minus three. The count
depends on the NMEA version a receiver speaks: the document's own position
fix flags section says that in NMEA 2.1 and earlier "the posMode field is
not output for GLL, RMC and VTG messages (each message has one field
less)", and later versions append fields (systemId, signalId). So
:func:`unpack` reads a sentence with fewer data fields than its table with
the missing trailing fields ``None`` (absent, which is not the empty
string of a null field), and one with more with the extra fields in
``extra``; :func:`pack` writes both back, so the round trip holds. With
``strict=True`` only the table's own count is accepted.
"""

from dataclasses import dataclass, field, fields
from typing import ClassVar

from ._frame import Error


class FieldError(Error):
    """A sentence, or a message to encode, does not fit its table."""


def _row(name: str):
    """One table row: ``name`` is the field name the spec prints."""
    return field(metadata={"spec": name})


def _extra():
    """Data fields after the table's last, as received (``()`` for none)."""
    return field(default=(), metadata={"extra": True})


@dataclass(frozen=True, slots=True)
class Gga:
    """NMEA-Standard-GGA, global positioning system fix data.

    Section 2.7.5.1: "Number of fields: 17", so 14 data fields. The
    secondary-output variant NMEA-NAV2-GGA (section 2.8.1.1) is the same
    sentence after a TAG block, which is not part of the sentence (see
    ``_frame``).
    """

    FORMATTER: ClassVar[str] = "GGA"
    SECTION: ClassVar[str] = "2.7.5.1"
    NUMBER_OF_FIELDS: ClassVar[int] = 17

    talker: str = _row("xx")
    time: str | None = _row("time")               # hhmmss.ss, UTC
    lat: str | None = _row("lat")                 # ddmm.mmmmm
    ns: str | None = _row("NS")
    lon: str | None = _row("lon")                 # dddmm.mmmmm
    ew: str | None = _row("EW")
    quality: str | None = _row("quality")         # digit, section 2.5.5
    num_sv: str | None = _row("numSV")
    hdop: str | None = _row("HDOP")
    alt: str | None = _row("alt")
    alt_unit: str | None = _row("altUnit")
    sep: str | None = _row("sep")
    sep_unit: str | None = _row("sepUnit")
    diff_age: str | None = _row("diffAge")        # null when DGPS is not used
    diff_station: str | None = _row("diffStation")   # null when DGPS is not used
    extra: tuple[str, ...] = _extra()


@dataclass(frozen=True, slots=True)
class Zda:
    """NMEA-Standard-ZDA, time and date.

    Section 2.7.21.1: "Number of fields: 9", so 6 data fields. The
    secondary-output variant NMEA-NAV2-ZDA is section 2.8.7.1.
    """

    FORMATTER: ClassVar[str] = "ZDA"
    SECTION: ClassVar[str] = "2.7.21.1"
    NUMBER_OF_FIELDS: ClassVar[int] = 9

    talker: str = _row("xx")
    time: str | None = _row("time")               # hhmmss.ss, UTC
    day: str | None = _row("day")
    month: str | None = _row("month")
    year: str | None = _row("year")
    ltzh: str | None = _row("ltzh")               # "fixed field, always 00" on u-blox
    ltzn: str | None = _row("ltzn")               # same
    extra: tuple[str, ...] = _extra()


SENTENCES: tuple[type, ...] = (Gga, Zda)


def _rows(cls: type) -> tuple:
    """The table's rows, address first, without ``extra``."""
    return tuple(f for f in fields(cls) if "spec" in f.metadata)


def spec_names(cls: type) -> list[str]:
    """The table's field names as the spec prints them, address first."""
    return [f.metadata["spec"] for f in _rows(cls)]


def is_talker(text: str) -> bool:
    return len(text) == 2 and text.isascii() and text.isalpha() and text.isupper() \
        and text[0] != "P"


# A data field may hold printable ASCII other than the delimiters '$', '*'
# and ','; the first two are the framing's rule (``_frame``), the comma
# separates fields.
_FIELD_CHARS = frozenset(range(0x20, 0x7F)) - set(b"$*,")


def unpack(cls: type, talker: str, values: list[str], *, strict: bool = False):
    width = len(_rows(cls)) - 1
    if len(values) != width and strict:
        raise FieldError(f"{cls.FORMATTER}: {len(values)} data fields, section {cls.SECTION} "
                         f"has {width}")
    present = values[:width]
    return cls(talker, *present, *[None] * (width - len(present)), tuple(values[width:]))


def pack(message) -> bytes:
    cls = type(message)
    rows = _rows(cls)
    values = [getattr(message, f.name) for f in rows]
    extra = message.extra
    if not isinstance(message.talker, str):
        raise FieldError(f"{cls.FORMATTER}.talker: {message.talker!r} is not a string")
    if not isinstance(extra, tuple) or not all(isinstance(v, str) for v in extra):
        raise FieldError(f"{cls.FORMATTER}.extra: {extra!r} is not a tuple of strings")
    absent = False
    for f, value in zip(rows[1:], values[1:]):
        if value is None:
            absent = True
        elif not isinstance(value, str):
            raise FieldError(f"{cls.FORMATTER}.{f.name}: {value!r} is not a string or None")
        elif absent:
            raise FieldError(f"{cls.FORMATTER}.{f.name}: a field after an absent (None) "
                             f"field must be absent too")
    if absent and extra:
        raise FieldError(f"{cls.FORMATTER}: extra fields after an absent (None) field")
    if not is_talker(message.talker):
        raise FieldError(f"{cls.FORMATTER}: talker {message.talker!r} is not two uppercase "
                         f"letters (not starting with P)")
    data = [v for v in values[1:] if v is not None] + list(extra)
    for value in data:
        if not value.isascii() or not set(value.encode()) <= _FIELD_CHARS:
            raise FieldError(f"{cls.FORMATTER}: {value!r} holds a character a field cannot")
    return ",".join([message.talker + cls.FORMATTER, *data]).encode("ascii")
