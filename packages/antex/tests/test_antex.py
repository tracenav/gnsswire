"""ANTEX 1.4 files against section 4 of the document (Rothacher and Schmid, 2010).

- The record table is transcribed a second time here, label by label, with
  the formats the document prints.
- Files are built line by line from those formats, here, with made-up
  values: a receiver antenna with an azimuth-dependent pattern, a satellite
  antenna with a NOAZI-only pattern, rms sections. The document prints no
  example file, and no calibration file is used.
- Built files round-trip: ``write(read(text)) == text``.
- What contradicts the table is refused.
"""

import dataclasses

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import antex
from gnsswire.antex import (
    Antenna,
    AntexFile,
    Invalid,
    Pattern,
    Record,
    Row,
    Unsupported,
    number,
)

# Section 4, row by row: label, then (field, width, format) in column order.
# The widths of a row add up to 60, the columns before the label.
DOCUMENT = {
    "ANTEX VERSION / SYST": [("version", 20, "F8.1,12X"), ("system", 1, "A1"),
                             ("blank", 39, "39X")],
    "PCV TYPE / REFANT": [("pcv_type", 20, "A1,19X"), ("refant", 20, "A20"),
                          ("refant_serial", 20, "A20")],
    "COMMENT": [("text", 60, "A60")],
    "END OF HEADER": [("blank", 60, "60X")],
    "START OF ANTENNA": [("blank", 60, "60X")],
    "TYPE / SERIAL NO": [("type", 20, "A20"), ("serial", 20, "A20"), ("svn", 10, "A10"),
                         ("cospar", 10, "A10")],
    "METH / BY / # / DATE": [("method", 20, "A20"), ("agency", 20, "A20"),
                             ("count", 10, "I6,4X"), ("date", 10, "A10")],
    "DAZI": [("dazi", 8, "2X,F6.1"), ("blank", 52, "52X")],
    "ZEN1 / ZEN2 / DZEN": [("zen1", 8, "2X,F6.1"), ("zen2", 6, "F6.1"), ("dzen", 6, "F6.1"),
                           ("blank", 40, "40X")],
    "# OF FREQUENCIES": [("count", 6, "I6"), ("blank", 54, "54X")],
    "VALID FROM": [("year", 6, "I6"), ("month", 6, "I6"), ("day", 6, "I6"), ("hour", 6, "I6"),
                   ("minute", 6, "I6"), ("second", 13, "F13.7"), ("blank", 17, "17X")],
    "VALID UNTIL": [("year", 6, "I6"), ("month", 6, "I6"), ("day", 6, "I6"), ("hour", 6, "I6"),
                    ("minute", 6, "I6"), ("second", 13, "F13.7"), ("blank", 17, "17X")],
    "SINEX CODE": [("code", 10, "A10"), ("blank", 50, "50X")],
    "START OF FREQUENCY": [("code", 6, "3X,A1,I2"), ("blank", 54, "54X")],
    "NORTH / EAST / UP": [("north", 10, "F10.2"), ("east", 10, "F10.2"), ("up", 10, "F10.2"),
                          ("blank", 30, "30X")],
    "END OF FREQUENCY": [("code", 6, "3X,A1,I2"), ("blank", 54, "54X")],
    "START OF FREQ RMS": [("code", 6, "3X,A1,I2"), ("blank", 54, "54X")],
    "END OF FREQ RMS": [("code", 6, "3X,A1,I2"), ("blank", 54, "54X")],
    "END OF ANTENNA": [("blank", 60, "60X")],
}


def test_tables_are_the_document():
    assert list(antex.TABLE) == list(DOCUMENT)       # the table's order too
    for name, cols in DOCUMENT.items():
        assert [(n, c.width, c.fmt) for n, c in antex.columns(antex.TABLE[name])] == cols, name
        assert sum(width for _, width, _ in cols) == 60 and len(name) <= 20
    assert [(n, c.width) for n, c in antex.columns(Record)] == [("content", 60), ("label", 20)]
    # The frequency codes the START OF FREQUENCY description lists.
    assert antex.FREQUENCIES == {
        "G01": "L1", "G02": "L2", "G05": "L5", "R01": "G1", "R02": "G2",
        "E01": "E1", "E05": "E5a", "E07": "E5b", "E08": "E5 (E5a+E5b)", "E06": "E6",
        "C01": "E1", "C02": "E2", "C07": "E5b", "C06": "E6",
        "J01": "L1", "J02": "L2", "J05": "L5", "J06": "LEX", "S01": "L1", "S05": "L5"}
    assert antex.SYSTEMS == "GRECJS" and antex.NOAZI == "   NOAZI"


# --- building files from the formats ---------------------------------------------------

def fixed(value: int, decimals: int, width: int) -> str:
    """Fortran Fw.d of ``value`` in units of 10**-decimals, without floating point."""
    digits = f"{abs(value):0{decimals + 1}d}"
    text = ("-" if value < 0 else "") + digits[:-decimals] + "." + digits[-decimals:]
    assert len(text) <= width
    return text.rjust(width)


