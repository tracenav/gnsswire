"""RINEX 2 observation files against RINEX 2.11, Tables A1 and A2.

- The record tables are transcribed a second time here, column for column.
- Files are built line by line from the tables' Fortran formats, with the
  values of the document's examples: Table A7 ("GPS observation data file -
  example") whole and the first epoch of Table A14 ("mixed GPS/GLONASS
  observation file - example", 14 satellites).
- Where the document is staged (refs/RINEX_2.11.txt, not committed), the
  files built here are compared with the examples it prints, and its four
  observation file examples (Tables A7, A13, A14, A17) are read and written
  back; those tests skip without it.
- Generated files round-trip: ``write2(read2(text)) == text``.
"""

import hashlib
import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import rinex
from gnsswire.rinex import (
    Epoch2,
    EpochRecord2,
    HeaderRecord,
    Invalid,
    Observation,
    ObsFile2,
    SatelliteList,
    SatelliteRecord,
    Unsupported,
    full_year,
    number,
    sat_name,
)
from gnsswire.rinex._records import join

SPEC = Path(__file__).resolve().parents[3] / "refs" / "RINEX_2.11.txt"
SPEC_SHA256 = "59042b80"

# (field, width, format) as Table A2 prints the EPOCH/SAT record and its
# continuation line.
EPOCH_TABLE = [("year", 3, "1X,I2.2"), ("month", 3, "1X,I2"), ("day", 3, "1X,I2"),
               ("hour", 3, "1X,I2"), ("minute", 3, "1X,I2"), ("second", 11, "F11.7"),
               ("flag", 3, "2X,I1"), ("count", 3, "I3"), ("sats", 36, "12(A1,I2)"),
               ("clock", 12, "F12.9")]
LIST_TABLE = [("blank", 32, "32X"), ("sats", 36, "12(A1,I2)")]


def test_tables_are_the_document():
    assert [(n, c.width, c.fmt) for n, c in rinex.columns(EpochRecord2)] == EPOCH_TABLE
    assert [(n, c.width, c.fmt) for n, c in rinex.columns(SatelliteList)] == LIST_TABLE
    # The OBSERVATIONS record, m(F14.3,I1,I1), is the Observation of RINEX 3.
    assert [(n, c.width, c.fmt) for n, c in rinex.columns(Observation)] == [
        ("value", 14, "F14.3"), ("lli", 1, "I1"), ("ssi", 1, "I1")]
    assert rinex.SYSTEMS2 == "GRSE" and rinex.OBS_TYPES2 == "# / TYPES OF OBSERV"


def test_epoch_columns():
    # Table A2 by column, 1-based: year 2-3, month 5-6, day 8-9, hour 11-12,
    # minute 14-15, second 16-26, flag 29, count 30-32, the list 33-68, the
    # clock offset 69-80: a record of 80 columns.
    record = EpochRecord2(" YY", " MM", " DD", " hh", " mm", "sssssssssss", "  F", "CCC",
                          "L" * 36, "o" * 12)
    line = join(record)
    assert len(line) == 80
    spans = {c: (line.index(c) + 1, line.rindex(c) + 1) for c in "YMDhmsFCLo"}
    assert spans == {"Y": (2, 3), "M": (5, 6), "D": (8, 9), "h": (11, 12), "m": (14, 15),
                     "s": (16, 26), "F": (29, 29), "C": (30, 32), "L": (33, 68),
                     "o": (69, 80)}
    assert join(SatelliteList(" " * 32, "L" * 36)).index("L") == 32


# ---- building files from the formats ------------------------------------------

def h(content: str, label: str) -> str:
    """A header line: A60 content, then the label (Table A1)."""
    assert len(content) <= 60
    return content.ljust(60) + label


def types_lines(types: list[str]) -> list[str]:
    """# / TYPES OF OBSERV: I6,9(4X,A1,A1), continuation lines 6X,9(4X,2A1)."""
    out = []
    for i in range(0, max(len(types), 1), 9):
        head = f"{len(types):6d}" if i == 0 else " " * 6
        out.append(h(head + "".join(f"    {t}" for t in types[i:i + 9]), "# / TYPES OF OBSERV"))
    return out


def epoch(time=None, flag=0, sats=(), clock=None, count=None) -> list[str]:
    """EPOCH/SAT: 1X,I2.2,4(1X,I2),F11.7,2X,I1,I3,12(A1,I2),F12.9; then 32X,12(A1,I2)."""
    if time is None:
        head = " " * 26
    else:
        year, *rest, sec = time
        head = f" {year:02d}" + "".join(f" {v:2d}" for v in rest) + f"{sec:11.7f}"
    head += f"  {flag:1d}{len(sats) if count is None else count:3d}"
    lines = [head + "".join(sats[:12])]
    if clock is not None:
        lines[0] = lines[0].ljust(68) + f"{clock:>12}"
    return lines + [" " * 32 + "".join(sats[i:i + 12]) for i in range(12, len(sats), 12)]


