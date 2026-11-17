"""RINEX 2 observation files: :func:`read2`, :func:`write2`, :func:`obs_types2`.

Source: RINEX 2.11 (W. Gurtner and L. Estey, IGS/RTCM RINEX Working Group,
10 December 2007 with the clarifications of 26 June 2012), Table A1 ("GNSS
observation data file - header section description"), Table A2 ("GNSS
observation data file - data record description") and sections 5 and 6.
The file structure:

- Header records (Table A1), each one line: content in columns 1 to 60, the
  label in 61 to 80 (section 2). The first is RINEX VERSION / TYPE (section
  5.2), the last END OF HEADER. They are the :class:`HeaderRecord` of RINEX
  3 and 4.
- Data records (Table A2): an EPOCH/SAT or EVENT FLAG record, then, by its
  epoch flag,

  - 0 or 1: the satellites of the epoch are listed in the record, twelve to
    a line, with continuation lines for more than twelve (section 8.1.3);
    OBSERVATIONS records follow for each satellite in turn, five
    observations to a line, so ``ceil(types / 5)`` lines per satellite;
  - 2 to 5: ``count`` special records, which are header records ("header
    records now allowed after all epoch flags >1", section 0.4); the epoch
    fields may be blank;
  - 6: cycle slip records, "same format as OBSERVATIONS records", for the
    satellites listed.

Unlike RINEX 3, an OBSERVATIONS record does not name its satellite, the
year has two digits (:func:`full_year`, section 6.5), every satellite has
the same observation types (# / TYPES OF OBSERV), and a satellite number
may have a blank system identifier, meaning GPS, and a blank for a leading
zero (:func:`sat_name`, section 5.1).

Readings this codec makes where the document leaves room:

- Trailing blanks may be truncated (sections 2 and 5.3) from every line,
  but lines are not: a satellite always has ``ceil(types / 5)`` OBSERVATIONS
  lines, the last ones empty if their observations are missing, and an
  epoch of more than twelve satellites always has its continuation lines.
- Section 5.3: "each value remains valid until changed by an additional
  header record". A # / TYPES OF OBSERV record among the special records of
  any event flag 2 to 5 therefore changes the observation types from there
  on, since section 0.4 allows header records after each of them.
- A satellite number is ``A1,I2`` with the system identifiers of section
  5.1 (blank, G, R, S, E); another is refused. The 32 blank columns of a
  continuation line (``32X``) are kept as text, unread (section 6.4).
- The receiver clock offset is read on the EPOCH/SAT line only: Table A2
  gives the continuation line as ``32X,12(A1,I2)``, without it.
- A blank ``count`` (``I3``) counts as 0, as Fortran reads blanks. An epoch
  flag other than 0 to 6, a version other than 2.xx and a file type other
  than ``O`` are refused; other header labels and the contents of every
  header record are kept as text, unread (section 6.9).
- Lines end in LF or CR LF, the same throughout a file, kept as in RINEX 3.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Annotated

from ._obs import END_OF_HEADER, _count, _flag, _header_line, _header_record, _label, _lines
from ._records import (
    Col,
    Error,
    HeaderRecord,
    Invalid,
    Observation,
    SatelliteRecord,
    Unsupported,
    columns,
    cut,
    join,
    number,
)

SYSTEMS2 = "GRSE"     # GPS, GLONASS, geostationary signal payload, Galileo (section 5.1)
OBS_TYPES2 = "# / TYPES OF OBSERV"
EVENTS = (2, 3, 4, 5)                                           # special records follow
OBS_WIDTH = sum(col.width for _, col in columns(Observation))   # 16
PER_LINE = 5          # "If more than 5 observation types (=80 char): continue" (Table A2)
LIST = 12             # satellites in an EPOCH/SAT line or a continuation line
NO_OBS = Observation("", "", "")

_SAT = re.compile(r"[ GRSE][ \d]\d")


@dataclass(frozen=True, slots=True)
class EpochRecord2:
    """The EPOCH/SAT or EVENT FLAG record of Table A2: the first line of an epoch.

    ``sats`` is the list of up to twelve satellite numbers as written, three
    columns each (``G12G09G06``; see :func:`sat_name`), blank under flags 2
    to 5; ``clock`` is the optional receiver clock offset in seconds. For
    flags 0, 1 and 6, ``count`` is the number of satellites in the epoch,
    for flags 2 to 5 the number of special records that follow. "For events
    without significant epoch the epoch fields can be left blank."
    """

    year: Annotated[str, Col(3, "1X,I2.2")]
    month: Annotated[str, Col(3, "1X,I2")]
    day: Annotated[str, Col(3, "1X,I2")]
    hour: Annotated[str, Col(3, "1X,I2")]
    minute: Annotated[str, Col(3, "1X,I2")]
    second: Annotated[str, Col(11, "F11.7")]
    flag: Annotated[str, Col(3, "2X,I1")]
    count: Annotated[str, Col(3, "I3")]
    sats: Annotated[str, Col(36, "12(A1,I2)")]
    clock: Annotated[str, Col(12, "F12.9")]


@dataclass(frozen=True, slots=True)
class SatelliteList:
    """A continuation line of the EPOCH/SAT record: ``32X,12(A1,I2)`` (Table A2).

    "If more than 12 satellites: use continuation line(s)" (section 8.1.3).
    """

    blank: Annotated[str, Col(32, "32X")]
    sats: Annotated[str, Col(36, "12(A1,I2)")]


@dataclass(frozen=True, slots=True)
class Epoch2:
    """An EPOCH/SAT or EVENT FLAG record and the records that belong to it.

    ``satellites`` for flags 0, 1 and 6, ``special`` for flags 2 to 5; the
    other is empty. Each satellite is a :class:`SatelliteRecord`: ``sat`` is
    its three columns of the list in ``record.sats`` and ``continuation``,
    in the list's order, and ``obs`` its observations in the order of # /
    TYPES OF OBSERV, the lines of five joined. ``obs`` may be shorter than
    the types when the trailing fields are missing; an observation missing
    from the end of a line that is not the satellite's last is
    ``Observation("", "", "")``, and one cut by the end of its line is the
    part that is there.
    """

    record: EpochRecord2
    satellites: tuple[SatelliteRecord, ...] = ()
    special: tuple[HeaderRecord, ...] = ()
    continuation: tuple[SatelliteList, ...] = ()


@dataclass(frozen=True, slots=True)
class ObsFile2:
    """A whole RINEX 2 observation file."""

    header: tuple[HeaderRecord, ...]   # RINEX VERSION / TYPE to END OF HEADER
    epochs: tuple[Epoch2, ...]
    newline: str = "\n"                # "\n" or "\r\n"
    final_newline: bool = True         # whether the last line ends with ``newline``

    @property
    def version(self) -> str:
        """The format version, columns 1 to 9 of RINEX VERSION / TYPE, stripped."""
        return self.header[0].content[:9].strip()


def full_year(field: str) -> int | None:
    """The year a two-digit year field stands for; ``None`` for a blank field.

    Section 6.5: "any two-digit years in RINEX Version 1 and Version 2.xx
    files are understood to represent 80-99: 1980-1999, 00-79: 2000-2079".
    """
    year = number(field)
    if year is None:
        return None
    if not 0 <= year <= 99:
        raise Error(f"{field!r} is not a two-digit year")
    return year + (1900 if year >= 80 else 2000)


def sat_name(sat: str) -> str:
    """A satellite number of a list as ``A1,I2.2``: ``G09`` for ``G 9`` and for ``  9``.

    Section 5.1: the system identifier is "G or blank: GPS", R, S or E.
    """
    if not isinstance(sat, str) or not _SAT.fullmatch(sat):
        raise Error(f"{sat!r} is not a satellite number (A1,I2)")
    return (sat[0] if sat[0] != " " else "G") + sat[1:].replace(" ", "0")


def obs_types2(records: Iterable[HeaderRecord],
               types: tuple[str, ...] | None = None) -> tuple[str, ...] | None:
    """The observation types from # / TYPES OF OBSERV records, as ``("C1", "L1")``.

    Table A1: the number of types ``I6``, then ``9(4X,A1,A1)``; more than 9
    types continue on lines of ``6X,9(4X,2A1)`` with the same label.
    ``types`` holds an earlier definition, which is returned when
    ``records`` has no such record (``None`` if there was none); a new
    definition replaces it.
    """
    out = types
    want = None
    got: list[str] = []
    for r in records:
        if _label(r) != OBS_TYPES2:
            continue
        c = r.content.ljust(60)
        if c[:6].strip():
            if want is not None and len(got) != want:
                raise Invalid(f"{OBS_TYPES2}: {len(got)} types, says {want}")
            try:
                want = int(c[:6])
            except ValueError:
                raise Invalid(f"{OBS_TYPES2}: number of types {c[:6]!r} is not I6") from None
            if want < 0:
                raise Invalid(f"{OBS_TYPES2}: number of types {c[:6]!r} is not I6")
            got = []
        elif want is None:
            raise Invalid(f"{OBS_TYPES2}: a continuation line without a first line")
        for i in range(9):
            if c[6 + 6 * i:10 + 6 * i].strip():
                raise Invalid(f"{OBS_TYPES2}: columns {7 + 6 * i} to {10 + 6 * i} are not blank")
            t = c[10 + 6 * i:12 + 6 * i]
            if t.strip():
                got.append(t)
        out = tuple(got)
    if want is not None and len(got) != want:
        raise Invalid(f"{OBS_TYPES2}: {len(got)} types, says {want}")
    return out


def _names(text: str, n: int, where: str) -> tuple[str, ...]:
    """The ``n`` satellite numbers at the start of a list field; the rest is blank."""
    if len(text) < 3 * n:
        raise Invalid(f"{where}: {n} satellites to list, {len(text)} columns of list")
    names = tuple(text[i:i + 3] for i in range(0, 3 * n, 3))
    for name in names:
        if not _SAT.fullmatch(name):
            raise Invalid(f"{where}: {name!r} is not a satellite number (A1,I2)")
    if text[3 * n:].strip():
        raise Invalid(f"{where}: {text[3 * n:]!r} after the {n} satellites of the list")
    return names


def _observations(lines: Sequence[str], types: int, where: str) -> tuple[Observation, ...]:
    """The observations of one satellite from its OBSERVATIONS lines."""
    rows = []
    for k, line in enumerate(lines):
        if len(line) > PER_LINE * OBS_WIDTH:
            raise Invalid(f"{where}: an OBSERVATIONS record of {len(line)} columns")
        row = [cut(Observation, line[i:i + OBS_WIDTH]) for i in range(0, len(line), OBS_WIDTH)]
        if PER_LINE * k + len(row) > types:
            raise Invalid(f"{where}: {PER_LINE * k + len(row)} observations, {types} types")
        rows.append(row)
    while rows and not rows[-1]:
        rows.pop()
    out: list[Observation] = []
    for row in rows[:-1]:
        out += row + [NO_OBS] * (PER_LINE - len(row))
    if rows:
        out += rows[-1]
    return tuple(out)


def _need(lines: Sequence[str], n: int, count: int, what: str, where: str) -> None:
    if n + count > len(lines):
        raise Invalid(f"{where}: {count} {what} announced, {len(lines) - n} lines left")


def _epoch(lines: Sequence[str], n: int, types: tuple[str, ...] | None,
           ) -> tuple[Epoch2, int, tuple[str, ...] | None]:
    """The epoch at ``lines[n]``, the index after it and the types after it."""
    where = f"line {n + 1}"
    record = cut(EpochRecord2, lines[n])
    flag, count = _flag(record, where), _count(record, where)
    n += 1
    if flag in EVENTS:
        if record.sats.strip():
            raise Invalid(f"{where}: flag {flag} has no list of satellites")
        _need(lines, n, count, "special records", where)
        special = tuple(_header_record(lines[n + i], f"line {n + 1 + i}") for i in range(count))
        return Epoch2(record, special=special), n + count, obs_types2(special, types)
    more = max(count - 1, 0) // LIST
    _need(lines, n, more, "continuation lines", where)
    continuation = tuple(cut(SatelliteList, lines[n + i]) for i in range(more))
    names = _names(record.sats, min(count, LIST), where)
    for i, c in enumerate(continuation):
        names += _names(c.sats, min(count - LIST * (i + 1), LIST), f"line {n + 1 + i}")
    n += more
    if count and types is None:
        raise Invalid(f"{where}: no {OBS_TYPES2} record")
    per = -(-len(types or ()) // PER_LINE)
    _need(lines, n, count * per, "OBSERVATIONS records", where)
    satellites = []
    for name in names:
        satellites.append(SatelliteRecord(
            name, _observations(lines[n:n + per], len(types or ()), f"line {n + 1}")))
        n += per
    return Epoch2(record, tuple(satellites), (), continuation), n, types


def _check_version2(header: HeaderRecord) -> str:
    if _label(header) != "RINEX VERSION / TYPE":
        raise Invalid("the first record is not RINEX VERSION / TYPE")
    version = header.content[:9].strip()
    if version.split(".")[0] != "2":
        raise Unsupported(f"RINEX version {version!r}: read2 and write2 are for 2.xx")
    if header.content[20:21] != "O":
        raise Unsupported(f"file type {header.content[20:21]!r}: only observation data (O)")
    return version


def read2(text: str) -> ObsFile2:
    """The RINEX 2 observation file in ``text``; raises :class:`Invalid` or :class:`Unsupported`."""
    lines, newline, final = _lines(text)
    header: list[HeaderRecord] = []
    n = 0
    while True:
        if n == len(lines):
            raise Invalid(f"no {END_OF_HEADER} record")
        header.append(_header_record(lines[n], f"line {n + 1}"))
        n += 1
        if n == 1:
            _check_version2(header[0])
        if _label(header[-1]) == END_OF_HEADER:
            break
    types = obs_types2(header)
    epochs = []
    while n < len(lines):
        epoch, n, types = _epoch(lines, n, types)
        epochs.append(epoch)
    return ObsFile2(tuple(header), tuple(epochs), newline, final)


def _epoch_lines(epoch: Epoch2, types: tuple[str, ...] | None, where: str) -> list[str]:
    if not isinstance(epoch, Epoch2) or not isinstance(epoch.record, EpochRecord2):
        raise Invalid(f"{where}: {epoch!r} is not an Epoch2 of an EpochRecord2")
    lines = [join(epoch.record)]
    for c in epoch.continuation:
        if not isinstance(c, SatelliteList):
            raise Invalid(f"{where}: {c!r} is not a SatelliteList")
        lines.append(join(c))
    lines += [_header_line(r) for r in epoch.special]
    per = -(-len(types or ()) // PER_LINE)
    for s in epoch.satellites:
        if not isinstance(s, SatelliteRecord) or not all(
                isinstance(o, Observation) for o in s.obs):
            raise Invalid(f"{where}: {s!r} is not a SatelliteRecord of Observations")
        lines += ["".join(join(o) for o in s.obs[PER_LINE * k:PER_LINE * (k + 1)])
                  for k in range(per)]
    return lines


def records2(obs: ObsFile2) -> Iterator[str]:
    """The lines of ``obs``, without line endings, checked as :func:`read2` checks them."""
    if not obs.header or _label(obs.header[-1]) != END_OF_HEADER:
        raise Invalid(f"the header must end with {END_OF_HEADER}")
    _check_version2(obs.header[0])
    for r in obs.header[1:-1]:
        if _label(r) == END_OF_HEADER:
            raise Invalid(f"{END_OF_HEADER} inside the header")
    for r in obs.header:
        yield _header_line(r)
    types = obs_types2(obs.header)
    for i, epoch in enumerate(obs.epochs):
        where = f"epoch {i}"
        lines = _epoch_lines(epoch, types, where)
        # Whatever would not read back as this epoch is refused: a count or a
        # list that does not match the records, a satellite named otherwise
        # than in the list, more observations than types, a short observation
        # before the end of its line, an empty last observation.
        try:
            back, n, types = _epoch(lines, 0, types)
        except Invalid as e:
            raise Invalid(f"{where}: {e}") from None
        if back != epoch or n != len(lines):
            raise Invalid(f"{where}: {epoch!r} does not read back from its lines")
        yield from lines


def write2(obs: ObsFile2) -> str:
    """The text of ``obs``; ``write2(read2(text)) == text``."""
    if obs.newline not in ("\n", "\r\n"):
        raise Invalid(f"newline {obs.newline!r}: LF or CR LF")
    lines = list(records2(obs))
    return obs.newline.join(lines) + (obs.newline if obs.final_newline else "")