def labelled(content: str, label: str, pad: bool = True) -> str:
    assert len(content) <= 60 and len(label) <= 20
    return content.ljust(60) + (label.ljust(20) if pad else label)


def pattern_value(code: str, azimuth: int | None, zenith: int) -> int:
    """A made-up phase pattern value, in 0.01 mm, that differs in every cell."""
    return (sum(map(ord, code)) * 7 + (0 if azimuth is None else azimuth + 1) * 3
            - zenith * 2) % 4001 - 2000


def row(code: str, azimuth: int | None, zeniths: list[int]) -> str:
    # 3X,A5,mF8.2 for NOAZI; F8.1,mF8.2 for an azimuth.
    first = "   NOAZI" if azimuth is None else fixed(azimuth, 1, 8)
    return first + "".join(fixed(pattern_value(code, azimuth, z), 2, 8) for z in zeniths)


def section(code: str, neu: tuple[int, int, int], dazi: int, zeniths: list[int],
            rms: bool = False) -> list[str]:
    kind = "FREQ RMS" if rms else "FREQUENCY"
    lines = [labelled("   " + code, f"START OF {kind}"),                       # 3X,A1,I2,54X
             labelled("".join(fixed(v, 2, 10) for v in neu), "NORTH / EAST / UP")]   # 3F10.2
    lines.append(row(code, None, zeniths))
    if dazi:
        lines += [row(code, azimuth, zeniths) for azimuth in range(0, 3601, dazi)]
    lines.append(labelled("   " + code, f"END OF {kind}"))
    return lines


def antenna(type_: str, serial: str = "", svn: str = "", cospar: str = "", *,
            dazi: int = 50, zen: tuple[int, int, int] = (0, 900, 50),
            codes: tuple[str, ...] = ("G01", "G02"), rms: str = "",
            valid_from: tuple | None = None, valid_until: tuple | None = None,
            sinex: str | None = None, comments: tuple[str, ...] = ()) -> list[str]:
    """An antenna section; ``rms`` is "", "each" (after each frequency) or "last"."""
    zeniths = list(range(zen[0], zen[1] + 1, zen[2]))
    lines = [
        labelled("", "START OF ANTENNA"),
        labelled(f"{type_:20}{serial:20}{svn:10}{cospar:10}", "TYPE / SERIAL NO"),
        labelled(f"{'ROBOT':20}{'Example Agency':20}{3:6d}    {'17-NOV-26':10}",
                 "METH / BY / # / DATE"),                                      # A20,A20,I6,4X,A10
        labelled("  " + fixed(dazi, 1, 6), "DAZI"),                            # 2X,F6.1
        labelled("  " + "".join(fixed(v, 1, 6) for v in zen), "ZEN1 / ZEN2 / DZEN"),
        labelled(f"{len(codes):6d}", "# OF FREQUENCIES"),                      # I6
    ]
    for epoch, name in ((valid_from, "VALID FROM"), (valid_until, "VALID UNTIL")):
        if epoch is not None:                                                  # 5I6,F13.7
            lines.append(labelled("".join(f"{v:6d}" for v in epoch[:5]) + fixed(epoch[5], 7, 13),
                                  name))
    if sinex is not None:
        lines.append(labelled(f"{sinex:10}", "SINEX CODE"))
    lines += [labelled(c, "COMMENT") for c in comments]
    for i, code in enumerate(codes):
        neu = (60 + i, -45 - i, 9000 + 100 * i)
        lines += section(code, neu, dazi, zeniths)
        if rms == "each":
            lines += section(code, (1, 2, 3), dazi, zeniths, rms=True)
    if rms == "last":
        for code in codes:
            lines += section(code, (1, 2, 3), dazi, zeniths, rms=True)
    lines.append(labelled("", "END OF ANTENNA"))
    return lines


def header(system: str = "M", pcv: str = "A", refant: str = "", refant_serial: str = "",
           comments: tuple[str, ...] = ("built for the tests",)) -> list[str]:
    return [labelled(fixed(14, 1, 8) + " " * 12 + system, "ANTEX VERSION / SYST"),
            labelled(f"{pcv:20}{refant:20}{refant_serial:20}", "PCV TYPE / REFANT"),
            *[labelled(c, "COMMENT") for c in comments],
            labelled("", "END OF HEADER")]


def text_of(lines: list[str], newline: str = "\n", final: bool = True) -> str:
    return newline.join(lines) + (newline if final else "")


RECEIVER = antenna("EXAMPLE_ANT     NONE", "12345", sinex="EXMPL_0001",
                   comments=("a receiver antenna", "with two comment lines"))
SATELLITE = antenna("BLOCK IIA", "G05", "G035", "1993-054A", dazi=0, zen=(0, 140, 10),
                    codes=("G01", "G02", "G05"), valid_from=(1993, 8, 30, 0, 0, 0),
                    valid_until=(2009, 3, 26, 23, 59, 599999999), sinex="EXMPL_0001")