def obs(types: int, *fields: str | None) -> list[str]:
    """OBSERVATIONS: m(F14.3,I1,I1), five to a line, trailing blanks truncated.

    A field is ``None`` (blank) or ``"value"`` or ``"value|LS"`` with the LLI
    and signal strength columns.
    """
    assert len(fields) <= types
    cells = []
    for f in fields:
        value, _, flags = (f or "").partition("|")
        cells.append(f"{value:>14}{flags:<2}")
    return ["".join(cells[i:i + 5]).rstrip() for i in range(0, 5 * -(-types // 5), 5)]


def file(body=(), types=("C1", "L1"), version="2.11", extra_header=(), newline="\n") -> str:
    header = [h(f"{version:>9}{'':11}OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
              h("XXRINEXO V9.9       AIUB                24-MAR-01 14:43", "PGM / RUN BY / DATE")]
    if types is not None:
        header += types_lines(list(types))
    header += [*extra_header, h("", "END OF HEADER")]
    return newline.join([*header, *body]) + newline


T = (5, 3, 24, 13)
CLOCK = "-.123456789"

A7_HEADER = [
    h("     2.11           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
    h("BLANK OR G = GPS,  R = GLONASS,  E = GALILEO,  M = MIXED", "COMMENT"),
    h("XXRINEXO V9.9       AIUB                24-MAR-01 14:43", "PGM / RUN BY / DATE"),
    h("EXAMPLE OF A MIXED RINEX FILE (NO FEATURES OF V 2.11)", "COMMENT"),
    h("A 9080", "MARKER NAME"),
    h("9080.1.34", "MARKER NUMBER"),
    h("BILL SMITH          ABC INSTITUTE", "OBSERVER / AGENCY"),
    h("X1234A123           XX                  ZZZ", "REC # / TYPE / VERS"),
    h("234                 YY", "ANT # / TYPE"),
    h("  4375274.       587466.      4589095.", "APPROX POSITION XYZ"),
    h("         .9030         .0000         .0000", "ANTENNA: DELTA H/E/N"),
    h("     1     1", "WAVELENGTH FACT L1/2"),
    h("     1     2     6   G14   G15   G16   G17   G18   G19", "WAVELENGTH FACT L1/2"),
    h("     0", "RCV CLOCK OFFS APPL"),
    *types_lines(["P1", "L1", "L2", "P2", "L5"]),
    h("    18.000", "INTERVAL"),
    h("  2005     3    24    13    10   36.0000000", "TIME OF FIRST OBS"),
    h("", "END OF HEADER"),
]
A7_BODY = [
    *epoch((*T, 10, 36.0), 0, ["G12", "G09", "G06", "E11"], CLOCK),
    *obs(5, "23629347.915", ".300| 8", "-.353", "23629364.158"),
    *obs(5, "20891534.648", "-.120| 9", "-.358", "20891541.292"),
    *obs(5, "20607600.189", "-.430| 9", ".394", "20607605.848"),
    *obs(5, None, ".324| 8", None, None, ".178| 7"),
    *epoch((*T, 10, 50.0), 4, count=4),
    h("     1     2     2   G 9   G12", "WAVELENGTH FACT L1/2"),
    h("  *** WAVELENGTH FACTOR CHANGED FOR 2 SATELLITES ***", "COMMENT"),
    h("      NOW 8 SATELLITES HAVE WL FACT 1 AND 2!", "COMMENT"),
    h("", "COMMENT"),
    *epoch((*T, 10, 54.0), 0, ["G12", "G09", "G06", "R21", "R22", "E11"], CLOCK),
    *obs(5, "23619095.450", "-53875.632| 8", "-41981.375", "23619112.008"),
    *obs(5, "20886075.667", "-28688.027| 9", "-22354.535", "20886082.101"),
    *obs(5, "20611072.689", "18247.789| 9", "14219.770", "20611078.410"),
    *obs(5, "21345678.576", "12345.567| 5"),
    *obs(5, "22123456.789", "23456.789| 5"),
    *obs(5, None, "65432.123| 5", None, None, "48861.586| 7"),
    *epoch((*T, 11, 0.0), 2, count=1),
    h("            *** FROM NOW ON KINEMATIC DATA! ***", "COMMENT"),
    *epoch((*T, 11, 48.0), 0, ["G16", "G12", "G09", "G06"], CLOCK),
    *obs(5, "21110991.756", "16119.980| 7", "12560.510", "21110998.441"),
    *obs(5, "23588424.398", "-215050.557| 6", "-167571.734", "23588439.570"),
    *obs(5, "20869878.790", "-113803.187| 8", "-88677.926", "20869884.938"),
    *obs(5, "20621643.727", "73797.462| 7", "57505.177", "20621649.276"),
    *epoch(None, 3, count=4),
    h("A 9080", "MARKER NAME"),
    h("9080.1.34", "MARKER NUMBER"),
    h("         .9030         .0000         .0000", "ANTENNA: DELTA H/E/N"),
    h("          --> THIS IS THE START OF A NEW SITE <--", "COMMENT"),
    *epoch((*T, 12, 6.0), 0, ["G16", "G12", "G06", "G09"], "-.123456987"),
    *obs(5, "21112589.384", "24515.877| 6", "19102.763| 3", "21112596.187"),
    *obs(5, "23578228.338", "-268624.234| 7", "-209317.284| 4", "23578244.398"),
    *obs(5, "20625218.088", "92581.207| 7", "72141.846| 4", "20625223.795"),
    *obs(5, "20864539.693", "-141858.836| 8", "-110539.435| 5", "20864545.943"),
    *epoch((*T, 13, 1.2345678), 5),
    *epoch(None, 4, count=1),
    h("        (AN EVENT FLAG WITH SIGNIFICANT EPOCH)", "COMMENT"),
    *epoch((*T, 14, 12.0), 0, ["G16", "G12", "G09", "G06"], "-.123456012"),
    *obs(5, "21124965.133", "89551.302|16", "69779.626|54", "21124972.275|4"),
    *obs(5, "23507272.372", "-212616.150| 7", "-165674.789| 5", "23507288.421"),
    *obs(5, "20828010.354", "-333820.093| 6", "-260119.395| 5", "20828017.129"),
    *obs(5, "20650944.902", "227775.130| 7", "177487.651| 4", "20650950.363"),
    *epoch(None, 4, count=1),
    h("           *** ANTISPOOFING ON G 16 AND LOST LOCK", "COMMENT"),
    # Cycle slip records: the example writes the slips with one decimal, two
    # columns left of where F14.3 would end.
    *epoch((*T, 14, 12.0), 6, ["G16", "G09"]),
    " " * 17 + "123456789.0" + " " * 6 + "-9876543.5",
    " " * 25 + "0.0" + " " * 12 + "-0.5",
    *epoch(None, 4, count=2),
    h("           ---> CYCLE SLIPS THAT HAVE BEEN APPLIED TO", "COMMENT"),
    h("                THE OBSERVATIONS", "COMMENT"),
    *epoch((*T, 14, 48.0), 0, ["G16", "G12", "G09", "G06"], "-.123456234"),
    *obs(5, "21128884.159", "110143.144| 7", "85825.185|45", "21128890.776|4"),
    *obs(5, "23487131.045", "-318463.297| 7", "-248152.728|24", "23487146.149"),
    *obs(5, "20817844.743", "-387242.571| 6", "-301747.229|25", "20817851.322"),
    *obs(5, "20658519.895", "267583.678|17", "208507.262|34", "20658525.869"),
    *epoch(None, 4, count=3),
    h("         ***   SATELLITE G 9   THIS EPOCH ON WLFACT 1 (L2)", "COMMENT"),
    h("         *** G 6 LOST LOCK AND THIS EPOCH ON WLFACT 2 (L2)", "COMMENT"),
    h("                (OPPOSITE TO PREVIOUS SETTINGS)", "COMMENT"),
]
A7 = "\n".join(A7_HEADER + A7_BODY) + "\n"

# Table A14, the first epoch: 14 satellites, two observation types.
A14_SATS = ["G23", "G07", "G02", "G05", "G26", "G09", "G21", "R20", "R19", "R12", "R02", "R11",
            "R10", "R03"]
A14_EPOCH = [
    *epoch((0, 2, 6, 11, 53, 0.0), 0, A14_SATS),
    *obs(2, "22576523.586", "-11256947.602|12"),
    *obs(2, "22360162.704", "-16225110.754|13"),
    *obs(2, "24484865.974", "14662682.882| 2"),
    *obs(2, "21950524.331", "-13784707.249|12"),
    *obs(2, "22507304.252", "9846064.848| 2"),
    *obs(2, "20148742.213", "-20988953.712| 4"),
    *obs(2, "22800149.591", "-16650822.700|12"),
    *obs(2, "19811403.273", "-25116169.741| 3"),
    *obs(2, "23046997.513", "-3264701.688| 2"),
    *obs(2, "22778170.622", "-821857836.745| 1"),
    *obs(2, "22221283.991", "-988088156.884| 2"),
    *obs(2, "19300913.475", "-83282658.190|13"),
    *obs(2, "20309075.579", "-672668843.847|13"),
    *obs(2, "23397403.484", "-285457101.342|11"),
]
A14 = file(A14_EPOCH)


# ---- the document's examples -------------------------------------------------------

def test_a7_reads_and_writes_back():
    f = rinex.read2(A7)
    assert rinex.write2(f) == A7
    assert f.version == "2.11" and f.newline == "\n" and f.final_newline
    assert rinex.obs_types2(f.header) == ("P1", "L1", "L2", "P2", "L5")
    assert [e.record.flag.strip() for e in f.epochs] == list("040203054046404")
    first = f.epochs[0]
    assert first.record == EpochRecord2(" 05", "  3", " 24", " 13", " 10", " 36.0000000", "  0",
                                        "  4", "G12G09G06E11".ljust(36), " -.123456789")
    assert full_year(first.record.year) == 2005
    assert number(first.record.clock, 9) == -123456789
    assert [s.sat for s in first.satellites] == ["G12", "G09", "G06", "E11"]
    g12 = first.satellites[0]
    assert g12.obs[0] == Observation("  23629347.915", " ", " ")
    assert g12.obs[1] == Observation("          .300", " ", "8")
    assert g12.obs[3] == Observation("  23629364.158", "", "")      # truncated record
    assert [number(o.value, 3) for o in g12.obs] == [23629347915, 300, -353, 23629364158]
    e11 = first.satellites[3]
    assert [number(o.value, 3) for o in e11.obs] == [None, 324, None, None, 178]
    assert e11.obs[4] == Observation("          .178", " ", "7")
    assert first.special == () and first.continuation == ()
    # Flag 4 with header records, flag 2, flag 3 without an epoch, flag 5 without records.
    assert [r.label for r in f.epochs[1].special] == ["WAVELENGTH FACT L1/2", "COMMENT",
                                                      "COMMENT", "COMMENT"]
    assert f.epochs[1].satellites == ()
    assert f.epochs[3].special == (HeaderRecord(
        "            *** FROM NOW ON KINEMATIC DATA! ***".ljust(60), "COMMENT"),)
    site = f.epochs[5]
    assert site.record == EpochRecord2("   ", "   ", "   ", "   ", "   ", " " * 11, "  3", "  4",
                                       "", "")
    assert full_year(site.record.year) is None
    assert site.special[0] == HeaderRecord("A 9080".ljust(60), "MARKER NAME")
    assert f.epochs[7].record.second == "  1.2345678" and f.epochs[7].special == ()
    # LLI and signal strength.
    g16 = f.epochs[9].satellites[0]
    assert (g16.obs[1].lli, g16.obs[1].ssi) == ("1", "6")
    assert g16.obs[3] == Observation("  21124972.275", "4", "")
    # Flag 6: cycle slips for the satellites listed.
    slips = f.epochs[11]
    assert [s.sat for s in slips.satellites] == ["G16", "G09"]
    assert slips.satellites[0].obs == (Observation(" " * 14, " ", " "),
                                       Observation(" 123456789.0  ", " ", " "),
                                       Observation("  -9876543.5", "", ""))
    assert rinex.read2(A7[:-1]).final_newline is False


def test_a14_more_than_12_satellites():
    f = rinex.read2(A14)
    assert rinex.write2(f) == A14
    (e,) = f.epochs
    assert A14_EPOCH[1] == " " * 32 + "R10R03"
    assert e.record.count == " 14" and e.record.sats == "".join(A14_SATS[:12])
    assert e.continuation == (SatelliteList(" " * 32, "R10R03"),)
    assert [s.sat for s in e.satellites] == A14_SATS
    assert full_year(e.record.year) == 2000
    assert e.satellites[13].obs == (Observation("  23397403.484", " ", " "),
                                    Observation("-285457101.342", "1", "1"))


def spec_examples() -> dict[str, str]:
    """The observation file examples of the staged document, by table."""
    if not SPEC.is_file():
        pytest.skip("refs/RINEX_2.11.txt is not staged")
    data = SPEC.read_bytes()
    if not hashlib.sha256(data).hexdigest().startswith(SPEC_SHA256):
        pytest.skip("refs/RINEX_2.11.txt is another copy of the document")
    lines = data.decode("ascii").split("\n")
    out = {}
    for table in ("A7", "A13", "A14", "A17"):
        title = next(i for i, line in enumerate(lines) if re.search(rf"TABLE {table}\s", line))
        ruler = [i for i in range(title, len(lines)) if lines[i].startswith("----|---1|0---")][:2]
        out[table] = "\n".join(lines[ruler[0] + 2:ruler[1] - 1]) + "\n"
    return out


def test_the_files_built_here_are_the_documents_examples():
    examples = spec_examples()
    assert examples["A7"] == A7
    a14 = examples["A14"].split("\n")
    start = a14.index(h("", "END OF HEADER")) + 1
    assert a14[start:start + len(A14_EPOCH)] == A14_EPOCH


def test_the_documents_examples_read_and_write_back():
    examples = spec_examples()
    counts = {}
    for table, text in examples.items():
        f = rinex.read2(text)
        assert rinex.write2(f) == text, table
        assert f.version == "2.11"
        counts[table] = [len(e.satellites) for e in f.epochs]
    assert counts["A13"] == [3, 3, 3, 5, 5, 5]
    assert counts["A14"] == [14, 14] and counts["A17"] == [8, 8, 8]
    # Table A13 lists a satellite with a blank system identifier.
    a13 = rinex.read2(examples["A13"])
    assert [s.sat for s in a13.epochs[0].satellites] == ["  2", "R01", "R21"]
    assert a13.epochs[2].record.second == "   .0490000"
    assert full_year(a13.epochs[0].record.year) == 1993
    # Table A17: four types, the GEO satellite's record truncated after two.
    a17 = rinex.read2(examples["A17"])
    assert [len(s.obs) for s in a17.epochs[0].satellites] == [4] * 7 + [2]
    assert a17.epochs[0].record.clock == " 0.000535140"


# ---- satellite numbers and years ----------------------------------------------------

def test_blank_system_identifier_is_gps():
    # Section 5.1: "G or blank: GPS"; the number is I2.
    text = file([*epoch((*T, 10, 36.0), 0, ["  2", " 12", "G 9", "R01", "S20", "E11"]),
                 *[line for _ in range(6) for line in obs(2, "1.000")]])
    f = rinex.read2(text)
    assert rinex.write2(f) == text
    assert [s.sat for s in f.epochs[0].satellites] == ["  2", " 12", "G 9", "R01", "S20", "E11"]
    assert [sat_name(s.sat) for s in f.epochs[0].satellites] == ["G02", "G12", "G09", "R01",
                                                                 "S20", "E11"]
    for bad in ("C01", "G1", "G1 ", "GG1", "", "g01", 1):
        with pytest.raises(rinex.Error):
            sat_name(bad)


@pytest.mark.parametrize("field, year", [(" 80", 1980), (" 99", 1999), (" 00", 2000),
                                         (" 79", 2079), ("  5", 2005), ("   ", None), ("", None)])
def test_two_digit_years(field, year):
    # Section 6.5: 80-99 are 1980-1999, 00-79 are 2000-2079.
    assert full_year(field) == year


@pytest.mark.parametrize("field", ["2005", " -1", " 5.", " xx"])
def test_two_digit_years_refuse(field):
    with pytest.raises(rinex.Error):
        full_year(field)


# ---- observation types and continuation lines ---------------------------------------

def test_obs_types_continuation_lines():
    types = [c + b for b in "125678" for c in "CLDS"][:20]
    lines = types_lines(types)
    assert len(lines) == 3 and lines[1][:10] == " " * 10 and lines[1][60:] == "# / TYPES OF OBSERV"
    assert lines[0][:18] == "    20    C1    L1"
    f = rinex.read2(file(types=types))
    assert rinex.obs_types2(f.header) == tuple(types)
    assert rinex.obs_types2(f.header[:2]) is None
    assert rinex.obs_types2(f.header[:2], ("C1",)) == ("C1",)
    with pytest.raises(Invalid, match="20 types, says 21"):
        rinex.read2(file(types=types).replace("    20    C1", "    21    C1"))
    with pytest.raises(Invalid, match="continuation line without"):
        rinex.read2(file(types=types).replace("    20    C1", "          C1"))
    with pytest.raises(Invalid, match="not blank"):
        rinex.read2(file(types=types).replace("    20    C1", "    20   xC1"))
    with pytest.raises(Invalid, match="not I6"):
        rinex.read2(file(types=types).replace("    20    C1", "    2x    C1"))


def test_more_than_five_observation_types():
    # Table A2: "If more than 5 observation types (=80 char): continue
    # observations in next record"; 12 types are three lines per satellite.
    types = ["C1", "L1", "D1", "S1", "P1", "C2", "L2", "D2", "S2", "P2", "C5", "L5"]
    full = [f"{i}.000|{i % 10}{9 - i % 10}" for i in range(1, 13)]
    body = [*epoch((*T, 10, 36.0), 0, ["G01", "G02", "G03", "G04", "G05"]),
            *obs(12, *full),                          # 80, 80 and 32 columns
            *obs(12, "1.000", "2.000"),               # the other two lines empty
            *obs(12, *[None] * 5, "6.000"),           # the first line empty
            *obs(12, "1.000", *[None] * 9, "11.000"),  # short, empty, short
            *obs(12)]                                 # no observation at all
    assert [len(line) for line in body[1:4]] == [80, 80, 32]
    assert body[4:7] == ["         1.000           2.000", "", ""]
    assert body[13:] == ["", "", ""]
    text = file(body, types=types)
    f = rinex.read2(text)
    assert rinex.write2(f) == text
    g1, g2, g3, g4, g5 = f.epochs[0].satellites
    assert [number(o.value, 3) for o in g1.obs] == [i * 1000 for i in range(1, 13)]
    assert g1.obs[11] == Observation("        12.000", "2", "7")
    assert len(g2.obs) == 2
    assert g3.obs == (*[Observation("", "", "")] * 5, Observation("         6.000", "", ""))
    assert len(g4.obs) == 11 and g4.obs[0] == Observation("         1.000", "", "")
    assert g4.obs[1:10] == (Observation("", "", ""),) * 9
    assert g5.obs == ()
    # A satellite's lines are all there, even when empty.
    with pytest.raises(Invalid, match="OBSERVATIONS records announced"):
        rinex.read2(file(body[:-1], types=types))


def test_more_observations_than_types_are_refused():
    body = [*epoch((*T, 10, 36.0), 0, ["G01"]), *obs(3, "1.000", "2.000", "3.000")]
    with pytest.raises(Invalid, match="3 observations, 2 types"):
        rinex.read2(file(body))
    seven = ["C1", "L1", "D1", "S1", "P1", "C2", "L2"]
    body = [*epoch((*T, 10, 36.0), 0, ["G01"]), "", obs(3, "1.000", "2.000", "3.000")[0]]
    with pytest.raises(Invalid, match="8 observations, 7 types"):
        rinex.read2(file(body, types=seven))


def test_a_file_without_observation_types():
    # No # / TYPES OF OBSERV record: events are read, observations are not.
    text = file([*epoch(None, 4, count=1), h("NOTHING YET", "COMMENT")], types=None)
    assert rinex.write2(rinex.read2(text)) == text
    with pytest.raises(Invalid, match="no # / TYPES OF OBSERV record"):
        rinex.read2(file([*epoch((*T, 10, 36.0), 0, ["G01"]), *obs(1, "1.000")], types=None))
    # The record may come in a header event.
    text = file([*epoch(None, 4, count=1), *types_lines(["C1"]),
                 *epoch((*T, 10, 36.0), 0, ["G01"]), *obs(1, "1.000")], types=None)
    assert rinex.write2(rinex.read2(text)) == text


@pytest.mark.parametrize("flag", [2, 3, 4, 5])
def test_header_records_of_an_event_redefine_obs_types(flag):
    # Section 5.3: "each value remains valid until changed by an additional
    # header record"; section 0.4: header records are allowed after every
    # event flag above 1.
    six = ["C1", "L1", "D1", "S1", "P2", "L2"]
    body = [*epoch((*T, 10, 36.0), 0, ["G01"]), *obs(2, "1.000", "2.000"),
            *epoch((*T, 10, 37.0), flag, count=1), *types_lines(six),
            *epoch((*T, 10, 38.0), 0, ["G01"]), *obs(6, *["1.000"] * 6)]
    text = file(body)
    f = rinex.read2(text)
    assert rinex.write2(f) == text
    assert [len(e.satellites[0].obs) for e in (f.epochs[0], f.epochs[2])] == [2, 6]
    assert rinex.obs_types2(f.epochs[1].special, rinex.obs_types2(f.header)) == tuple(six)
    # Without the event, the second line of six observations is not there to read.
    with pytest.raises(Invalid):
        rinex.read2(file(body[:2] + body[4:]))


def test_cycle_slip_records():
    # Flag 6: "same format as OBSERVATIONS records; slip instead of observation".
    body = [*epoch((*T, 10, 36.0), 6, ["G06", "R21"]), *obs(2, None, "1.000"),
            *obs(2, "-2.000")]
    f = rinex.read2(file(body))
    assert f.epochs[0].satellites == (
        SatelliteRecord("G06", (Observation(" " * 14, " ", " "),
                                Observation("         1.000", "", ""))),
        SatelliteRecord("R21", (Observation("        -2.000", "", ""),)))
    assert f.epochs[0].special == ()


def test_receiver_clock_offset_and_short_lines():
    # Section 6.3: "empty data fields at the end of a record may be missing,
    # especially in the case of the optional receiver clock offset".
    sats = [f"G{i:02d}" for i in range(1, 13)]
    one = obs(2, "1.000")
    for line, clock, listed in [
            (epoch((*T, 10, 36.0), 0, sats)[0], "", "".join(sats)),               # 68 columns
            (epoch((*T, 10, 36.0), 0, sats, "0.000535140")[0], " 0.000535140", "".join(sats)),
            (epoch((*T, 10, 36.0), 0, sats, "-.5")[0].rstrip(), "         -.5", "".join(sats)),
            (epoch((*T, 10, 36.0), 0, sats[:1])[0], "", "G01"),
            (epoch((*T, 10, 36.0), 0, sats[:1])[0].ljust(80), " " * 12, "G01".ljust(36)),
            (epoch((*T, 10, 36.0), 0, sats[:1])[0] + "  ", "", "G01  "),
            (epoch((*T, 10, 36.0), 0, sats[:1], "1.000000000")[0], " 1.000000000",
             "G01".ljust(36)),
    ]:
        n = number(line[29:32])
        text = file([line, *one * n])
        f = rinex.read2(text)
        assert rinex.write2(f) == text
        assert (f.epochs[0].record.clock, f.epochs[0].record.sats) == (clock, listed)
        assert len(f.epochs[0].satellites) == n
    # An epoch without satellites, and a line that stops after the flag.
    text = file([*epoch((*T, 10, 36.0), 0), " 05  3 24 13 10 37.0000000  0"])
    assert [e.record.count for e in rinex.read2(text).epochs] == ["  0", ""]
    assert rinex.write2(rinex.read2(text)) == text


def test_24_and_25_satellites():
    sats = [f"G{i:02d}" for i in range(1, 26)]
    for n, lines in ((12, 1), (13, 2), (24, 2), (25, 3)):
        head = epoch((*T, 10, 36.0), 0, sats[:n], "0.000000001")
        assert len(head) == lines and len(head[0]) == 80
        text = file([*head, *obs(2, "1.000") * n])
        f = rinex.read2(text)
        assert rinex.write2(f) == text
        assert [s.sat for s in f.epochs[0].satellites] == sats[:n]
        assert len(f.epochs[0].continuation) == lines - 1


def test_line_endings_are_kept():
    for newline in ("\n", "\r\n"):
        text = newline.join(A7_HEADER + A7_BODY) + newline
        f = rinex.read2(text)
        assert f.newline == newline and f.final_newline
        assert rinex.write2(f) == text
        assert rinex.write2(rinex.read2(text[:-len(newline)])) == text[:-len(newline)]
    with pytest.raises(Invalid, match="both LF and CR LF"):
        rinex.read2(A7.replace("\n", "\r\n", 1))


# ---- what is refused ------------------------------------------------------------------

@pytest.mark.parametrize("version", ["2.11", "2.10", "2.00", "2", "2.20"])
def test_versions_2(version):
    assert rinex.read2(file(version=version)).version == version


@pytest.mark.parametrize("version", ["3.05", "4.02", "1.00", "", "x"])
def test_other_versions_are_unsupported(version):
    with pytest.raises(Unsupported, match="RINEX version"):
        rinex.read2(file(version=version))


def test_other_file_types_are_unsupported():
    for kind, name in (("N", "NAVIGATION DATA"), ("M", "METEOROLOGICAL DATA"),
                       ("G", "GLONASS NAV DATA")):
        first = h(f"     2.11           {name}", "RINEX VERSION / TYPE")
        with pytest.raises(Unsupported, match=f"file type '{kind}'"):
            rinex.read2(first + "\n" + h("", "END OF HEADER") + "\n")


def test_read_and_read2_each_refuse_the_others_files():
    # read is for RINEX 3 and 4, read2 for RINEX 2; neither guesses.
    with pytest.raises(Unsupported):
        rinex.read(A7)
    three = (h("     3.05           OBSERVATION DATA    M", "RINEX VERSION / TYPE") + "\n"
             + h("", "END OF HEADER") + "\n")
    assert rinex.read(three).version == "3.05"
    with pytest.raises(Unsupported):
        rinex.read2(three)
    with pytest.raises(Unsupported):
        rinex.write2(rinex.read(three))


@pytest.mark.parametrize("text, damage, match", [
    (A7, lambda t: t.replace("RINEX VERSION / TYPE", "COMMENT"), "first record"),
    (A7, lambda t: t.split(h("", "END OF HEADER"))[0], "no END OF HEADER"),
    (A7, lambda t: t.replace(h("234                 YY", "ANT # / TYPE"), "234"), "label"),
    (A7, lambda t: t.replace("MARKER NUMBER", "MARKER NUMBER" + "x" * 8), "past column"),
    (A7, lambda t: t.replace("  0  4G12G09G06E11", "  9  4G12G09G06E11"), "epoch flag"),
    (A7, lambda t: t.replace("  0  4G12G09G06E11", "     4G12G09G06E11"), "epoch flag"),
    (A7, lambda t: t.replace("  0  4G12G09G06E11", "  0 x4G12G09G06E11"), "not I3"),
    (A7, lambda t: t.replace("G12G09G06E11", "G12X09G06E11"), "'X09' is not a satellite"),
    (A7, lambda t: t.replace("G12G09G06E11", "G12C09G06E11"), "'C09' is not a satellite"),
    (A7, lambda t: t.replace("G12G09G06E11", "G12G9 G06E11"), "'G9 ' is not a satellite"),
    (A7, lambda t: t.replace("  0  4G12G09G06E11", "  0  5G12G09G06E11"), "'   ' is not a"),
    (A7, lambda t: t.replace("  6  2G16G09", "  6  3G16G09"), "3 satellites to list, 6 columns"),
    (A7, lambda t: t.replace("  6  2G16G09", "  6  1G16G09"), "'G09' after the 1 satellites"),
    (A7, lambda t: t.replace(CLOCK + "\n", CLOCK + "9\n", 1), "past column 80"),
    (A7, lambda t: t.replace("23629364.158\n", "23629364.158".ljust(40) + "\n"),
     "OBSERVATIONS record of 90 columns"),
    (A7, lambda t: t.replace(" 0.0000000  2  1", " 0.0000000  2  1G01"), "no list of satellites"),
    (A7, lambda t: t.replace("  4  3\n", "  4  4\n"), "4 special records announced, 3 lines"),
    (A7, lambda t: t.replace("  4  3\n", "  4  2\n"), "epoch flag"),
    (A7, lambda t: t.replace("  6  2G16G09", "  6  2G16\rG09"), "CR inside"),
    (A7, lambda t: "\n".join(line for line in t.split("\n") if "TYPES OF OBSERV" not in line),
     "no # / TYPES OF OBSERV record"),
    (A7, lambda t: t + "\n", "epoch flag"),
    (A7, lambda t: "", "empty"),
    (A14, lambda t: t.replace(" " * 32 + "R10R03\n", ""), "2 satellites to list, 0 columns"),
    (A14, lambda t: t.replace(" " * 32 + "R10R03\n", " " * 32 + "R10\n"), "2 satellites to list"),
    (A14, lambda t: t.replace(" " * 32 + "R10R03\n", " " * 32 + "R10R03R04\n"), "'R04' after"),
    (A14, lambda t: t.replace(" " * 32 + "R10R03\n", " " * 32 + "R10R03".ljust(36) + " 0.1\n"),
     "past column 68"),
    (A14, lambda t: t.rsplit("\n", 2)[0] + "\n", "OBSERVATIONS records announced"),
    (A14, lambda t: t.split("G23G07")[0] + "G23G07G02G05G26G09G21R20R19R12R02R11\n",
     "continuation lines announced"),
])
def test_refusals(text, damage, match):
    damaged = damage(text)
    assert damaged != text
    with pytest.raises(Invalid, match=match):
        rinex.read2(damaged)


def test_write_checks_what_read_would_refuse():
    f = rinex.read2(A7)
    first = f.epochs[0]
    sats = first.satellites
    blank = EpochRecord2("   ", "   ", "   ", "   ", "   ", " " * 11, "  2", "  1", "", "")

    def with_first(**changes):
        e = Epoch2(**{"record": first.record, "satellites": sats, "special": first.special,
                      "continuation": first.continuation, **changes})
        return ObsFile2(f.header, (e, *f.epochs[1:]), f.newline, f.final_newline)

    def named(**changes):
        fields = {n: getattr(first.record, n) for n, _ in rinex.columns(EpochRecord2)}
        return with_first(record=EpochRecord2(**{**fields, **changes}))

    assert rinex.write2(with_first()) == A7
    bad = [
        with_first(satellites=sats[:-1]),                                   # count is 4
        with_first(satellites=(*sats, sats[0])),
        with_first(satellites=(sats[1], sats[0], *sats[2:])),               # not the list's order
        with_first(satellites=(SatelliteRecord("G 12", sats[0].obs), *sats[1:])),
        with_first(satellites=list(sats)),
        with_first(special=(f.header[1],)),                                 # flag 0
        with_first(continuation=(SatelliteList(" " * 32, ""),)),            # 4 satellites
        with_first(continuation=("",)),
        with_first(satellites=(SatelliteRecord("G12", (Observation("1", "", ""),
                                                       Observation("2", "", ""))), *sats[1:])),
        with_first(satellites=(SatelliteRecord("G12", (Observation("", "", ""),)), *sats[1:])),
        with_first(satellites=(SatelliteRecord("G12", sats[0].obs * 2), *sats[1:])),  # 8 of 5
        with_first(satellites=(SatelliteRecord("G12", ("  23629347.915",)), *sats[1:])),
        with_first(satellites=("G12", *sats[1:])),
        named(count="  5"),
        named(flag="  7"),
        named(flag="  2"),                                                  # a list under flag 2
        named(sats="G12G09G06E11"),                                         # short before clock
        named(sats="G12G09G06C11".ljust(36)),
        named(clock="-.1234567890123"),
        named(year=5),
        with_first(record=blank, satellites=()),                            # one record announced
        with_first(record=blank, satellites=(), special=("COMMENT",)),
        with_first(record=first),
        ObsFile2(f.header[:-1], f.epochs),
        ObsFile2((f.header[0], f.header[-1], *f.header[1:]), f.epochs),
        ObsFile2((f.header[0], HeaderRecord("x" * 59, "COMMENT"), *f.header[1:]), ()),
        ObsFile2((HeaderRecord("     3.05           O".ljust(60), "RINEX VERSION / TYPE"),
                  f.header[-1]), ()),
        ObsFile2(f.header, f.epochs, newline="\r"),
        ObsFile2(f.header, (*f.epochs, "epoch")),
    ]
    for b in bad:
        with pytest.raises(rinex.Error):
            rinex.write2(b)
    # Without the header's types, the observations cannot be written.
    header = tuple(r for r in f.header if r.label != rinex.OBS_TYPES2)
    with pytest.raises(Invalid, match="no # / TYPES OF OBSERV"):
        rinex.write2(ObsFile2(header, f.epochs))


def test_records_are_built_by_hand():
    # A file made from records, not from text: the list in the EPOCH/SAT
    # record names the satellites, and each SatelliteRecord repeats its name.
    header = (HeaderRecord("     2.11           OBSERVATION DATA    G".ljust(60),
                           "RINEX VERSION / TYPE"),
              HeaderRecord("     1    C1".ljust(60), "# / TYPES OF OBSERV"),
              HeaderRecord(" " * 60, "END OF HEADER"))
    record = EpochRecord2(" 26", "  1", "  2", "  3", "  4", "  5.0000000", "  0", "  2", "G01G02",
                          "")
    e = Epoch2(record, (SatelliteRecord("G01", (Observation("  20000000.000", "", ""),)),
                        SatelliteRecord("G02", ())))
    text = rinex.write2(ObsFile2(header, (e,)))
    assert text.split("\n")[3:] == [" 26  1  2  3  4  5.0000000  0  2G01G02", "  20000000.000", "",
                                    ""]
    assert rinex.read2(text) == ObsFile2(header, (e,))
    assert list(rinex.records2(ObsFile2(header, (e,)))) == text.split("\n")[:-1]


# ---- generated files --------------------------------------------------------------

digits = st.sampled_from("0123456789")
sat_numbers = st.builds(lambda s, n, pad: s + (f"{n:02d}" if pad else f"{n:2d}"),
                        st.sampled_from(" GRSE"), st.integers(1, 99), st.booleans())


@st.composite
def cells(draw):
    value = draw(st.one_of(st.just(" " * 14), st.floats(-9e8, 9e8).map(lambda v: f"{v:14.3f}")))
    return value + draw(st.one_of(st.just(" "), digits)) + draw(st.one_of(st.just(" "), digits))


@st.composite
def trimmed(draw, line, width=80):
    """``line`` with its trailing blanks truncated, kept, or padded to ``width``."""
    how = draw(st.sampled_from(["strip", "keep", "pad"]))
    return line.rstrip() if how == "strip" else line.ljust(width) if how == "pad" else line


@st.composite
def texts(draw):
    types = draw(st.lists(st.from_regex(r"[CPLDS][125678]", fullmatch=True), max_size=12))
    version = draw(st.sampled_from(["2.11", "2.10", "2.00"]))
    lines = [h(f"{version:>9}{'':11}OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
             *types_lines(types),
             h(draw(st.text(st.characters(min_codepoint=32, max_codepoint=126), max_size=60)),
               "COMMENT"), h("", "END OF HEADER")]
    per = -(-len(types) // 5)
    for _ in range(draw(st.integers(0, 4))):
        flag = draw(st.sampled_from([0, 0, 1, 6, 2, 3, 4, 5]))
        time = draw(st.one_of(st.none() if flag > 1 else st.nothing(), st.tuples(
            st.integers(0, 99), st.integers(1, 12), st.integers(1, 28), st.integers(0, 23),
            st.integers(0, 59), st.floats(0, 59.9999999))))
        if flag in (2, 3, 4, 5):
            n = draw(st.integers(0, 3))
            lines += epoch(time, flag, count=n)
            lines += [h(draw(st.text("ABC xyz", max_size=60)), "COMMENT") for _ in range(n)]
            continue
        sats = draw(st.lists(sat_numbers, max_size=30))
        clock = draw(st.one_of(st.none(), st.floats(-9, 9).map(lambda v: f"{v:12.9f}")))
        head = epoch(time, flag, sats, clock)
        lines += [draw(trimmed(line, 80 if i == 0 else 68)) for i, line in enumerate(head)]
        for _ in sats:
            left = len(types)
            for _ in range(per):
                row = draw(st.lists(cells(), max_size=min(5, left)))
                left -= 5
                line = "".join(row)
                lines.append(line.rstrip() if draw(st.booleans()) else line)
    newline = draw(st.sampled_from(["\n", "\r\n"]))
    # A file whose last line is empty needs its line ending to be told from
    # the same file without that line.
    return newline.join(lines) + (newline if lines[-1] == "" or draw(st.booleans()) else "")


@settings(max_examples=200, derandomize=True, deadline=None)
@given(texts())
def test_generated_files_round_trip(text):
    f = rinex.read2(text)
    assert rinex.write2(f) == text
    assert rinex.read2(rinex.write2(f)) == f
    for e in f.epochs:
        assert len(e.satellites) == (number(e.record.count) or 0) * (not e.special)
        assert all(len(s.sat) == 3 and sat_name(s.sat)[0] in rinex.SYSTEMS2 for s in e.satellites)
