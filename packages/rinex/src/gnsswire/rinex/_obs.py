"""Observation files: :func:`read`, :func:`write`, :func:`obs_types`.

Sources: RINEX 3.05 and 4.02, Tables A2 and A3, sections 5.3.2 (event
flags) and 6.3 to 6.6 of 3.05. The file structure:

- Header records (Table A2), each one line: content in columns 1 to 60, the
  label in 61 to 80. The first is RINEX VERSION / TYPE ("must be the first
  record in a file"), the last END OF HEADER.
- Data records (Table A3): an EPOCH record starting with ``>``, then, by
  its epoch flag,

  - 0 or 1: ``count`` OBSERVATION records, one line per satellite;
  - 2 to 5: ``count`` special records, which are header records ("header
    information follows" for 4, "at least MARKER NAME record follows" for
    3); 0 if none;
  - 6: ``count`` cycle slip records, "same format as OBSERVATIONS records".

An observation record's length is set by the SYS / # / OBS TYPES record of
its system; it may be shorter (trailing fields missing, section 6.3) but
not longer. A header event (flag 4) that holds SYS / # / OBS TYPES records
redefines the types of those systems from there on ("each value remains
valid until changed by an additional header record", section 6.5).

Readings this codec makes where the documents leave room:

- A blank ``count`` (``I3``) counts as 0, as Fortran reads blanks.
- An epoch flag other than 0 to 6, a version other than 3.xx or 4.xx and a
  file type other than ``O`` are refused; other header labels and the
  contents of every header record are kept as text, unread (section 6.6
  asks readers to skip what they do not know).
- Lines end in LF or CR LF, the same throughout a file; the file's line
  ending and whether its last line has one are kept, so that ``write(read(
  text)) == text``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ._records import (
    EpochRecord,
    HeaderRecord,
    Invalid,
    Observation,
    SatelliteRecord,
    Unsupported,
    columns,
    cut,
    join,
)

SYSTEMS = "GRECJIS"   # GPS, GLONASS, Galileo, BDS, QZSS, NavIC/IRNSS, SBAS (Table A2)
VERSIONS = ("3", "4")
OBS_TYPES = "SYS / # / OBS TYPES"
END_OF_HEADER = "END OF HEADER"
OBS_WIDTH = sum(col.width for _, col in columns(Observation))   # 16


@dataclass(frozen=True, slots=True)
class Epoch:
    """An EPOCH record and the records that belong to it.

    ``satellites`` for flags 0, 1 and 6, ``special`` for flags 2 to 5; the
    other is empty.
    """

    record: EpochRecord
    satellites: tuple[SatelliteRecord, ...] = ()
    special: tuple[HeaderRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ObsFile:
    """A whole observation file."""

    header: tuple[HeaderRecord, ...]   # RINEX VERSION / TYPE to END OF HEADER
    epochs: tuple[Epoch, ...]
    newline: str = "\n"                # "\n" or "\r\n"
    final_newline: bool = True         # whether the last line ends with ``newline``

    @property
    def version(self) -> str:
        """The format version, columns 1 to 9 of RINEX VERSION / TYPE, stripped."""
        return self.header[0].content[:9].strip()


def _label(record: HeaderRecord) -> str:
    return record.label.rstrip()


def _header_record(line: str, where: str) -> HeaderRecord:
    if len(line) <= 60:
        raise Invalid(f"{where}: a header record needs its label in columns 61 to 80")
    return cut(HeaderRecord, line)


def obs_types(records: Iterable[HeaderRecord],
              types: dict[str, tuple[str, ...]] | None = None) -> dict[str, tuple[str, ...]]:
    """The observation types per system from SYS / # / OBS TYPES records.

    Table A2: system ``A1``, ``2X``, the number of types ``I3``, then
    ``13(1X,A3)``; more than 13 types continue on lines whose first six
    columns are blank. ``types`` holds earlier definitions; a system defined
    again is replaced.
    """
    out = dict(types or {})
    system = None
    want = 0
    got: list[str] = []
    for r in records:
        if _label(r) != OBS_TYPES:
            continue
        c = r.content.ljust(60)
        if c[0] != " ":
            if system is not None and len(got) != want:
                raise Invalid(f"{OBS_TYPES} {system}: {len(got)} types, says {want}")
            system = c[0]
            if system not in SYSTEMS or c[1:3] != "  ":
                raise Invalid(f"{OBS_TYPES}: no system code in {r.content!r}")
            try:
                want = int(c[3:6])
            except ValueError:
                raise Invalid(f"{OBS_TYPES} {system}: no number of types") from None
            got = []
            out[system] = ()
        elif system is None or c[:6].strip():
            raise Invalid(f"{OBS_TYPES}: a continuation line without a system line")
        for i in range(13):
            if c[6 + 4 * i] != " ":
                raise Invalid(f"{OBS_TYPES} {system}: column {7 + 4 * i} is not blank")
            t = c[7 + 4 * i:10 + 4 * i]
            if t.strip():
                got.append(t)
        out[system] = tuple(got)
    if system is not None and len(got) != want:
        raise Invalid(f"{OBS_TYPES} {system}: {len(got)} types, says {want}")
    return out


def _satellite(line: str, types: dict[str, tuple[str, ...]], where: str) -> SatelliteRecord:
    sat = line[:3]
    if len(sat) < 3 or sat[0] not in SYSTEMS or not sat[1:].isdigit():
        raise Invalid(f"{where}: {sat!r} is not a satellite number (A1,I2.2)")
    if sat[0] not in types:
        raise Invalid(f"{where}: no {OBS_TYPES} record for system {sat[0]}")
    rest = line[3:]
    obs = tuple(cut(Observation, rest[i:i + OBS_WIDTH]) for i in range(0, len(rest), OBS_WIDTH))
    if len(obs) > len(types[sat[0]]):
        raise Invalid(f"{where}: {len(obs)} observations, {sat[0]} has "
                      f"{len(types[sat[0]])} types")
    return SatelliteRecord(sat, obs)


def _count(record: EpochRecord, where: str) -> int:
    text = record.count.strip()
    if not text:
        return 0
    if not text.isdigit():
        raise Invalid(f"{where}: number of records {record.count!r} is not I3")
    return int(text)


def _flag(record: EpochRecord, where: str) -> int:
    flag = record.flag.strip()
    if len(flag) != 1 or flag not in "0123456":
        raise Invalid(f"{where}: epoch flag {record.flag!r} is not 0 to 6")
    return int(flag)


def _check_version(header: HeaderRecord) -> str:
    if _label(header) != "RINEX VERSION / TYPE":
        raise Invalid("the first record is not RINEX VERSION / TYPE")
    version = header.content[:9].strip()
    if version.split(".")[0] not in VERSIONS:
        raise Unsupported(f"RINEX version {version!r}: only 3.xx and 4.xx are implemented")
    if header.content[20:21] != "O":
        raise Unsupported(f"file type {header.content[20:21]!r}: only observation data (O)")
    return version


def _lines(text: str) -> tuple[list[str], str, bool]:
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
    for i, line in enumerate(lines):
        if "\r" in line:
            raise Invalid(f"line {i + 1}: a CR inside the line")
    return lines, newline, final


def read(text: str) -> ObsFile:
    """The observation file in ``text``; raises :class:`Invalid` or :class:`Unsupported`."""
    lines, newline, final = _lines(text)
    header: list[HeaderRecord] = []
    n = 0
    while True:
        if n == len(lines):
            raise Invalid(f"no {END_OF_HEADER} record")
        header.append(_header_record(lines[n], f"line {n + 1}"))
        n += 1
        if n == 1:
            version = _check_version(header[0])
        if _label(header[-1]) == END_OF_HEADER:
            break
    types = obs_types(header)
    epochs = []
    while n < len(lines):
        where = f"line {n + 1}"
        line = lines[n]
        if not line.startswith(">"):
            raise Invalid(f"{where}: an EPOCH record starts with '>'")
        record = cut(EpochRecord, line[1:])
        if record.picoseconds and not version.startswith("4"):
            raise Invalid(f"{where}: picoseconds (1X,I5.5) are a RINEX 4 field")
        flag, count = _flag(record, where), _count(record, where)
        n += 1
        if n + count > len(lines):
            raise Invalid(f"{where}: {count} records announced, {len(lines) - n} lines left")
        body = lines[n:n + count]
        if flag in (2, 3, 4, 5):
            special = tuple(_header_record(b, f"line {n + 1 + i}") for i, b in enumerate(body))
            if flag == 4:
                types = obs_types(special, types)
            epochs.append(Epoch(record, special=special))
        else:
            epochs.append(Epoch(record, satellites=tuple(
                _satellite(b, types, f"line {n + 1 + i}") for i, b in enumerate(body))))
        n += count
    return ObsFile(tuple(header), tuple(epochs), newline, final)


def records(obs: ObsFile) -> Iterator[str]:
    """The lines of ``obs``, without line endings, checked as :func:`read` checks them."""
    if not obs.header or _label(obs.header[-1]) != END_OF_HEADER:
        raise Invalid(f"the header must end with {END_OF_HEADER}")
    version = _check_version(obs.header[0])
    for r in obs.header[1:-1]:
        if _label(r) == END_OF_HEADER:
            raise Invalid(f"{END_OF_HEADER} inside the header")
    for r in obs.header:
        yield _header_line(r)
    types = obs_types(obs.header)
    for i, epoch in enumerate(obs.epochs):
        where = f"epoch {i}"
        record = epoch.record
        if record.picoseconds and not version.startswith("4"):
            raise Invalid(f"{where}: picoseconds (1X,I5.5) are a RINEX 4 field")
        flag, count = _flag(record, where), _count(record, where)
        body = epoch.special if flag in (2, 3, 4, 5) else epoch.satellites
        other = epoch.satellites if flag in (2, 3, 4, 5) else epoch.special
        if other:
            kind = "satellite" if flag in (2, 3, 4, 5) else "special"
            raise Invalid(f"{where}: flag {flag} has no {kind} records")
        if len(body) != count:
            raise Invalid(f"{where}: count {record.count!r}, {len(body)} records")
        yield ">" + join(record)
        if flag in (2, 3, 4, 5):
            for r in epoch.special:
                yield _header_line(r)
            if flag == 4:
                types = obs_types(epoch.special, types)
        else:
            for s in epoch.satellites:
                if not isinstance(s, SatelliteRecord) or not isinstance(s.sat, str) or not all(
                        isinstance(o, Observation) for o in s.obs):
                    raise Invalid(f"{where}: {s!r} is not a SatelliteRecord of Observations")
                if any(len(join(o)) != OBS_WIDTH for o in s.obs[:-1]):
                    raise Invalid(f"{where}: {s.sat}: only the last observation may be short")
                line = s.sat + "".join(join(o) for o in s.obs)
                if _satellite(line, types, f"{where}, {s.sat}") != s:
                    # An empty last observation, or a satellite number that
                    # is not three columns: the line would read back otherwise.
                    raise Invalid(f"{where}: {s!r} does not read back from its line")
                yield line


def _header_line(r: HeaderRecord) -> str:
    if not isinstance(r, HeaderRecord):
        raise Invalid(f"{r!r} is not a HeaderRecord")
    line = join(r)
    if len(r.content) != 60 or not r.label:
        raise Invalid(f"header record {line!r}: content is 60 columns, then a label")
    return line


def write(obs: ObsFile) -> str:
    """The text of ``obs``; ``write(read(text)) == text``."""
    if obs.newline not in ("\n", "\r\n"):
        raise Invalid(f"newline {obs.newline!r}: LF or CR LF")
    lines = list(records(obs))
    return obs.newline.join(lines) + (obs.newline if obs.final_newline else "")