TYPE_MEAN = antenna("EXAMPLE_ANT     NONE", dazi=300, zen=(0, 800, 100), codes=("R01",))
FILE = header() + SATELLITE + RECEIVER + TYPE_MEAN


def test_built_lines_are_as_the_document_describes():
    # The examples the document prints in its descriptions.
    assert RECEIVER[4][:20] == "     0.0  90.0   5.0"         # ZEN1 / ZEN2 / DZEN, receiver
    assert SATELLITE[4][:20] == "     0.0  14.0   1.0"        # and satellite
    assert SATELLITE[1][:9] == "BLOCK IIA" and SATELLITE[1][20:23] == "G05"
    assert all(len(line) == 80 for line in header())
    assert len(RECEIVER[13]) == 8 + 8 * 19                      # 0 to 90 by 5: 19 values


# --- reading ---------------------------------------------------------------------------

@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("final", [True, False])
def test_round_trip(newline, final):
    text = text_of(FILE, newline, final)
    file = antex.read(text)
    assert (file.newline, file.final_newline) == (newline, final)
    assert antex.write(file) == text
    assert antex.read(antex.write(file)) == file


def test_header():
    file = antex.read(text_of(FILE))
    assert (file.version, file.system) == ("1.4", "M")
    assert number(antex.fields(file.header[0]).version, 1) == 14
    assert file.pcv_type == antex.PcvType("A".ljust(20), " " * 20, " " * 20)
    assert file.comments == ("built for the tests".ljust(60),)
    assert [r.label.rstrip() for r in file.header] == [
        "ANTEX VERSION / SYST", "PCV TYPE / REFANT", "COMMENT", "END OF HEADER"]
    assert len(file.antennas) == 3

    relative = antex.read(text_of(header("G", "R", "AOAD/M_T        NONE", "S/N 1", ())))
    assert relative.system == "G" and relative.antennas == () and relative.comments == ()
    pcv = relative.pcv_type
    assert (pcv.pcv_type.strip(), pcv.refant, pcv.refant_serial.strip()) == (
        "R", "AOAD/M_T        NONE", "S/N 1")


def test_receiver_antenna_with_azimuth_dependent_pattern():
    a = antex.read(text_of(FILE)).antennas[1]
    assert (a.type, a.serial) == ("EXAMPLE_ANT     NONE", "12345".ljust(20))
    assert a.type_serial == antex.TypeSerial("EXAMPLE_ANT     NONE", "12345".ljust(20),
                                             " " * 10, " " * 10)
    m = a.method
    assert (m.method.strip(), m.agency.strip(), number(m.count), m.date.strip()) == (
        "ROBOT", "Example Agency", 3, "17-NOV-26")
    assert a.dazi == "     5.0" and number(a.dazi, 1) == 50
    assert a.grid == antex.Grid("     0.0", "  90.0", "   5.0")
    assert a.zeniths == tuple(range(0, 901, 50)) and a.azimuths == tuple(range(0, 3601, 50))
    assert (a.valid_from, a.valid_until, a.sinex_code) == (None, None, "EXMPL_0001")
    assert a.comments == ("a receiver antenna".ljust(60), "with two comment lines".ljust(60))
    assert list(a.frequencies) == ["G01", "G02"] and a.rms == {}

    g2 = a.frequencies["G02"]
    assert (g2.code, g2.rms) == ("G02", False)
    assert g2.offset == antex.Offset("      0.61", "     -0.46", "     91.00")
    assert [number(f, 2) for f in (g2.offset.north, g2.offset.east, g2.offset.up)] == [
        61, -46, 9100]                                           # units of 0.01 mm
    assert g2.noazi.azimuth == "   NOAZI" and len(g2.noazi.values) == 19
    assert [number(v, 2) for v in g2.noazi.values] == [
        pattern_value("G02", None, z) for z in a.zeniths]
    assert len(g2.rows) == 73
    for azimuth, r in zip(a.azimuths, g2.rows, strict=True):
        assert number(r.azimuth, 1) == azimuth and r.trailing == ""
        assert [number(v, 2) for v in r.values] == [
            pattern_value("G02", azimuth, z) for z in a.zeniths]
    assert g2.rows[0].azimuth == "     0.0" and g2.rows[-1].azimuth == "   360.0"
    assert all(len(v) == 8 for r in g2.rows for v in r.values)


def test_satellite_antenna_with_noazi_only_pattern():
    a = antex.read(text_of(FILE)).antennas[0]
    t = a.type_serial
    assert (t.type.strip(), t.serial.strip(), t.svn.strip(), t.cospar.strip()) == (
        "BLOCK IIA", "G05", "G035", "1993-054A")
    assert number(a.dazi, 1) == 0 and a.azimuths == ()
    assert a.zeniths == tuple(range(0, 141, 10))                 # nadir angles 0 to 14
    assert a.valid_from == antex.Epoch("  1993", "     8", "    30", "     0", "     0",
                                       "    0.0000000")
    until = a.valid_until
    assert [number(f) for f in (until.year, until.month, until.day, until.hour,
                                until.minute)] == [2009, 3, 26, 23, 59]
    assert number(until.second, 7) == 599999999                  # 59.9999999 s
    assert list(a.frequencies) == ["G01", "G02", "G05"]
    for code, p in a.frequencies.items():
        assert p.rows == () and len(p.noazi.values) == 15
        assert [number(v, 2) for v in p.noazi.values] == [
            pattern_value(code, None, z) for z in a.zeniths]
    assert number(a.frequencies["G05"].offset.up, 2) == 9200     # Z for a satellite


