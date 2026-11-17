"""ANTEX files: :func:`read` and :func:`write`.

Source: ANTEX 1.4 (Rothacher and Schmid, 15 September 2010), section 4. The
table there gives the records in the order they are written; records
marked ``*`` are optional, and comments are "only allowed at the specified
position". The file structure, as that table orders it:

- the header: ANTEX VERSION / SYST, PCV TYPE / REFANT, COMMENT lines (*),
  END OF HEADER;
- then antenna sections, each:

  - START OF ANTENNA, TYPE / SERIAL NO, METH / BY / # / DATE, DAZI,
    ZEN1 / ZEN2 / DZEN, # OF FREQUENCIES, VALID FROM (*), VALID UNTIL (*),
    SINEX CODE (*), COMMENT lines (*);
  - frequency sections: START OF FREQUENCY, NORTH / EAST / UP, the NOAZI
    row, the azimuth rows when DAZI is above 0.0, END OF FREQUENCY
    ("neither other types of records nor comment lines are allowed within
    this section");
  - rms sections (*), laid out as frequency sections between START OF FREQ
    RMS and END OF FREQ RMS;
  - END OF ANTENNA.

The grid, from the DAZI and ZEN1 / ZEN2 / DZEN descriptions: a row holds
(ZEN2 - ZEN1) / DZEN + 1 values ("from 'ZEN1' to 'ZEN2' (with increment
'DZEN')"), and there are 360 / DAZI + 1 azimuth rows ("0 to 360 with
increment 'DAZI'"), none for DAZI 0.0. DZEN "has to be > 0.0", ZEN1 and ZEN2
"always have to be multiples of 'DZEN'", ZEN2 "always has to be greater
than 'ZEN1'" and "360 degrees have to be divisible by 'DAZI'"; a file that
breaks one of these, or whose rows disagree with its grid, is refused.

Readings this codec makes where the document leaves room:

- Where an rms section goes is not said beyond its place in the table,
  after END OF FREQUENCY. It is accepted anywhere after the frequency
  section of the same code: straight after it, or after all frequency
  sections. At most one per frequency.
- # OF FREQUENCIES counts the frequency sections; rms sections are not
  counted. Two frequency sections of one code in an antenna are refused.
- A frequency code is a letter and two digits (``A1,I2``), the same in the
  START and END records of its section. The document's list of codes
  (``FREQUENCIES``) is not enforced: it says the frequency number "has to
  be consistent with the RINEX definition", and files of the IGS carry
  codes of later RINEX versions (``C05``, ``I05``) under format version
  1.4.
- The header's satellite system must be one the document lists, and the
  PCV type A or R. The format version must be 1.4 (:class:`Unsupported`
  otherwise).
- A row's azimuth must be the one its position gives; pattern values and
  every other field are kept as the text in their columns, unread.
- Blanks after a row's last value are kept (``Row.trailing``); a labelled
  line may end anywhere in its label, as when trailing blanks were cut,
  and has at most 80 columns.
- Lines end in LF or CR LF, the same throughout a file; the file's line
  ending and whether its last line has one are kept, so that ``write(read(
  text)) == text``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._records import (
    COMMENT,
    DAZI,
    END_OF_ANTENNA,
    END_OF_FREQ_RMS,
    END_OF_FREQUENCY,
    END_OF_HEADER,
    FREQUENCIES_COUNT,
    GRID,
    METHOD,
    NOAZI,
    OFFSET,
    PCV_TYPE,
    SINEX_CODE,
    START_OF_ANTENNA,
    START_OF_FREQ_RMS,
    START_OF_FREQUENCY,
    TYPE_SERIAL,
    VALID_FROM,
    VALID_UNTIL,
    VERSION,
    Epoch,
    Error,
    Grid,
    Invalid,
    Method,
    Offset,
    PcvType,
    Record,
    Row,
    TypeSerial,
    Unsupported,
    cut,
    label,
    number,
)
from ._records import Version as _Version

# Satellite system flags of TYPE / SERIAL NO and START OF FREQUENCY; the
# header's ANTEX VERSION / SYST also allows M, mixed.
SYSTEMS = "GRECJS"   # GPS, GLONASS, Galileo, Compass, QZSS, SBAS
# The frequency number codes the START OF FREQUENCY description lists.
FREQUENCIES = {
    "G01": "L1", "G02": "L2", "G05": "L5",
    "R01": "G1", "R02": "G2",
    "E01": "E1", "E05": "E5a", "E07": "E5b", "E08": "E5 (E5a+E5b)", "E06": "E6",
    "C01": "E1", "C02": "E2", "C07": "E5b", "C06": "E6",
    "J01": "L1", "J02": "L2", "J05": "L5", "J06": "LEX",
    "S01": "L1", "S05": "L5",
}
FORMAT_VERSION = 14   # 1.4, in tenths

_CODE = re.compile(r"[A-Z][0-9]{2}")


@dataclass(frozen=True, slots=True)
class Pattern:
    """A frequency section, or an rms section: offsets and pattern values.

    ``start`` is START OF FREQUENCY (START OF FREQ RMS for an rms section),
    ``neu`` the NORTH / EAST / UP record, ``noazi`` the non-azimuth-dependent
    row, ``rows`` the azimuth rows (none when the antenna's DAZI is 0.0),
    from azimuth 0.0 to 360.0, and ``end`` the END record.
    """

    start: Record
    neu: Record
    noazi: Row
    rows: tuple[Row, ...]
    end: Record

    @property
    def code(self) -> str:
        """The frequency code, such as ``G01``: columns 4 to 6 of ``start``."""
        return self.start.content[3:6]

    @property
    def rms(self) -> bool:
        """Whether this is an rms section (START OF FREQ RMS)."""
        return label(self.start) == START_OF_FREQ_RMS

    @property
    def offset(self) -> Offset:
        """The NORTH / EAST / UP fields (X, Y and Z for a satellite antenna)."""
        return cut(Offset, self.neu.content)


def _find(records: tuple[Record, ...], name: str) -> Record | None:
    for r in records:
        if label(r) == name:
            return r
    return None


def _need(records: tuple[Record, ...], name: str) -> Record:
    r = _find(records, name)
    if r is None:
        raise Invalid(f"no {name} record")
    return r


def _tenths(field: str, what: str) -> int:
    try:
        value = number(field, 1)
    except Error:
        value = None
    if value is None:
        raise Invalid(f"{what} {field!r} is not a number with one decimal")
    return value


def _grid(dazi: Record, grid: Record) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """(zenith angles, azimuth angles) in units of 0.1 degree; no azimuths for DAZI 0.0."""
    g = cut(Grid, grid.content)
    zen1, zen2, dzen = _tenths(g.zen1, "ZEN1"), _tenths(g.zen2, "ZEN2"), _tenths(g.dzen, "DZEN")
    if dzen <= 0:
        raise Invalid(f"DZEN {g.dzen!r} has to be > 0.0")
    if zen1 % dzen or zen2 % dzen:
        raise Invalid(f"ZEN1 {g.zen1!r} and ZEN2 {g.zen2!r} have to be multiples of "
                      f"DZEN {g.dzen!r}")
    if zen2 <= zen1:
        raise Invalid(f"ZEN2 {g.zen2!r} has to be greater than ZEN1 {g.zen1!r}")
    step = _tenths(dazi.content[:8], "DAZI")
    if step < 0 or (step and 3600 % step):
        raise Invalid(f"360 degrees have to be divisible by DAZI {dazi.content[:8]!r}")
    return (tuple(range(zen1, zen2 + 1, dzen)),
            tuple(range(0, 3601, step)) if step else ())


@dataclass(frozen=True, slots=True)
class Antenna:
    """One antenna section, START OF ANTENNA to END OF ANTENNA.

    ``records`` are the labelled lines from START OF ANTENNA to the last one
    before the first frequency section; ``patterns`` the frequency and rms
    sections in the file's order; ``end`` is END OF ANTENNA. The properties
    read ``records``.
    """

    records: tuple[Record, ...]
    patterns: tuple[Pattern, ...]
    end: Record

    @property
    def type_serial(self) -> TypeSerial:
        """The TYPE / SERIAL NO fields: type, serial and, for a satellite, SVN and COSPAR ID."""
        return cut(TypeSerial, _need(self.records, TYPE_SERIAL).content)

    @property
    def type(self) -> str:
        """The antenna type, columns 1 to 20 of TYPE / SERIAL NO, as written."""
        return _need(self.records, TYPE_SERIAL).content[:20]

    @property
    def serial(self) -> str:
        """The serial number, or a satellite's code "sNN": columns 21 to 40, as written.

        Blank for "all representatives of the specified antenna type".
        """
        return _need(self.records, TYPE_SERIAL).content[20:40]

    @property
    def method(self) -> Method:
        """The METH / BY / # / DATE fields."""
        return cut(Method, _need(self.records, METHOD).content)

    @property
    def dazi(self) -> str:
        """The azimuth increment in degrees (``2X,F6.1``); 0.0 for a NOAZI-only antenna."""
        return _need(self.records, DAZI).content[:8]

    @property
    def grid(self) -> Grid:
        """The ZEN1 / ZEN2 / DZEN fields, in degrees."""
        return cut(Grid, _need(self.records, GRID).content)

    @property
    def zeniths(self) -> tuple[int, ...]:
        """The zenith (satellite: nadir) angle of each value of a row, in units of 0.1 degree."""
        return _grid(_need(self.records, DAZI), _need(self.records, GRID))[0]

    @property
    def azimuths(self) -> tuple[int, ...]:
        """The azimuth of each of a pattern's ``rows``, in units of 0.1 degree."""
        return _grid(_need(self.records, DAZI), _need(self.records, GRID))[1]

    @property
    def valid_from(self) -> Epoch | None:
        """The VALID FROM fields (GPS time), or ``None`` without the record."""
        r = _find(self.records, VALID_FROM)
        return None if r is None else cut(Epoch, r.content)

    @property
    def valid_until(self) -> Epoch | None:
        """The VALID UNTIL fields (GPS time), or ``None`` without the record."""
        r = _find(self.records, VALID_UNTIL)
        return None if r is None else cut(Epoch, r.content)

    @property
    def sinex_code(self) -> str | None:
        """Columns 1 to 10 of SINEX CODE, or ``None`` without the record."""
        r = _find(self.records, SINEX_CODE)
        return None if r is None else r.content[:10]

    @property
    def comments(self) -> tuple[str, ...]:
        """The content of each COMMENT record."""
        return tuple(r.content for r in self.records if label(r) == COMMENT)

    @property
    def frequencies(self) -> dict[str, Pattern]:
        """The frequency sections by code (``G01``), in the file's order."""
        return {p.code: p for p in self.patterns if not p.rms}

    @property
    def rms(self) -> dict[str, Pattern]:
        """The rms sections by frequency code; empty when the antenna has none."""
        return {p.code: p for p in self.patterns if p.rms}


@dataclass(frozen=True, slots=True)
class AntexFile:
    """A whole ANTEX file."""

    header: tuple[Record, ...]         # ANTEX VERSION / SYST to END OF HEADER
    antennas: tuple[Antenna, ...]
    newline: str = "\n"                # "\n" or "\r\n"
    final_newline: bool = True         # whether the last line ends with ``newline``

    @property
    def version(self) -> str:
        """The format version, columns 1 to 8 of ANTEX VERSION / SYST, stripped."""
        return self.header[0].content[:8].strip()

    @property
    def system(self) -> str:
        """The satellite system, column 21 of ANTEX VERSION / SYST: G, R, E, C, J, S or M."""
        return self.header[0].content[20:21]

    @property
    def pcv_type(self) -> PcvType:
        """The PCV TYPE / REFANT fields."""
        return cut(PcvType, self.header[1].content)

    @property
    def comments(self) -> tuple[str, ...]:
        """The content of each COMMENT record of the header."""
        return tuple(r.content for r in self.header if label(r) == COMMENT)


class _Lines:
    """The lines of a file and a position in them."""

    __slots__ = ("lines", "at")

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.at = 0

    def where(self) -> str:
        return f"line {self.at + 1}"

    def line(self, what: str) -> str:
        if self.at == len(self.lines):
            raise Invalid(f"the file ends where {what} is expected")
        line = self.lines[self.at]
        self.at += 1
        return line

    def label(self) -> str:
        """The label of the next line; "" at the end of the file or without one."""
        if self.at == len(self.lines):
            return ""
        return self.lines[self.at][60:80].rstrip()

    def record(self, name: str) -> Record:
        """The next line, which must be a record labelled ``name``."""
        line = self.line(name)
        if not 60 < len(line) <= 80 or line[60:].rstrip() != name:
            self.at -= 1
            found = line[60:].rstrip() if 60 < len(line) <= 80 else line[:80]
            raise Invalid(f"{self.where()}: expected {name} in columns 61 to 80, "
                          f"found {found!r}")
        return Record(line[:60], line[60:])

    def records(self, name: str, out: list[Record]) -> None:
        """Every next line labelled ``name``, appended to ``out``."""
        while self.label() == name:
            out.append(self.record(name))


def _row(lines: _Lines, width: int, azimuth: int | None) -> Row:
    """A row of ``width`` columns; ``azimuth`` in 0.1 degree, or ``None`` for NOAZI."""
    what = "the NOAZI row" if azimuth is None else f"the row of azimuth {azimuth // 10}.{azimuth % 10}"
    line = lines.line(what)
    first = line[:8]
    if azimuth is None:
        ok = first == NOAZI
    else:
        try:
            ok = number(first, 1) == azimuth
        except Error:
            ok = False
    if not ok:
        lines.at -= 1
        raise Invalid(f"{lines.where()}: expected {what}, found {line[:80]!r}")
    if len(line) < width or (len(line) > width and line[width:].strip(" ")):
        lines.at -= 1
        raise Invalid(f"{lines.where()}: {what} needs {(width - 8) // 8} values of 8 columns "
                      f"after its first 8, and has {len(line)} columns")
    return Row(first, tuple([line[k:k + 8] for k in range(8, width, 8)]), line[width:])


def _pattern(lines: _Lines, width: int, azimuths: tuple[int, ...]) -> Pattern:
    rms = lines.label() == START_OF_FREQ_RMS
    start = lines.record(START_OF_FREQ_RMS if rms else START_OF_FREQUENCY)
    code = start.content[3:6]
    if not _CODE.fullmatch(code):
        lines.at -= 1
        raise Invalid(f"{lines.where()}: {start.content[:6]!r} is not a frequency code "
                      "(3X,A1,I2), such as '   G01'")
    neu = lines.record(OFFSET)
    noazi = _row(lines, width, None)
    rows = tuple([_row(lines, width, azimuth) for azimuth in azimuths])
    end = lines.record(END_OF_FREQ_RMS if rms else END_OF_FREQUENCY)
    if end.content[3:6] != code:
        lines.at -= 1
        raise Invalid(f"{lines.where()}: {label(end)} of {end.content[3:6]!r} ends the "
                      f"section of {code!r}")
    return Pattern(start, neu, noazi, rows, end)


def _antenna(lines: _Lines) -> Antenna:
    at = lines.at
    records = [lines.record(START_OF_ANTENNA)]
    for name in (TYPE_SERIAL, METHOD, DAZI, GRID, FREQUENCIES_COUNT):
        records.append(lines.record(name))
    for name in (VALID_FROM, VALID_UNTIL, SINEX_CODE):
        if lines.label() == name:
            records.append(lines.record(name))
    lines.records(COMMENT, records)
    where = f"the antenna of line {at + 1}"
    try:
        zeniths, azimuths = _grid(records[3], records[4])
    except Invalid as e:
        raise Invalid(f"{where}: {e}") from None
    count = records[5].content[:6].strip()
    if not count.isdigit():
        raise Invalid(f"{where}: {FREQUENCIES_COUNT} {records[5].content[:6]!r} is not I6")
    width = 8 + 8 * len(zeniths)
    patterns: list[Pattern] = []
    seen: set[tuple[str, bool]] = set()
    while lines.label() in (START_OF_FREQUENCY, START_OF_FREQ_RMS):
        p = _pattern(lines, width, azimuths)
        key = (p.code, p.rms)
        if key in seen:
            raise Invalid(f"{where}: two {label(p.start)} sections of {p.code}")
        if p.rms and (p.code, False) not in seen:
            raise Invalid(f"{where}: {START_OF_FREQ_RMS} of {p.code} does not follow a "
                          "frequency section of that code")
        seen.add(key)
        patterns.append(p)
    end = lines.record(END_OF_ANTENNA)
    found = sum(not rms for _, rms in seen)
    if found != int(count):
        raise Invalid(f"{where}: {found} frequency sections, {FREQUENCIES_COUNT} says "
                      f"{int(count)}")
    return Antenna(tuple(records), tuple(patterns), end)


def _header(lines: _Lines) -> tuple[Record, ...]:
    first = lines.record(VERSION)
    v = cut(_Version, first.content)
    try:
        version = number(v.version, 1)
    except Error:
        version = None
    if version is None:
        raise Invalid(f"line 1: format version {v.version!r} is not F8.1")
    if version != FORMAT_VERSION:
        raise Unsupported(f"ANTEX version {v.version.strip()!r}: only 1.4 is implemented")
    if v.system not in SYSTEMS + "M":
        raise Invalid(f"line 1: satellite system {v.system!r} is not one of "
                      f"{', '.join(SYSTEMS)} or M")
    header = [first, lines.record(PCV_TYPE)]
    if header[1].content[0] not in "AR":
        raise Invalid(f"line 2: PCV type {header[1].content[0]!r} is not A or R")
    lines.records(COMMENT, header)
    header.append(lines.record(END_OF_HEADER))
    return tuple(header)


def _split(text: str) -> tuple[list[str], str, bool]:
    if not isinstance(text, str):
        raise Invalid(f"read needs the file's text as a str, got {type(text).__name__}")
    if not text:
        raise Invalid("empty file")
    lines = text.split("\n")
    final = lines[-1] == ""
    if final:
        lines.pop()
    ended = len(lines) if final else len(lines) - 1   # lines followed by LF
    crlf = {line.endswith("\r") for line in lines[:ended]}
    if len(crlf) > 1:
        raise Invalid("lines end in both LF and CR LF")
    newline = "\r\n" if crlf == {True} else "\n"
    if newline == "\r\n":
        lines[:ended] = [line[:-1] for line in lines[:ended]]
    if "\r" in text:
        for i, line in enumerate(lines):
            if "\r" in line:
                raise Invalid(f"line {i + 1}: a CR inside the line")
    return lines, newline, final


def read(text: str) -> AntexFile:
    """The ANTEX file in ``text``; raises :class:`Invalid` or :class:`Unsupported`."""
    split, newline, final = _split(text)
    lines = _Lines(split)
    header = _header(lines)
    antennas = []
    while lines.at < len(split):
        antennas.append(_antenna(lines))
    return AntexFile(header, tuple(antennas), newline, final)


def _text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise Invalid(f"{where}: needs a str, got {value!r}")
    return value


def _record_line(r: object, where: str) -> str:
    if not isinstance(r, Record):
        raise Invalid(f"{where}: {r!r} is not a Record")
    return _text(r.content, where) + _text(r.label, where)


def _row_line(r: object, where: str) -> str:
    if not isinstance(r, Row) or not isinstance(r.values, tuple):
        raise Invalid(f"{where}: {r!r} is not a Row with a tuple of values")
    return _text(r.azimuth, where) + "".join([_text(v, where) for v in r.values]) \
        + _text(r.trailing, where)


def write(file: AntexFile) -> str:
    """The text of ``file``; ``write(read(text)) == text``.

    Records that :func:`read` would not give back from their text (a wrong
    order, a row that disagrees with the grid, a field of the wrong width)
    are :class:`Invalid`.
    """
    if not isinstance(file, AntexFile):
        raise Invalid(f"write needs an AntexFile, got {type(file).__name__}")
    if file.newline not in ("\n", "\r\n"):
        raise Invalid(f"newline {file.newline!r}: LF or CR LF")
    lines = [_record_line(r, "header") for r in file.header]
    for i, antenna in enumerate(file.antennas):
        where = f"antenna {i}"
        if not isinstance(antenna, Antenna):
            raise Invalid(f"{where}: {antenna!r} is not an Antenna")
        lines += [_record_line(r, where) for r in antenna.records]
        for p in antenna.patterns:
            if not isinstance(p, Pattern):
                raise Invalid(f"{where}: {p!r} is not a Pattern")
            lines.append(_record_line(p.start, where))
            lines.append(_record_line(p.neu, where))
            lines.append(_row_line(p.noazi, where))
            lines += [_row_line(r, where) for r in p.rows]
            lines.append(_record_line(p.end, where))
        lines.append(_record_line(antenna.end, where))
    text = file.newline.join(lines) + (file.newline if file.final_newline else "")
    # The rules are read's: what is written must read back as what was given.
    try:
        back = read(text)
    except Invalid as e:
        raise Invalid(f"these records do not make an ANTEX file: {e}") from None
    if back != file:
        raise Invalid("these records do not read back from their text: a field holds a "
                      "line break or is not as wide as its columns, or a sequence is "
                      "not a tuple")
    return text