def test_blank_serial_is_every_antenna_of_the_type():
    a = antex.read(text_of(FILE)).antennas[2]
    assert a.serial == " " * 20 and a.sinex_code is None and a.comments == ()
    assert a.azimuths == tuple(range(0, 3601, 300)) and len(a.frequencies["R01"].rows) == 13


@pytest.mark.parametrize("where", ["each", "last"])
def test_rms_sections(where):
    lines = header() + antenna("EXAMPLE_ANT     NONE", dazi=900, zen=(0, 900, 150),
                               codes=("G01", "E05"), rms=where)
    text = text_of(lines)
    file = antex.read(text)
    assert antex.write(file) == text
    a = file.antennas[0]
    kinds = [(p.code, p.rms) for p in a.patterns]
    assert kinds == {"each": [("G01", False), ("G01", True), ("E05", False), ("E05", True)],
                     "last": [("G01", False), ("E05", False), ("G01", True), ("E05", True)]}[
                         where]
    assert list(a.frequencies) == ["G01", "E05"] == list(a.rms)
    rms = a.rms["E05"]
    assert rms.start.label.rstrip() == "START OF FREQ RMS"
    assert rms.end.label.rstrip() == "END OF FREQ RMS"
    assert [number(f, 2) for f in (rms.offset.north, rms.offset.east, rms.offset.up)] == [1, 2, 3]
    assert len(rms.rows) == 5 and len(rms.noazi.values) == 7
    assert not a.frequencies["E05"].rms and number(a.frequencies["E05"].offset.up, 2) == 9100


def test_what_the_document_leaves_open_is_kept():
    lines = header() + antenna("EXAMPLE_ANT     NONE", dazi=0, zen=(0, 100, 50),
                               codes=("I05", "C05"))
    lines[3] = lines[3].rstrip()                 # a label whose trailing blanks were cut
    start = lines.index(labelled("", "START OF ANTENNA"))
    noazi = start + 8
    assert lines[noazi].startswith("   NOAZI")
    lines[noazi] += "  "                         # blanks after the last value
    lines[start] = labelled("", "START OF ANTENNA", pad=False)
    text = text_of(lines)
    file = antex.read(text)
    assert antex.write(file) == text
    a = file.antennas[0]
    assert a.records[0].label == "START OF ANTENNA" and file.header[-1].label == "END OF HEADER"
    assert list(a.frequencies) == ["I05", "C05"]           # not in FREQUENCIES, kept
    assert a.frequencies["I05"].noazi.trailing == "  "
    assert a.frequencies["I05"].noazi.values == tuple(
        fixed(pattern_value("I05", None, z), 2, 8) for z in (0, 50, 100))
    # Columns the table skips (X) are kept, not checked.
    marked = text.replace(labelled("", "END OF ANTENNA"), labelled("x", "END OF ANTENNA"))
    assert antex.write(antex.read(marked)) == marked


# --- malformed input -------------------------------------------------------------------

def index(lines: list[str], label: str, nth: int = 0) -> int:
    return [i for i, line in enumerate(lines) if line[60:].rstrip() == label][nth]


def changed(lines: list[str], at: int, *new: str) -> list[str]:
    return lines[:at] + list(new) + lines[at + 1:]


def with_content(lines: list[str], label: str, content: str, nth: int = 0) -> list[str]:
    at = index(lines, label, nth)
    return changed(lines, at, labelled(content, label))


SMALL = header() + antenna("EXAMPLE_ANT     NONE", dazi=1200, zen=(0, 900, 300),
                           codes=("G01", "G02"), sinex="EXMPL_0001", comments=("c",))
G01, G02 = index(SMALL, "START OF FREQUENCY", 0), index(SMALL, "START OF FREQUENCY", 1)
ROWS = G01 + 2                                  # the NOAZI row of G01; azimuth rows follow
RMS_G01 = section("G01", (1, 2, 3), 1200, [0, 300, 600, 900], rms=True)

MALFORMED = {
    "no header": SMALL[1:],
    "header out of order": [SMALL[1], SMALL[0], *SMALL[2:]],
    "no PCV TYPE / REFANT": changed(SMALL, 1),
    "no END OF HEADER": changed(SMALL, index(SMALL, "END OF HEADER")),
    "header only begun": SMALL[:2],
    "comment after END OF HEADER": changed(SMALL, 3, SMALL[3], labelled("late", "COMMENT")),
    "unknown header label": changed(SMALL, 2, labelled("", "MARKER NAME")),
    "system not listed": with_content(SMALL, "ANTEX VERSION / SYST",
                                      fixed(14, 1, 8) + " " * 12 + "X"),
    "version not a number": with_content(SMALL, "ANTEX VERSION / SYST", "     one" + " " * 12
                                         + "M"),
    "PCV type not A or R": with_content(SMALL, "PCV TYPE / REFANT", "Q"),
    "no TYPE / SERIAL NO": changed(SMALL, index(SMALL, "TYPE / SERIAL NO")),
    "METH after DAZI": changed(changed(SMALL, index(SMALL, "DAZI"),
                                       SMALL[index(SMALL, "METH / BY / # / DATE")]),
                               index(SMALL, "METH / BY / # / DATE"),
                               SMALL[index(SMALL, "DAZI")]),
    "no # OF FREQUENCIES": changed(SMALL, index(SMALL, "# OF FREQUENCIES")),
    "comment before SINEX CODE": changed(changed(SMALL, index(SMALL, "COMMENT", 1),
                                                 SMALL[index(SMALL, "SINEX CODE")]),
                                         index(SMALL, "SINEX CODE"),
                                         SMALL[index(SMALL, "COMMENT", 1)]),
    "VALID UNTIL before VALID FROM": changed(
        SMALL, index(SMALL, "SINEX CODE"),
        labelled("  2020     1     1     0     0    0.0000000", "VALID UNTIL"),
        labelled("  2010     1     1     0     0    0.0000000", "VALID FROM")),
    "two SINEX CODE": changed(SMALL, index(SMALL, "SINEX CODE"),
                              *[SMALL[index(SMALL, "SINEX CODE")]] * 2),
    "comment inside a frequency section": changed(SMALL, G01, SMALL[G01],
                                                  labelled("no", "COMMENT")),
    "comment between frequency sections": changed(SMALL, G02, labelled("no", "COMMENT"),
                                                  SMALL[G02]),
    "no NORTH / EAST / UP": changed(SMALL, G01 + 1),
    "no NOAZI row": changed(SMALL, ROWS),
    "NOAZI out of its columns": changed(SMALL, ROWS, "  NOAZI " + SMALL[ROWS][8:]),
    "NOAZI row a value short": changed(SMALL, ROWS, SMALL[ROWS][:-8]),
    "NOAZI row a value long": changed(SMALL, ROWS, SMALL[ROWS] + "    0.00"),
    "azimuth row a value short": changed(SMALL, ROWS + 2, SMALL[ROWS + 2][:-8]),
    "azimuth row a column short": changed(SMALL, ROWS + 2, SMALL[ROWS + 2][:-1]),
    "azimuth row a value long": changed(SMALL, ROWS + 2, SMALL[ROWS + 2] + "    0.00"),
    "an azimuth row missing": changed(SMALL, ROWS + 3),
    "an azimuth row too many": changed(SMALL, ROWS + 4, SMALL[ROWS + 4],
                                       fixed(4800, 1, 8) + SMALL[ROWS + 4][8:]),
    "azimuth rows out of order": changed(changed(SMALL, ROWS + 1, SMALL[ROWS + 2]), ROWS + 2,
                                         SMALL[ROWS + 1]),
    "an azimuth off the grid": changed(SMALL, ROWS + 2, fixed(1100, 1, 8)
                                       + SMALL[ROWS + 2][8:]),
    "an azimuth that is not F8.1": changed(SMALL, ROWS + 2, "     120" + SMALL[ROWS + 2][8:]),
    "azimuth rows under DAZI 0.0": with_content(SMALL, "DAZI", "     0.0"),
    "no azimuth rows under DAZI 120.0": SMALL[:ROWS + 1] + SMALL[ROWS + 5:],
    "END OF FREQUENCY of another code": with_content(SMALL, "END OF FREQUENCY", "   G02"),
    "no END OF FREQUENCY": changed(SMALL, index(SMALL, "END OF FREQUENCY")),
    "END OF FREQ RMS ends a frequency": changed(SMALL, index(SMALL, "END OF FREQUENCY"),
                                                labelled("   G01", "END OF FREQ RMS")),
    "frequency code without digits": with_content(
        with_content(SMALL, "START OF FREQUENCY", "   GL1"), "END OF FREQUENCY", "   GL1"),
    "frequency code out of its columns": with_content(
        with_content(SMALL, "START OF FREQUENCY", "G01"), "END OF FREQUENCY", "G01"),
    "a frequency twice": with_content(
        with_content(SMALL, "START OF FREQUENCY", "   G01", 1), "END OF FREQUENCY", "   G01", 1),
    "fewer frequencies than announced": with_content(SMALL, "# OF FREQUENCIES", "     3"),
    "more frequencies than announced": with_content(SMALL, "# OF FREQUENCIES", "     1"),
    "# OF FREQUENCIES blank": with_content(SMALL, "# OF FREQUENCIES", ""),
    "rms before its frequency": SMALL[:G01] + RMS_G01 + SMALL[G01:],
    "rms twice": SMALL[:G02] + RMS_G01 + RMS_G01 + SMALL[G02:],
    "rms of a frequency the antenna lacks": SMALL[:G02] + section(
        "G05", (1, 2, 3), 1200, [0, 300, 600, 900], rms=True) + SMALL[G02:],
    "DAZI that does not divide 360": with_content(SMALL, "DAZI", "     7.0"),
    "DAZI negative": with_content(SMALL, "DAZI", "  -120.0"),
    "DAZI blank": with_content(SMALL, "DAZI", ""),
    "DAZI without its decimal": with_content(SMALL, "DAZI", "     120"),
    "DZEN 0.0": with_content(SMALL, "ZEN1 / ZEN2 / DZEN", "     0.0  90.0   0.0"),
    "ZEN2 not above ZEN1": with_content(SMALL, "ZEN1 / ZEN2 / DZEN", "    90.0  90.0  30.0"),
    "ZEN2 not a multiple of DZEN": with_content(SMALL, "ZEN1 / ZEN2 / DZEN",
                                                "     0.0  80.0  30.0"),
    "ZEN1 not a multiple of DZEN": with_content(SMALL, "ZEN1 / ZEN2 / DZEN",
                                                "    10.0  90.0  30.0"),
    "grid that disagrees with the rows": with_content(SMALL, "ZEN1 / ZEN2 / DZEN",
                                                      "     0.0  90.0  10.0"),
    "no END OF ANTENNA": SMALL[:-1],
    "the file ends inside a section": SMALL[:ROWS + 2],
    "the file ends inside the antenna's records": SMALL[:index(SMALL, "DAZI")],
    "END OF ANTENNA twice": [*SMALL, SMALL[-1]],
    "a blank line after the antenna": [*SMALL, ""],
    "a blank line between records": changed(SMALL, index(SMALL, "DAZI"), "",
                                            SMALL[index(SMALL, "DAZI")]),
    "text after the last antenna": [*SMALL, "more"],
    "a label past column 80": changed(SMALL, index(SMALL, "DAZI"),
                                      SMALL[index(SMALL, "DAZI")] + " "),
    "a label out of its columns": changed(SMALL, index(SMALL, "DAZI"),
                                          SMALL[index(SMALL, "DAZI")][1:]),
    "a lowercase label": changed(SMALL, index(SMALL, "DAZI"),
                                 SMALL[index(SMALL, "DAZI")].lower()),
    "an antenna that does not start": changed(SMALL, index(SMALL, "START OF ANTENNA")),
}


def test_the_base_of_the_malformed_files_is_accepted():
    assert antex.write(antex.read(text_of(SMALL))) == text_of(SMALL)
    assert antex.read(text_of(SMALL[:G02] + RMS_G01 + SMALL[G02:])).antennas[0].rms


@pytest.mark.parametrize("name", MALFORMED)
def test_malformed(name):
    with pytest.raises(Invalid):
        antex.read(text_of(MALFORMED[name]))


def test_malformed_text():
    text = text_of(SMALL)
    for bad in ("", "\n", text.replace("\n", "\r\n", 3), text.replace("COMMENT", "COMM\rNT", 1),
                text.replace("\n", "\r"), text.encode()):
        with pytest.raises(Invalid):
            antex.read(bad)


@pytest.mark.parametrize("version", [13, 10, 20, 140])
def test_other_versions_are_unsupported(version):
    lines = with_content(SMALL, "ANTEX VERSION / SYST", fixed(version, 1, 8) + " " * 12 + "M")
    with pytest.raises(Unsupported, match="only 1.4"):
        antex.read(text_of(lines))


def test_errors_derive_from_error():
    assert issubclass(antex.Error, ValueError)
    assert issubclass(Invalid, antex.Error) and issubclass(Unsupported, antex.Error)
    assert issubclass(Unsupported, LookupError)
    with pytest.raises(Invalid, match=f"line {G01 + 2}: expected NORTH / EAST / UP"):
        antex.read(text_of(changed(SMALL, G01 + 1)))
    with pytest.raises(Invalid, match="needs 4 values"):
        antex.read(text_of(MALFORMED["azimuth row a value short"]))
    with pytest.raises(Invalid, match="2 frequency sections, # OF FREQUENCIES says 3"):
        antex.read(text_of(MALFORMED["fewer frequencies than announced"]))


# --- records, fields and numbers -------------------------------------------------------

def test_fields_and_record_are_inverse():
    file = antex.read(text_of(FILE + antenna("EXAMPLE_ANT     NONE", dazi=0, codes=("G01",),
                                             rms="each")))
    seen = set()
    for a in file.antennas:
        every = [*file.header, *a.records, a.end]
        for p in a.patterns:
            every += [p.start, p.neu, p.end]
        for r in every:
            name = r.label.rstrip()
            seen.add(name)
            f = antex.fields(r)
            assert type(f) is antex.TABLE[name]
            assert antex.record(name, f) == r
    assert seen == set(antex.TABLE)
    assert antex.record("END OF HEADER") == Record(" " * 60, "END OF HEADER".ljust(20))
    assert antex.record("DAZI", antex.Dazi("     5.0")).content == "     5.0".ljust(60)
    for bad in (lambda: antex.record("DAZI", antex.Dazi("5.0")),            # not 8 columns
                lambda: antex.record("DAZI", antex.Dazi("     5.0\n")),
                lambda: antex.record("DAZI", antex.Dazi(5.0)),
                lambda: antex.record("DAZI", antex.SinexCode("EXMPL_0001")),
                lambda: antex.record("DAZI"),
                lambda: antex.record("MARKER NAME", antex.Blank()),
                lambda: antex.fields(Record(" " * 60, "MARKER NAME")),
                lambda: antex.fields(Record(" " * 59, "DAZI"))):
        with pytest.raises(Invalid):
            bad()


def test_number():
    assert number("     -0.87", 2) == -87 and number("    90.0", 1) == 900
    assert number("     3    ") == 3 and number("     1.4            ", 1) == 14
    assert number("    -.50", 2) == -50 and number("   +1.25", 2) == 125
    assert number("        ") is None and number("") is None
    for field, decimals in (("    1.5", 2), ("     15", 1), ("    1.5", 0), ("   NOAZI", 1),
                            ("  1 .5", 1), ("      .", 1), ("    1e3", 0)):
        with pytest.raises(antex.Error):
            number(field, decimals)
    assert not isinstance(pytest.raises(antex.Error, number, "x").value, Invalid)


# --- writing ---------------------------------------------------------------------------

def test_a_file_built_from_records():
    grid = antex.record("ZEN1 / ZEN2 / DZEN", antex.Grid("     0.0", "  10.0", "   5.0"))
    code = antex.FrequencyCode("   E01")
    a = Antenna(
        records=(antex.record("START OF ANTENNA"),
                 antex.record("TYPE / SERIAL NO", antex.TypeSerial(
                     "EXAMPLE_ANT     NONE", " " * 20, " " * 10, " " * 10)),
                 antex.record("METH / BY / # / DATE", antex.Method(
                     "FIELD".ljust(20), "Example Agency".ljust(20), "     1    ", " " * 10)),
                 antex.record("DAZI", antex.Dazi("     0.0")), grid,
                 antex.record("# OF FREQUENCIES", antex.Frequencies("     1"))),
        patterns=(Pattern(antex.record("START OF FREQUENCY", code),
                          antex.record("NORTH / EAST / UP", antex.Offset(
                              "      1.00", "     -2.00", "    100.00")),
                          Row(antex.NOAZI, ("    0.00", "   -0.25", "    1.50")), (),
                          antex.record("END OF FREQUENCY", code)),),
        end=antex.record("END OF ANTENNA"))
    file = AntexFile(
        (antex.record("ANTEX VERSION / SYST", antex.Version("     1.4".ljust(20), "E")),
         antex.record("PCV TYPE / REFANT", antex.PcvType("A".ljust(20), " " * 20, " " * 20)),
         antex.record("END OF HEADER")), (a,))
    text = antex.write(file)
    assert text.splitlines() == [
        labelled("     1.4            E", "ANTEX VERSION / SYST"),
        labelled("A", "PCV TYPE / REFANT"),
        labelled("", "END OF HEADER"),
        labelled("", "START OF ANTENNA"),
        labelled("EXAMPLE_ANT     NONE", "TYPE / SERIAL NO"),
        labelled("FIELD               Example Agency           1", "METH / BY / # / DATE"),
        labelled("     0.0", "DAZI"),
        labelled("     0.0  10.0   5.0", "ZEN1 / ZEN2 / DZEN"),
        labelled("     1", "# OF FREQUENCIES"),
        labelled("   E01", "START OF FREQUENCY"),
        labelled("      1.00     -2.00    100.00", "NORTH / EAST / UP"),
        "   NOAZI    0.00   -0.25    1.50",
        labelled("   E01", "END OF FREQUENCY"),
        labelled("", "END OF ANTENNA"),
    ]
    assert antex.read(text) == file
    assert antex.write(dataclasses.replace(file, newline="\r\n", final_newline=False)) \
        == text[:-1].replace("\n", "\r\n")


def test_write_refuses_what_read_would_not_give():
    file = antex.read(text_of(SMALL))
    a = file.antennas[0]
    p = a.patterns[0]

    def antenna_with(**changes) -> AntexFile:
        return dataclasses.replace(file, antennas=(dataclasses.replace(a, **changes),))

    def pattern_with(**changes) -> AntexFile:
        return antenna_with(patterns=(dataclasses.replace(p, **changes), *a.patterns[1:]))

    short = Row(p.rows[0].azimuth, p.rows[0].values[:-1])
    bad = {
        "newline": dataclasses.replace(file, newline="\r"),
        "final_newline": dataclasses.replace(file, final_newline=None),
        "header a list": dataclasses.replace(file, header=list(file.header)),
        "antennas a list": dataclasses.replace(file, antennas=list(file.antennas)),
        "no header": dataclasses.replace(file, header=()),
        "header not records": dataclasses.replace(file, header=("x" * 80, *file.header[1:])),
        "antenna not an Antenna": dataclasses.replace(file, antennas=(None,)),
        "records out of order": antenna_with(records=a.records[::-1]),
        "end not END OF ANTENNA": antenna_with(end=a.records[0]),
        "a pattern dropped": antenna_with(patterns=a.patterns[:1]),
        "pattern not a Pattern": antenna_with(patterns=(p.noazi,)),
        "content short": antenna_with(records=(Record("", "START OF ANTENNA"), *a.records[1:])),
        "content not text": antenna_with(records=(Record(None, "START OF ANTENNA"),
                                                  *a.records[1:])),
        "label too long": antenna_with(end=Record(" " * 60, "END OF ANTENNA".ljust(21))),
        "line break in a label": antenna_with(end=Record(" " * 60, "END OF ANTENNA\n")),
        "row short": pattern_with(rows=(short, *p.rows[1:])),
        "row missing": pattern_with(rows=p.rows[1:]),
        "rows a list": pattern_with(rows=list(p.rows)),
        "values a list": pattern_with(noazi=Row(p.noazi.azimuth, list(p.noazi.values))),
        "value not text": pattern_with(noazi=Row(p.noazi.azimuth, (0.0, *p.noazi.values[1:]))),
        "value narrow": pattern_with(noazi=Row(p.noazi.azimuth, ("0.00", *p.noazi.values[1:]))),
        "values split otherwise": pattern_with(noazi=Row(p.noazi.azimuth, (
            p.noazi.values[0] + p.noazi.values[1], *p.noazi.values[2:]))),
        "line break in a value": pattern_with(noazi=Row(p.noazi.azimuth, (
            "   0.0\n", *p.noazi.values[1:]))),
        "trailing not blank": pattern_with(noazi=Row(p.noazi.azimuth, p.noazi.values, "x")),
        "noazi not a Row": pattern_with(noazi=p.neu),
        "neu not a Record": pattern_with(neu=p.noazi),
        "end of another frequency": pattern_with(end=a.patterns[1].end),
        "not a file": a,
    }
    assert antex.write(file) == text_of(SMALL)
    for name, value in bad.items():
        with pytest.raises(Invalid):
            antex.write(value)
            pytest.fail(name)
    other = dataclasses.replace(file, header=(
        antex.record("ANTEX VERSION / SYST", antex.Version("     1.3".ljust(20), "M")),
        *file.header[1:]))
    with pytest.raises(Unsupported):
        antex.write(other)


# --- generated files -------------------------------------------------------------------

DIVISORS_OF_360 = [d for d in range(5, 3601, 5) if 3600 % d == 0 and d >= 150]
CODES = st.lists(st.sampled_from(sorted(antex.FREQUENCIES) + ["C05", "I05", "R04"]),
                 min_size=0, max_size=4, unique=True)


@st.composite
def antennas(draw) -> list[str]:
    dzen = draw(st.sampled_from([5, 10, 50, 100, 150]))
    zen1 = dzen * draw(st.integers(0, 3))
    zen2 = zen1 + dzen * draw(st.integers(1, 8))
    satellite = draw(st.booleans())
    return antenna(
        "BLOCK IIR-M" if satellite else "EXAMPLE_ANT     NONE",
        draw(st.sampled_from(["", "G07", "R24", "SN 0042"])),
        "G048" if satellite else "", "2008-012A" if satellite else "",
        dazi=draw(st.sampled_from([0, *DIVISORS_OF_360])), zen=(zen1, zen2, dzen),
        codes=tuple(draw(CODES)), rms=draw(st.sampled_from(["", "each", "last"])),
        valid_from=draw(st.sampled_from([None, (2008, 3, 15, 0, 0, 0)])),
        valid_until=draw(st.sampled_from([None, (2030, 12, 31, 23, 59, 599999999)])),
        sinex=draw(st.sampled_from([None, "EXMPL_0001"])),
        comments=tuple(draw(st.lists(st.text("abc XYZ#:/.-", max_size=60), max_size=3))))


@settings(max_examples=60, deadline=None)
@given(st.lists(antennas(), max_size=4), st.sampled_from(["\n", "\r\n"]), st.booleans())
def test_generated_files_round_trip(sections, newline, final):
    lines = header() + [line for s in sections for line in s]
    text = text_of(lines, newline, final)
    file = antex.read(text)
    assert antex.write(file) == text
    assert len(file.antennas) == len(sections)
    for a, s in zip(file.antennas, sections, strict=True):
        n = number(antex.fields(a.records[5]).count)
        assert len(a.frequencies) == n and len(a.rms) in (0, n)
        rows = 1 + len(a.azimuths)
        assert len(s) == len(a.records) + 1 + len(a.patterns) * (3 + rows)
        for p in a.patterns:
            assert len(p.rows) == len(a.azimuths)
            assert all(len(r.values) == len(a.zeniths) for r in (p.noazi, *p.rows))
