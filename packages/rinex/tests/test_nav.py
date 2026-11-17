"""RINEX navigation message files against RINEX 3.05, 4.02 and 2.11.

- The record columns and the shape of every message table (how many
  values each line names, and which are spares) are transcribed a second
  time here.
- Files are built line by line from the tables' Fortran formats, with the
  values the documents' examples print (3.05 Tables A7, A11, A15 and A19;
  4.02 Tables A18, A27, A32 and A41; 2.11 Tables A8, A12 and A18). The
  examples are not quoted as text: their columns cannot be taken reliably
  from the documents (proportional rendering moves them).
- Generated files round-trip: ``write_nav(read_nav(text)) == text``.

No independent reader is run against these files: none is among the
development dependencies.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import rinex
from gnsswire.rinex import (
    HeaderRecord,
    Invalid,
    NavEpoch,
    NavEpoch2,
    NavFile,
    NavLine,
    NavLine2,
    NavRecord,
    NavType,
    Unsupported,
    nav_fields,
    nav_type,
    read_nav,
    real,
    write_nav,
)
from gnsswire.rinex import _nav

# ---- the tables, a second time ---------------------------------------------------

VALUES3 = [("v1", 19, "D19.12"), ("v2", 19, "D19.12"), ("v3", 19, "D19.12")]


def test_record_columns_are_the_documents():
    cols = lambda cls: [(n, c.width, c.fmt) for n, c in rinex.columns(cls)]   # noqa: E731
    # 3.05 Table A6: A1,I2.2,1X,I4,5(1X,I2.2),3D19.12; 4X,4D19.12.
    assert cols(NavEpoch) == [("sat", 3, "A1,I2.2"), ("year", 5, "1X,I4"),
                              *[(n, 3, "1X,I2.2") for n in ("month", "day", "hour", "minute",
                                                           "second")], *VALUES3]
    assert cols(NavLine) == [("indent", 4, "4X"), *VALUES3, ("v4", 19, "D19.12")]
    # 2.11 Table A4: I2,1X,I2.2,4(1X,I2),F5.1,3D19.12; 3X,4D19.12.
    assert cols(NavEpoch2) == [("sat", 2, "I2"), ("year", 3, "1X,I2.2"),
                               *[(n, 3, "1X,I2") for n in ("month", "day", "hour", "minute")],
                               ("second", 5, "F5.1"), *VALUES3]
    assert cols(NavLine2) == [("indent", 3, "3X"), *VALUES3, ("v4", 19, "D19.12")]
    # 4.02 Table A9, TYPE / SV / MSSG: A1 (">"), then 1X,A3,1X,A3,1X,A4,1X,A4.
    assert cols(NavType) == [("kind", 4, "1X,A3"), ("source", 4, "1X,A3"),
                             ("message", 5, "1X,A4"), ("subtype", 5, "1X,A4")]
    width = lambda cls: sum(c.width for _, c in rinex.columns(cls))           # noqa: E731
    assert [width(c) for c in (NavEpoch, NavLine, NavEpoch2, NavLine2)] == [80, 80, 79, 79]


# Each table as the values its lines hold, first line first: "x" a named
# value, "-" a spare. A line the table ends early is shorter than four.
SHAPES2 = {
    "N": "xxx xxxx xxxx xxxx xxxx xxxx xxxx xx--",      # 2.11 Table A4
    "G": "xxx xxxx xxxx xxxx",                          # Table A11
    "H": "xxx xxxx xxxx xxxx",                          # Table A16
}
SHAPES3 = {
    "G": "xxx xxxx xxxx xxxx xxxx xxxx xxxx xx--",      # 3.05 Table A6
    "E": "xxx xxxx xxxx xxxx xxxx xxx- xxxx x---",      # Table A8
    "R": "xxx xxxx xxxx xxxx xxxx",                     # Table A10
    "J": "xxx xxxx xxxx xxxx xxxx xxxx xxxx xx--",      # Table A12
    "C": "xxx xxxx xxxx xxxx xxxx x-x- xxxx xx--",      # Table A14
    "S": "xxx xxxx xxxx xxxx",                          # Table A16
    "I": "xxx xxxx xxxx xxxx xxxx x-x- xxx- x---",      # Table A18
}
SHAPES4 = {
    ("EPH", "G", "LNAV", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xx",              # A9
    ("EPH", "G", "CNAV", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxx",        # A10
    ("EPH", "G", "CNV2", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx xx xxx",     # A11
    ("EPH", "E", "INAV", ""): "xxx xxxx xxxx xxxx xxxx xxx xxxx x",                # A13
    ("EPH", "E", "FNAV", ""): "xxx xxxx xxxx xxxx xxxx xxx xxxx x",                # A13
    ("EPH", "R", "FDMA", ""): "xxx xxxx xxxx xxxx xxxx",                           # A15
    ("EPH", "R", "L1OC", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx xx-x",       # A16
    ("EPH", "R", "L3OC", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx xx-x",       # A17
    ("EPH", "J", "LNAV", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xx",              # A19
    ("EPH", "J", "CNAV", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxx",        # A20
    ("EPH", "J", "CNV2", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx xx xxx",     # A21
    ("EPH", "C", "D1", ""): "xxx xxxx xxxx xxxx xxxx x-x- xxxx xx",                # A23
    ("EPH", "C", "D2", ""): "xxx xxxx xxxx xxxx xxxx x-x- xxxx xx",                # A23
    ("EPH", "C", "CNV1", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx x-xx xxxx x--x",  # A24
    ("EPH", "C", "CNV2", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx -xxx xxxx x--x",  # A25
    ("EPH", "C", "CNV3", ""): "xxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx x",          # A26
    ("EPH", "S", "SBAS", ""): "xxx xxxx xxxx xxxx",                                # A28
    ("EPH", "I", "LNAV", ""): "xxx xxxx xxxx xxxx xxxx x-x- xxx- x",               # A30
    ("EPH", "I", "L1NV", ""): "xxx xxxx xxxx xxxx xxxx xx-x xxxx xxxx x",          # A31
    ("STO", "G", "LNAV", ""): "xxx xxxx",                                          # A33
    ("EOP", "G", "CNVX", ""): "xxx -xxx xxxx",                                     # A34
    ("ION", "G", "LNAV", ""): "xxx xxxx x",                                        # A35
    ("ION", "G", "CNVX", ""): "xxx xxxx x",
    ("ION", "C", "D1D2", ""): "xxx xxxx x",
    ("ION", "J", "LNAV", ""): "xxx xxxx x",
    ("ION", "J", "CNVX", "WIDE"): "xxx xxxx x",
    ("ION", "J", "CNVX", "JAPN"): "xxx xxxx x",
    ("ION", "I", "LNAV", ""): "xxx xxxx x",
    ("ION", "E", "IFNV", ""): "xxx x",                                             # A36
    ("ION", "C", "CNVX", ""): "xxx xxxx xx",                                       # A37
    ("ION", "I", "L1NV", "KLOB"): "x xxxx xxxx xxxx",                              # A38
    ("ION", "I", "L1NV", "NEQN"): "x xxxx xxxx xxxx xxxx xxxx xxxx",               # A39
    ("ION", "R", "LXOC", ""): "xxx",                                               # A40
}


def shape(layout) -> str:
    return " ".join("".join("-" if n is None else "x" for n in group)
                    for group in (layout.first, *layout.lines))


def source(key) -> str:
    kind, system, message, subtype = key
    return (" " + system).ljust(4) if kind != "EPH" else f" {system}07"


def layout4(key):
    kind, system, message, subtype = key
    record = NavRecord(NavType(" " + kind, source(key), " " + message,
                               " " + subtype if subtype else ""),
                       NavEpoch(*[""] * 10), ())
    return _nav._layout("4", "N", record)


def test_message_tables_are_the_documents():
    assert {k: shape(v) for k, v in _nav.NAV2.items()} == SHAPES2
    assert {k: shape(v) for k, v in _nav.NAV3.items()} == SHAPES3
    assert {k: shape(layout4(k)) for k in SHAPES4} == SHAPES4
    assert {("EPH", s, m, "") for s, m in _nav.NAV4_EPH} == {k for k in SHAPES4 if k[0] == "EPH"}
    assert len(_nav.NAV4_ION) == 11
    for layout in (*_nav.NAV2.values(), *_nav.NAV3.values(), *_nav.NAV4_EPH.values(),
                   *_nav.NAV4_ION.values(), _nav.NAV4_STO, _nav.NAV4_EOP):
        assert len(set(layout.names)) == len(layout.names), layout.source
        assert len(layout.first) <= 3 and all(len(ln) <= 4 for ln in layout.lines)


def test_names_follow_the_tables():
    # Spot checks of the order, against the tables' descriptions.
    assert _nav.NAV3["G"].names == (
        "clock_bias", "clock_drift", "clock_drift_rate", "iode", "crs", "delta_n", "m0",
        "cuc", "e", "cus", "sqrt_a", "toe", "cic", "omega0", "cis", "i0", "crc", "omega",
        "omega_dot", "idot", "l2_codes", "week", "l2p_flag", "accuracy", "health", "tgd",
        "iodc", "t_tm", "fit_interval")
    assert _nav.NAV3["R"].names == (
        "clock_bias", "freq_bias", "frame_time", "x", "x_dot", "x_acc", "health", "y",
        "y_dot", "y_acc", "freq_num", "z", "z_dot", "z_acc", "age", "status_flags",
        "group_delay", "urai", "health_flags")
    assert _nav.NAV4_EPH["G", "CNAV"].lines[4:] == (
        ("idot", "delta_n0_dot", "urai_ned0", "urai_ned1"),
        ("urai_ed", "health", "tgd", "urai_ned2"),
        ("isc_l1ca", "isc_l2c", "isc_l5i5", "isc_l5q5"), ("t_tm", "wn_op", "flags"))
    assert _nav.NAV4_EPH["C", "CNV1"].lines[6] == ("isc_b1cd", None, "tgd_b1cp", "tgd_b2ap")
    assert _nav.NAV4_EPH["C", "CNV2"].lines[6] == (None, "isc_b2ad", "tgd_b1cp", "tgd_b2ap")
    assert _nav.NAV4_EPH["I", "L1NV"].lines[2][0] == "iodec"
    assert _nav.NAV4_STO.text == {"offset", "sbas_id", "utc_id"}


# ---- building files from the formats ------------------------------------------------

def h(content: str, label: str) -> str:
    assert len(content) <= 60
    return content.ljust(60) + label


def d(value, style="e") -> str:
    """A D19.12 field. Styles, as the documents' examples print numbers:

    ``e``/``E`` `` 1.330170780420e-04``; ``D`` `` -.839701388031D-03`` (3.05
    Table A7); ``0E``/``0D`` `` 0.798045657575E-04`` (Table A11); ``d`` as
    ``D`` with a small letter. ``None`` is a blank field, a string is
    itself, left-justified (``1X,A18``).
    """
    if value is None:
        return " " * 19
    if isinstance(value, str):
        return value.ljust(19)
    if style in ("e", "E"):
        text = f"{value:19.12e}"
        return text.upper() if style == "E" else text
    mantissa, exponent = f"{abs(value):.11e}".split("e")
    exponent = int(exponent) + 1 if value else 0
    text = ("-" if value < 0 else "") + ("0." if style[0] == "0" else ".") + mantissa.replace(
        ".", "") + f"{style[-1]}{exponent:+03d}"
    return text.rjust(19)


def first(sat, date, values, style="e") -> str:
    """SV / EPOCH / SV CLK: A1,I2.2,1X,I4,5(1X,I2.2),3D19.12, trailing blanks cut."""
    y, *rest = date
    return (f"{sat:3}{y:5d}" + "".join(f" {v:02d}" for v in rest)
            + "".join(d(v, style) for v in values)).rstrip()


def orbit(values, style="e", indent=4) -> str:
    """BROADCAST ORBIT: 4X,4D19.12 (3X in RINEX 2), trailing blanks cut."""
    return (" " * indent + "".join(d(v, style) for v in values)).rstrip()


def first2(sat, date, values, style="D") -> str:
    """PRN / EPOCH / SV CLK of RINEX 2: I2,1X,I2.2,4(1X,I2),F5.1,3D19.12."""
    y, mo, dd, hh, mi, s = date
    return (f"{sat:2d} {y % 100:02d} {mo:2d} {dd:2d} {hh:2d} {mi:2d}{s:5.1f}"
            + "".join(d(v, style) for v in values))


def header(version: str, kind="NAVIGATION DATA", system="M", extra=()) -> list[str]:
    return [h(f"{version:>9}{'':11}{kind:20}{system}", "RINEX VERSION / TYPE"),
            h("XXRINEXN V3         AIUB                19990903 152236 UTC", "PGM / RUN BY / DATE"),
            *extra, h("", "END OF HEADER")]


def file(version, body, newline="\n", **kw) -> str:
    return newline.join([*header(version, **kw), *body]) + newline


def chunks(values, n=4):
    return [values[i:i + n] for i in range(0, len(values), n)]


# 3.05 Table A7 (GPS), the first record, and Table A8 of 2.11 (the same message).
A7 = [-.839701388031e-03, -.165982783074e-10, 0.0,
      91.0, 93.40625, .116040547840e-08, .162092304801e+00,
      .484101474285e-05, .626740418375e-02, .652112066746e-05, .515365489006e+04,
      .409904e+06, -.242143869400e-07, .329237003460e+00, -.596046447754e-07,
      .111541663136e+01, .326593750000e+03, .206958726335e+01, -.638312302555e-08,
      .307155651409e-09, 0.0, 1025.0, 0.0,
      0.0, 0.0, 0.0, 91.0,
      .4068e+06, 4.0]
# Table A11 (mixed GPS/GLONASS), R01: four BROADCAST ORBIT lines in 3.05.
A11_R01 = [-0.137668102980e-04, -0.454747350886e-11, 90.0,
           0.157594921875e+05, -0.145566368103e+01, 0.0, 0.0,
           -0.813711474609e+04, 0.205006790161e+01, 0.931322574615e-09, 7.0,
           0.183413398438e+05, 0.215388488770e+01, -0.186264514923e-08, 1.0,
           179.0, 8.381903171539e-09, 2.0, 3.0]
# Table A15 (BDS), C01: BROADCAST ORBIT - 5 has blank spares.
A15 = [2.969256602228e-04, 2.196998138970e-11, 0.0,
       1.0, 4.365468750000e+02, 1.318269196918e-09, -3.118148933476e+00,
       1.447647809982e-05, 2.822051756084e-04, 8.092261850834e-06, 6.493480609894e+03,
       5.184e+05, -2.654269337654e-08, 3.076630958509e+00, -3.864988684654e-08,
       1.103024081152e-01, -2.506406250000e+02, 2.587808789012e+00, -3.039412318009e-10,
       2.389385241772e-10, None, 435.0, None,
       2.0, 0.0, 1.42e-08, -1.04e-08,
       5.184e+05, 0.0]
# Table A19 (NavIC/IRNSS), I01: the last lines end before their spares.
A19 = [-9.473115205765e-04, 1.250555214938e-12, 0.0,
       0.0, -5.820625e+02, 4.720196615135e-09, -1.396094758025e+00,
       -1.898035407066e-05, 2.257102518342e-03, -1.068413257599e-05, 6.493487739563e+03,
       1.728e+05, 6.705522537231e-08, -8.912102146884e-01, -5.215406417847e-08,
       4.758105460020e-01, 4.009375e+02, -2.999907424014e+00, -4.414469594664e-09,
       -4.839487298357e-10, None, 1786.0, None,
       11.3, 0.0, -4.190951585770e-09, None,
       1.728e+05]


def record3(sat, date, values, style="e") -> list[str]:
    return [first(sat, date, values[:3], style), *(orbit(c, style) for c in chunks(values[3:]))]


MIXED3 = file("3.05", [
    *record3("G06", (1999, 9, 2, 17, 51, 44), A7, "D"),
    *record3("R01", (2006, 10, 1, 0, 15, 0), A11_R01, "0E"),
    *record3("C01", (2014, 5, 10, 0, 0, 0), A15),
    *record3("I01", (2014, 4, 1, 0, 0, 0), A19),
], extra=[h("GPSA   0.1025E-07  0.7451E-08 -0.5960E-07 -0.5960E-07", "IONOSPHERIC CORR"),
          h("    13", "LEAP SECONDS")])


def test_rinex_3_examples_read_and_write_back():
    nav = read_nav(MIXED3)
    assert write_nav(nav) == MIXED3
    assert nav.version == "3.05" and nav.file_type == "N"
    assert [r.label.rstrip() for r in nav.header] == [
        "RINEX VERSION / TYPE", "PGM / RUN BY / DATE", "IONOSPHERIC CORR", "LEAP SECONDS",
        "END OF HEADER"]
    g06, r01, c01, i01 = nav.records
    assert [len(r.lines) for r in nav.records] == [7, 4, 7, 7]
    assert all(r.type is None for r in nav.records)
    assert nav_type(nav, g06) == ("EPH", "G", "", "") and nav_type(nav, r01)[1] == "R"

    # 3.05 Table A7 as printed: "G06 1999 09 02 17 51 44 -.839701388031D-03 ...".
    assert g06.epoch == NavEpoch("G06", " 1999", " 09", " 02", " 17", " 51", " 44",
                                 " -.839701388031D-03", " -.165982783074D-10",
                                 "  .000000000000D+00")
    assert g06.lines[0] == NavLine("    ", "  .910000000000D+02", "  .934062500000D+02",
                                   "  .116040547840D-08", "  .162092304801D+00")
    assert g06.lines[6] == NavLine("    ", "  .406800000000D+06", "  .400000000000D+01", "", "")
    assert len(g06.values) == 3 + 4 * 7 and g06.values[3] == "  .910000000000D+02"
    f = nav_fields(nav, g06)
    assert list(f) == list(_nav.NAV3["G"].names)
    assert f["iode"] == "  .910000000000D+02" and f["iodc"] == "  .910000000000D+02"
    assert real(f["week"]) == (102500000000, -8) and real(f["sqrt_a"]) == (515365489006, -8)
    assert f["t_tm"].strip() == ".406800000000D+06" and f["fit_interval"].strip() \
        == ".400000000000D+01"

    f = nav_fields(nav, r01)
    assert f["clock_bias"] == "-0.137668102980E-04" and f["frame_time"] == " 0.900000000000E+02"
    assert f["freq_num"] == " 0.700000000000E+01" and f["status_flags"] == " 0.179000000000E+03"
    assert f["health_flags"] == " 0.300000000000E+01"

    # Blank spares inside a line, absent ones at its end.
    assert c01.lines[4] == NavLine("    ", " 2.389385241772e-10", " " * 19,
                                   " 4.350000000000e+02", "")
    f = nav_fields(nav, c01)
    assert f["week"] == " 4.350000000000e+02" and f["tgd2"] == "-1.040000000000e-08"
    assert "spare" not in " ".join(f) and f["aodc"] == " 0.000000000000e+00"
    assert i01.lines[5].v4 == "" and i01.lines[6] == NavLine("    ", " 1.728000000000e+05",
                                                            "", "", "")
    f = nav_fields(nav, i01)
    assert f["tgd"] == "-4.190951585770e-09" and f["t_tm"] == " 1.728000000000e+05"


def numbers(shape_text: str, start=1.0):
    """Values for a table's shape: a number for each name, a blank for each spare."""
    out, value = [], start
    for c in shape_text.replace(" ", ""):
        out.append(None if c == "-" else value)
        value = -value * 1.37
    return out


def groups(shape_text: str, values):
    out, at = [], 0
    for g in shape_text.split(" "):
        out.append(values[at:at + len(g)])
        at += len(g)
    return out


@pytest.mark.parametrize("system", sorted(SHAPES3))
@pytest.mark.parametrize("style", ["e", "E", "D", "d", "0D", "0E"])
def test_rinex_3_every_system_round_trips(system, style):
    values = groups(SHAPES3[system], numbers(SHAPES3[system]))
    body = [first(f"{system}07", (2024, 2, 3, 4, 5, 6), values[0], style),
            *(orbit(v, style) for v in values[1:])]
    text = file("3.05", body, system=system)
    nav = read_nav(text)
    assert write_nav(nav) == text
    f = nav_fields(nav, nav.records[0])
    assert list(f) == list(_nav.NAV3[system].names)
    named = [v for v in numbers(SHAPES3[system]) if v is not None]
    assert [real(v) for v in f.values()] == [real(d(v, style)) for v in named]
    # The same with every line padded to 80 columns.
    padded = file("3.05", [line.ljust(80) for line in body], system=system)
    assert write_nav(read_nav(padded)) == padded
    assert {k: v.strip() for k, v in nav_fields(read_nav(padded), read_nav(padded).records[0])
            .items()} == {k: v.strip() for k, v in f.items()}


def test_glonass_of_rinex_3_has_three_or_four_lines():
    # 3.05 revision history, 1-Sep-2020: "Added a 5th line to the GLONASS
    # navigation message (Table A10)".
    three = record3("R01", (2006, 10, 1, 0, 15, 0), A11_R01[:15], "0E")
    for version in ("3.04", "3.05"):
        nav = read_nav(file(version, three))
        f = nav_fields(nav, nav.records[0])
        assert len(nav.records[0].lines) == 3 and f["age"].strip() == "0.100000000000E+01"
        assert f["status_flags"] == "" and f["health_flags"] == ""
        assert write_nav(nav) == file(version, three)
    five = [*record3("R01", (2006, 10, 1, 0, 15, 0), A11_R01, "0E"), orbit([1.0])]
    with pytest.raises(Invalid, match="5 lines after the first, RINEX 3.05 Table A10 has 4"):
        read_nav(file("3.05", five))
    with pytest.raises(Invalid, match="2 lines"):
        read_nav(file("3.05", three[:-1]))


# ---- RINEX 4 ------------------------------------------------------------------------

DATE4 = (2021, 7, 5, 22, 0, 0)


def record4(key, shape_text, start=1.0) -> list[str]:
    kind, system, message, subtype = key
    values = groups(shape_text, numbers(shape_text, start))
    head = (f"> {kind}{source(key)} {message:4}" + (f" {subtype}" if subtype else "")).rstrip()
    if kind == "STO":   # 4X,I4,5(1X,I2.2),3(1X,A18): GPUT, no SBAS ID, the UTC ID
        line0 = first("", DATE4, [" GPUT".ljust(19), None, " UTC(USNO)"])
    else:
        line0 = first(f"{system}07" if kind == "EPH" else "", DATE4, values[0])
    return [head, line0, *(orbit(v) for v in values[1:])]


@pytest.mark.parametrize("key", sorted(SHAPES4))
def test_rinex_4_every_message_round_trips(key):
    kind, system, message, subtype = key
    body = record4(key, SHAPES4[key])
    text = file("4.02", body)
    nav = read_nav(text)
    assert write_nav(nav) == text
    (record,) = nav.records
    assert nav_type(nav, record) == key
    assert record.type == NavType(" " + kind, source(key), " " + message,
                                  " " + subtype if subtype else "")
    assert record.epoch.sat == (f"{system}07" if kind == "EPH" else "   ")
    f = nav_fields(nav, record)
    assert list(f) == list(layout4(key).names)
    named = [v for v in numbers(SHAPES4[key]) if v is not None]
    if kind == "STO":
        assert (f["offset"].strip(), f["sbas_id"].strip(), f["utc_id"].strip()) == (
            "GPUT", "", "UTC(USNO)")
        assert [real(v) for v in list(f.values())[3:]] == [real(d(v)) for v in named[3:]]
    else:
        assert [real(v) for v in f.values()] == [real(d(v)) for v in named]
    # A line more or a line fewer than the table is refused.
    with pytest.raises(Invalid, match="lines after the first"):
        read_nav(file("4.02", [*body, orbit([1.0])]))
    if len(body) > 2:
        with pytest.raises(Invalid, match="lines after the first"):
            read_nav(file("4.02", body[:-1]))


def test_rinex_4_examples():
    # 4.02 Table A27, "> EPH C05 D2" (A2 message type) and "> EPH C20 CNV1";
    # Table A32, "> EPH I10 L1NV"; Table A41: STO, EOP and ION records.
    body = [
        "> EPH C05 D2",
        *record3("C05", (2021, 7, 5, 22, 0, 0), [
            -5.836377386004e-05, 1.694644424788e-11, 0.0,
            0.0, -5.88125e+01, 1.949724070976e-09, -1.593114605012e+00,
            -1.817941665649e-06, 7.691901409999e-04, 1.800991594791e-05, 6.493525815964e+03,
            1.656e+05, 2.072192728519e-07, 2.624951167227e+00, -1.122243702412e-07,
            1.151558582809e-01, -5.49703125e+02, -4.9542147195e-01, -8.100337411567e-10,
            6.564559154524e-10, None, 809.0, None,
            2.0, 0.0, 0.0, -9.5e-09,
            1.656e+05, 0.0]),
        "> EPH C20 CNV1",
        *record3("C20", (2021, 7, 5, 22, 0, 0), [
            -8.537324611098e-04, 1.167599350538e-11, 0.0,
            -3.525733947754e-03, 1.9609375e+00, 3.931056601429e-09, -2.980266083268e+00,
            7.729977369308e-08, 8.434175979346e-04, 7.596798241138e-06, 5.282624978926e+03,
            1.656e+05, -4.190951585770e-08, -2.772741033988e+00, -2.514570951462e-08,
            9.666057809078e-01, 2.101328125e+02, -6.122205141961e-01, -6.644205329250e-09,
            4.784127849557e-10, 2.655139894109e-14, 3.0, 1.656e+05,
            0.0, -4.0, -1.0, -1.0,
            -3.492459654808e-10, None, 2.328306436539e-08, -2.968590706587e-09,
            -1.0, 0.0, 0.0, 18.0,
            1.656e+05, None, None, 18.0]),
        "> EPH I10 L1NV",
        *record3("I10", (2023, 6, 24, 0, 5, 0), [
            1.527369022369e-07, 1.364242052659e-12, 0.0,
            0.0, -2.593125e+02, 7.028864208979e-09, 2.300305834983e+00,
            -8.691102266312e-06, 4.531537415460e-04, -3.855675458908e-06, 6.493495117188e+03,
            7.0, 1.341104507446e-07, 1.359342162629e-01, -7.078051567078e-08,
            8.594830530333e-02, 1.214375e+02, -5.136403830694e-02, -5.858815471753e-09,
            -4.846630453041e-10, 0.0, None, 1.0,
            15.0, 0.0, None, -3.608874976635e-09,
            None, None, 6.984919309616e-09, 5.995389074087e-09,
            5.19138e+05]),
        "> STO E   IFNV",
        first("", (2020, 9, 15, 0, 0, 0), [" GAUT".ljust(19), None, " UTCGAL"]),
        orbit([1.735e+05, -1.862645149231e-09, 0.0, 0.0]),
        "> STO E   LEG",     # as printed in Table A41: not a message type of Table 21
        first("", (2020, 9, 16, 0, 0, 0), [" GAGP".ljust(19)]),
        orbit([2.173e+05, 2.299202606082e-09, 0.0, 0.0]),
        "> EOP G24 CNVX",
        first("", (2020, 9, 18, 19, 56, 48), [2.070846557617e-01, -2.679824829102e-04, 0.0]),
        orbit([None, 3.392457962036e-01, -1.400947570801e-03, 0.0]),
        orbit([2.53248e+05, -1.759799122810e-01, -7.975101470947e-05, 0.0]),
        "> ION G14 CNVX",
        first("", (2021, 7, 5, 23, 30, 42), [7.450580596924e-09, 2.235174179077e-08,
                                             -5.960464477539e-08]),
        orbit([-1.192092895508e-07, 9.216e+04, 1.31072e+05, -6.5536e+04]),
        orbit([-5.24288e+05]),
        "> ION I10 L1NV KLOB",
        first("", (2023, 6, 24, 0, 7, 30), [1.0]),
        orbit([5.867332220078e-08, 2.533197402954e-07, -1.430511474609e-06, -7.5101852417e-06]),
        orbit([1.49504e+05, -5.40672e+05, 2.883584e+06, 8.323072e+06]),
        orbit([50.0, 110.0, 0.0, 50.0]),
        "> ION R22 LXOC",
        first("", (2024, 2, 3, 0, 1, 9), [1.0, 141.0, 5.0]),
    ]
    text = file("4.02", body)
    nav = read_nav(text)
    assert write_nav(nav) == text
    assert [nav_type(nav, r) for r in nav.records] == [
        ("EPH", "C", "D2", ""), ("EPH", "C", "CNV1", ""), ("EPH", "I", "L1NV", ""),
        ("STO", "E", "IFNV", ""), ("STO", "E", "LEG", ""), ("EOP", "G", "CNVX", ""),
        ("ION", "G", "CNVX", ""), ("ION", "I", "L1NV", "KLOB"), ("ION", "R", "LXOC", "")]
    d2, cnv1, l1nv, sto, leg, eop, ion, klob, lxoc = nav.records
    assert d2.type == NavType(" EPH", " C05", " D2", "")
    assert real(nav_fields(nav, d2)["week"]) == (8090000000000, -10)
    f = nav_fields(nav, cnv1)
    assert f["isc_b1cd"] == "-3.492459654808e-10" and f["tgd_b1cp"] == " 2.328306436539e-08"
    assert f["iodc"] == f["iode"] == " 1.800000000000e+01" and real(f["sat_type"]) == (
        3000000000000, -12)
    assert cnv1.lines[8] == NavLine("    ", " 1.656000000000e+05", " " * 19, " " * 19,
                                    " 1.800000000000e+01")
    f = nav_fields(nav, l1nv)
    assert f["rsf"] == " 1.000000000000e+00" and f["tgd_l1p_l5"] == " " * 19
    assert f["isc_s_l1p"] == " " * 19 and f["isc_l1d_s"] == " 5.995389074087e-09"
    assert f["t_tm"] == " 5.191380000000e+05"

    assert sto.epoch == NavEpoch("   ", " 2020", " 09", " 15", " 00", " 00", " 00",
                                 " GAUT" + " " * 14, " " * 19, " UTCGAL")
    assert nav_fields(nav, sto) == {
        "offset": " GAUT" + " " * 14, "sbas_id": " " * 19, "utc_id": " UTCGAL",
        "t_tm": " 1.735000000000e+05", "a0": "-1.862645149231e-09",
        "a1": " 0.000000000000e+00", "a2": " 0.000000000000e+00"}
    assert nav_fields(nav, leg)["offset"] == " GAGP" and nav_fields(nav, leg)["utc_id"] == ""
    f = nav_fields(nav, eop)
    assert list(f) == ["xp", "xp_dot", "xp_dot2", "yp", "yp_dot", "yp_dot2", "t_tm", "dut1",
                       "dut1_dot", "dut1_dot2"]
    assert f["yp"] == " 3.392457962036e-01" and f["dut1"] == "-1.759799122810e-01"
    f = nav_fields(nav, ion)
    assert f["alpha3"] == "-1.192092895508e-07" and f["beta3"] == "-5.242880000000e+05"
    assert nav_fields(nav, klob)["iodk"] == " 1.000000000000e+00"
    assert nav_fields(nav, klob)["lat_max"] == " 5.000000000000e+01"
    assert nav_fields(nav, lxoc) == {"c_a": " 1.000000000000e+00", "c_f107":
                                     " 1.410000000000e+02", "c_ap": " 5.000000000000e+00"}


def test_glonass_cdma_as_the_example_prints_it():
    # 4.02 Table A18, "> EPH R26 L1OC": BROADCAST ORBIT - 8 printed with
    # three values, the transmission time third; Table A16 has a spare
    # third and the transmission time fourth. The names follow the table.
    values = [-1.605716170161e-05, 1.652011860642e-12, -2.081668171172e-17,
              1.812154053020e+04, -2.071979139000e+00, 5.729816621169e-10, 1.0,
              -2.325615360260e+03, 1.285475494340e+00, -1.047737896442e-09, 1.0,
              1.781341854668e+04, 2.280306640081e+00, -9.458744898438e-10, 0.0,
              2.0, 10.0, 0.75, 0.75, *[0.0] * 12, 15.0, 5.0, 5.184e+05]
    text = file("4.02", ["> EPH R26 L1OC", *record3("R26", (2024, 2, 3, 0, 15, 0), values)])
    nav = read_nav(text)
    assert write_nav(nav) == text
    (record,) = nav.records
    assert len(record.lines) == 8
    f = nav_fields(nav, record)
    assert f["urai_orb"] == " 1.500000000000e+01" and f["urai_clk"] == " 5.000000000000e+00"
    assert f["t_tm"] == "" and record.values[-2] == " 5.184000000000e+05"
    assert f["tgd_l2ocp"] == " 0.000000000000e+00" and f["aodc"] == " 7.500000000000e-01"


def test_rinex_4_records_without_a_table_are_kept_whole():
    body = [
        "> EPH G01 XNAV",                               # no such message type
        first("G01", DATE4, [1.0, 2.0, 3.0]), orbit([4.0]), orbit(["anything"]),
        "> ALM G   XXXX",                               # no such record type
        first("", DATE4, ["some text"]),
        "> ION I   L1NV XXXX",                          # no such subtype
        first("", DATE4, [1.0]),
        "> ION S   SBAS",                               # no ION table for SBAS
        first("", DATE4, [1.0, 2.0, 3.0]), orbit([4.0, 5.0, 6.0, 7.0]),
    ]
    text = file("4.02", body)
    nav = read_nav(text)
    assert write_nav(nav) == text
    assert [len(r.lines) for r in nav.records] == [2, 0, 0, 1]
    assert nav.records[0].lines[1].v1 == "anything"
    assert nav_type(nav, nav.records[1]) == ("ALM", "G", "XXXX", "")
    for record in nav.records:
        with pytest.raises(Unsupported, match="no table"):
            nav_fields(nav, record)
    # They are still on the grid: 80 columns, four blanks before the values.
    for bad in ([body[0], body[1] + "x" * 30], [body[0], body[1], "x" + orbit([4.0])[1:]],
                [body[4], "G01" + body[5][3:].replace("2021", "20x1")]):
        with pytest.raises(Invalid):
            read_nav(file("4.02", bad))


# ---- RINEX 2 ------------------------------------------------------------------------

def test_rinex_2_examples():
    # 2.11 Table A8 (GPS), Table A12 (GLONASS), Table A18 (GEO).
    gps = [first2(6, (1999, 9, 2, 17, 51, 44.0), A7[:3]),
           *(orbit(c, "D", 3) for c in chunks(A7[3:27])), orbit([.4068e+06, 0.0], "D", 3)]
    text = file("2.11", gps, kind="N: GPS NAV DATA", system=" ", extra=[
        h("     .1676D-07   .2235D-07  -.1192D-06  -.1192D-06", "ION ALPHA")])
    nav = read_nav(text)
    assert write_nav(nav) == text and nav.version == "2.11" and nav.file_type == "N"
    (g06,) = nav.records
    # " 6 99  9  2 17 51 44.0 -.839701388031D-03 ..."
    assert g06.epoch == NavEpoch2(" 6", " 99", "  9", "  2", " 17", " 51", " 44.0",
                                  " -.839701388031D-03", " -.165982783074D-10",
                                  "  .000000000000D+00")
    assert g06.lines[0] == NavLine2("   ", "  .910000000000D+02", "  .934062500000D+02",
                                    "  .116040547840D-08", "  .162092304801D+00")
    assert nav_type(nav, g06) == ("EPH", "G", "", "")
    f = nav_fields(nav, g06)
    assert list(f) == list(_nav.NAV3["G"].names)
    assert real(f["week"]) == (102500000000, -8) and f["fit_interval"].strip() \
        == ".000000000000D+00"

    glo = [first2(3, (1998, 2, 15, 0, 15, 0.0), [0.163525342941e-03, 0.363797880709e-11,
                                                  0.108e+05], "0D"),
           orbit([0.106275903320e+05, -0.348924636841e+00, 0.931322574615e-09, 0.0], "0D", 3),
           orbit([-0.944422070313e+04, 0.288163375854e+01, 0.931322574615e-09, 21.0], "0D", 3),
           orbit([0.212257280273e+05, 0.144599342346e+01, -0.186264514923e-08, 3.0], "0D", 3)]
    text = file("2.11", glo, kind="GLONASS NAV DATA", system=" ")
    nav = read_nav(text)
    assert write_nav(nav) == text and nav.file_type == "G"
    f = nav_fields(nav, nav.records[0])
    assert nav.records[0].epoch.sat == " 3" and nav_type(nav, nav.records[0])[1] == "R"
    assert f["frame_time"] == " 0.108000000000D+05" and f["freq_num"] == " 0.210000000000D+02"
    assert f["z"] == " 0.212257280273D+05" and f["age"] == " 0.300000000000D+01"

    geo = [first2(22, (2003, 10, 18, 0, 1, 4.0), [-1.005828380585e-07, 6.366462912410e-12,
                                                  5.18442e+05], "E"),
           orbit([2.482832392e+04, -3.59375e-04, -1.375e-07, 0.0], "E", 3),
           orbit([-3.408920872e+04, -1.480625e-03, -5.0e-08, 4.0], "E", 3),
           orbit([-1.65056e+01, 8.36e-04, 6.25e-08, 23.0], "E", 3)]
    text = file("2.11", geo, kind="H: GEO NAV MSG DATA", system=" ")
    nav = read_nav(text)
    assert write_nav(nav) == text and nav.file_type == "H"
    f = nav_fields(nav, nav.records[0])
    assert nav_type(nav, nav.records[0]) == ("EPH", "S", "", "")
    assert f["t_tm"] == " 5.184420000000E+05" and f["accuracy"] == " 4.000000000000E+00"
    assert f["iodn"] == " 2.300000000000E+01"
    # Several records: a line with a character in columns 1 to 2 starts one.
    text = file("2.11", geo + geo, kind="H: GEO NAV MSG DATA", system=" ")
    assert len(read_nav(text).records) == 2 and write_nav(read_nav(text)) == text
    with pytest.raises(Invalid, match="4 lines after the first, RINEX 2.11 Table A16 has 3"):
        read_nav(file("2.11", [*geo, orbit([1.0], "E", 3)], kind="H", system=" "))
    with pytest.raises(Invalid, match="second"):
        read_nav(file("2.11", [geo[0].replace(" 4.0", "  40"), *geo[1:]], kind="H"))
    with pytest.raises(Invalid, match="columns 1 to 3"):
        read_nav(file("2.11", [geo[0], "  x" + geo[1][3:], *geo[2:]], kind="H"))


# ---- what is refused ----------------------------------------------------------------

@pytest.mark.parametrize("version, kind", [
    ("3.05", "OBSERVATION DATA"), ("4.02", "OBSERVATION DATA"), ("2.11", "OBSERVATION DATA"),
    ("3.05", "METEOROLOGICAL DATA"), ("3.05", "GLONASS NAV DATA"), ("3.05", "H: GEO NAV"),
    ("4.02", "C"), ("1.00", "N"), ("5.00", "N"), ("", "N"),
])
def test_other_versions_and_types_are_unsupported(version, kind):
    with pytest.raises(Unsupported):
        read_nav(file(version, [], kind=kind))


def test_read_still_refuses_navigation_files():
    for text in (MIXED3, file("4.02", record4(("EPH", "G", "LNAV", ""), "xxx"))):
        with pytest.raises(Unsupported, match="file type 'N'"):
            rinex.read(text)


G4 = record4(("EPH", "G", "LNAV", ""), SHAPES4["EPH", "G", "LNAV", ""])
FILE4 = file("4.02", G4 + record4(("STO", "G", "LNAV", ""), "xxx xxxx"))


@pytest.mark.parametrize("damage, match", [
    (lambda t: "", "empty"),
    (lambda t: t.replace("RINEX VERSION / TYPE", "COMMENT"), "first record"),
    (lambda t: t.split(h("", "END OF HEADER"))[0], "no END OF HEADER"),
    (lambda t: t.replace(h("    13", "LEAP SECONDS"), "    13"), "label"),
    (lambda t: t.replace("G06 1999", "X06 1999"), "satellite number"),
    (lambda t: t.replace("G06 1999", "G6  1999"), "satellite number"),
    (lambda t: t.replace("G06 1999", " 06 1999"), "expected the first line of a record"),
    (lambda t: t.replace("R01 2006", "    2006"), "12 lines after the first"),
    (lambda t: t.replace("G06 1999 09", "G06 1999 9 "), "month"),
    (lambda t: t.replace("G06 1999", "G06 19x9"), "year"),
    (lambda t: t.replace("17 51 44", "17 51   "), "second"),
    (lambda t: t.replace("  .934062500000D+02", "  .934062500000D+0x"), "crs .* not a number"),
    (lambda t: t.replace("  .934062500000D+02", "  .9340625 0000D+02"), "not a number"),
    (lambda t: t.replace("  .934062500000D+02", "                  D"), "not a number"),
    (lambda t: t.replace("  .934062500000D+02", "               nan "), "not a number"),
    (lambda t: t.replace(" -.839701388031D-03", " -.839701388031D-03" + "9" * 60),
     "past column"),
    (lambda t: t.replace("\n      .910000000000D+02", "\n   x  .910000000000D+02"),
     "columns 1 to 4"),
    (lambda t: t.replace("\nR01", "\n\nR01"), "8 lines after the first"),
    (lambda t: t.replace("\nR01", "\r\nR01"), "both LF and CR LF"),
    (lambda t: t.replace("R01", "R\r1"), "CR inside"),
    (lambda t: t[:t.index("\nR01")], None),               # a whole file of one record: fine
    (lambda t: t.replace(orbit([.4068e+06, 4.0], "D") + "\n", ""), "6 lines after the first"),
])
def test_refusals(damage, match):
    if match is None:
        assert len(read_nav(damage(MIXED3)).records) == 1
        return
    with pytest.raises(Invalid, match=match):
        read_nav(damage(MIXED3))


@pytest.mark.parametrize("damage, match", [
    (lambda t: t.replace("> EPH G07 LNAV\n", ""), "expected a record header line"),
    (lambda t: t.replace("> EPH G07 LNAV", "> EPH G08 LNAV"), "under a header line"),
    (lambda t: t.replace("> EPH G07 LNAV", ">  EPH G07 LNAV"), "past column|does not follow"),
    (lambda t: t.replace("> EPH G07 LNAV", ">EPH G07 LNAV"), "does not follow a blank"),
    (lambda t: t.replace("> EPH G07 LNAV", "> EPH G07"), "record type, a source and a message"),
    (lambda t: t.replace("> EPH G07 LNAV", "> EPH G07 LNAV KLOB XX"), "past column"),
    (lambda t: t.replace("> EPH G07 LNAV", "> EPH G07 LNAV\n> EPH G07 LNAV"), "no record"),
    (lambda t: t + ">", "no record"),
    (lambda t: t.replace("> STO G   LNAV\n   ", "> STO G   LNAV\nG07"), "columns 1 to 3 of STO"),
    (lambda t: t.replace("> STO G   LNAV", "> STO G   LNAV\n"), "year"),
    (lambda t: t.replace("\nG07 2021", "\n    2021"), "satellite number"),
])
def test_rinex_4_refusals(damage, match):
    with pytest.raises(Invalid, match=match):
        read_nav(damage(FILE4))


def test_write_checks_what_read_would_refuse():
    nav = read_nav(MIXED3)
    g06 = nav.records[0]
    e, ln = g06.epoch, g06.lines[0]

    def with_first(record):
        return NavFile(nav.header, (record, *nav.records[1:]), nav.newline, nav.final_newline)

    change = lambda obj, **kw: type(obj)(**{**{n: getattr(obj, n) for n, _ in         # noqa: E731
                                            rinex.columns(type(obj))}, **kw})
    assert write_nav(with_first(g06)) == MIXED3
    bad = [
        with_first(NavRecord(None, e, g06.lines[:-1])),                       # six lines
        with_first(NavRecord(None, e, (*g06.lines, ln))),                     # eight
        with_first(NavRecord(NavType(" EPH", " G06", " LNAV", ""), e, g06.lines)),
        with_first(NavRecord(None, change(e, sat="G6"), g06.lines)),          # short inside
        with_first(NavRecord(None, change(e, sat="   "), g06.lines)),         # joins the header
        with_first(NavRecord(None, change(e, v1="x" * 19), g06.lines)),
        with_first(NavRecord(None, change(e, v1="1" * 20), g06.lines)),
        with_first(NavRecord(None, e, (change(ln, indent="G01 "), *g06.lines[1:]))),
        with_first(NavRecord(None, e, (change(ln, v4=" " * 19 + "\n"), *g06.lines[1:]))),
        with_first(NavRecord(None, e, (change(ln, v2=""), *g06.lines[1:]))),  # then v3
        with_first(NavRecord(None, e, (change(ln, v2=5.0), *g06.lines[1:]))),
        with_first(NavRecord(None, NavEpoch2(" 6", " 99", "  9", "  2", " 17", " 51", " 44.0",
                                             e.v1, e.v2, e.v3), g06.lines)),
        with_first(NavRecord(None, e, tuple(NavLine2("   ", x.v1, x.v2, x.v3, x.v4)
                                            for x in g06.lines))),
        with_first("G06"),
        NavFile(nav.header[:-1], nav.records),
        NavFile((), nav.records),
        NavFile((nav.header[0], nav.header[-1], *nav.header[1:]), nav.records),
        NavFile((nav.header[0], HeaderRecord("x" * 59, "COMMENT"), *nav.header[1:]), ()),
        NavFile(("x", *nav.header[1:]), ()),
        NavFile((*nav.header[:-1], "x"), ()),
        NavFile(nav.header, nav.records, newline="\r"),
        # An empty last line and no final newline: it would not be read back.
        NavFile(nav.header, (nav.records[1], NavRecord(None, e, (
            *g06.lines[:-1], NavLine("", "", "", "", "")))), final_newline=False),
        # RINEX 4 records need their header line.
        NavFile((HeaderRecord(nav.header[0].content.replace("3.05", "4.02"), nav.header[0].label),
                 *nav.header[1:]), nav.records),
    ]
    for b in bad:
        with pytest.raises(Invalid):
            write_nav(b)
    obs = HeaderRecord(nav.header[0].content.replace("NAVIGATION DATA", "OBSERVATION DATA"),
                       nav.header[0].label)
    with pytest.raises(Unsupported):
        write_nav(NavFile((obs, *nav.header[1:]), ()))
    with pytest.raises(Unsupported):
        nav_fields(NavFile((obs, *nav.header[1:]), ()), g06)


def test_line_endings_are_kept():
    for text in (MIXED3, FILE4):
        for newline in ("\n", "\r\n"):
            t = text.replace("\n", newline)
            nav = read_nav(t)
            assert nav.newline == newline and nav.final_newline
            assert write_nav(nav) == t
            cut_off = t[:-len(newline)]
            assert not read_nav(cut_off).final_newline and write_nav(read_nav(cut_off)) == cut_off


def test_a_file_with_no_records():
    for version in ("2.11", "3.05", "4.02"):
        text = file(version, [], kind="N")
        assert read_nav(text).records == () and write_nav(read_nav(text)) == text


# ---- real ---------------------------------------------------------------------------

@pytest.mark.parametrize("field, value", [
    ("-.839701388031D-03", (-839701388031, -15)), (" 1.330170780420e-04", (1330170780420, -16)),
    (" 0.798045657575E-04", (798045657575, -16)), ("  .400000000000d+01", (400000000000, -11)),
    ("  2.0", (20, -1)), ("17", (17, 0)), ("-0", (0, 0)), ("+1.5E3", (15, 2)), ("1.E+01", (1, 1)),
    (" .999999999999E+09", (999999999999, -3)), (" " * 19, None), ("", None),
])
def test_real(field, value):
    assert real(field) == value


@pytest.mark.parametrize("field", ["D+01", ".", "-", "1.0D", "1.0 D+01", "1,5", "nan", "0x10",
                                   "1e1.5", "--1"])
def test_real_refuses(field):
    with pytest.raises(rinex.Error):
        real(field)


# ---- generated files -----------------------------------------------------------------

value_text = st.one_of(
    st.just(" " * 19),
    st.tuples(st.floats(-1e9, 1e9).filter(lambda v: v == 0 or abs(v) > 1e-90),   # two digits
              st.sampled_from(["e", "E", "D", "d", "0D"])).map(lambda v: d(*v)))


@st.composite
def value_lines(draw, layout, text_first=False):
    """The values of a record for ``layout``: the first three, then four per line."""
    out = []
    for i, names in enumerate((layout.first, *layout.lines)):
        width = 3 if i == 0 else 4
        if i == 0 and text_first:
            values = [draw(st.sampled_from([" GPUT", " SBUT", ""])).ljust(19),
                      draw(st.sampled_from([" EGNOS", ""])).ljust(19),
                      draw(st.sampled_from([" UTC(USNO)", " UTCGAL", ""])).ljust(19)]
        else:
            # Spares, and the columns after a short line's names, hold anything.
            values = [draw(value_text) if j < len(names) and names[j] is not None
                      else draw(st.one_of(st.just(" " * 19), value_text,
                                          st.text("spare ", min_size=19, max_size=19)))
                      for j in range(width)]
        line = "".join(values)
        if draw(st.booleans()):
            line = line.rstrip()           # truncated trailing blanks
        out.append([line[k:k + 19] for k in range(0, 19 * width, 19)])
    return out


@st.composite
def nav_files(draw):
    major = draw(st.sampled_from(["2", "3", "4"]))
    records = []
    if major == "2":
        file_type = draw(st.sampled_from("NGH"))
        head = h(f"{'2.11':>9}{'':11}{file_type}", "RINEX VERSION / TYPE")
        for _ in range(draw(st.integers(0, 4))):
            v = draw(value_lines(_nav.NAV2[file_type]))
            epoch = NavEpoch2(f"{draw(st.integers(1, 32)):2d}", " 07", " 12", "  1", "  0", "  5",
                              " 44.0", *v[0])
            records.append(NavRecord(None, epoch, tuple(
                NavLine2("   " if "".join(x) else draw(st.sampled_from(["", " ", "   "])), *x)
                for x in v[1:])))
    elif major == "3":
        head = h(f"{draw(st.sampled_from(['3.00', '3.04', '3.05'])):>9}{'':11}N", "RINEX VERSION "
                 "/ TYPE")
        for _ in range(draw(st.integers(0, 4))):
            system = draw(st.sampled_from(sorted(_nav.NAV3)))
            v = draw(value_lines(_nav.NAV3[system]))
            if system == "R" and draw(st.booleans()):
                v = v[:-1]
            epoch = NavEpoch(f"{system}{draw(st.integers(1, 63)):02d}", " 2024", " 02", " 03",
                             " 04", " 05", " 06", *v[0])
            records.append(NavRecord(None, epoch, tuple(
                NavLine("    " if "".join(x) else draw(st.sampled_from(["", "  ", "    "])), *x)
                for x in v[1:])))
    else:
        head = h(f"{draw(st.sampled_from(['4.00', '4.02'])):>9}{'':11}N", "RINEX VERSION / TYPE")
        for _ in range(draw(st.integers(0, 4))):
            key = draw(st.sampled_from(sorted(SHAPES4)))
            kind, system, message, subtype = key
            v = draw(value_lines(layout4(key), text_first=kind == "STO"))
            sat = f"{system}{draw(st.integers(1, 63)):02d}"
            src = " " + sat if kind == "EPH" else draw(st.sampled_from([" " + sat,
                                                                        " " + system + "  "]))
            kind_line = NavType(" " + kind, src, " " + message, " " + subtype if subtype else "")
            epoch = NavEpoch(sat if kind == "EPH" else "   ", " 2024", " 02", " 03", " 04", " 05",
                             " 06", *v[0])
            records.append(NavRecord(kind_line, epoch, tuple(
                NavLine("    " if "".join(x) else draw(st.sampled_from(["", "  ", "    "])), *x)
                for x in v[1:])))
    header = (HeaderRecord(head[:60], head[60:]),
              HeaderRecord(draw(st.text(st.characters(min_codepoint=32, max_codepoint=126),
                                        max_size=60)).ljust(60), "COMMENT"),
              HeaderRecord(" " * 60, "END OF HEADER"))
    # An empty last line can only be told from none by the newline after it.
    empty_end = bool(records and records[-1].lines) and records[-1].lines[-1].indent == ""
    return NavFile(header, tuple(records), draw(st.sampled_from(["\n", "\r\n"])),
                   empty_end or draw(st.booleans()))


@settings(max_examples=200, derandomize=True, deadline=None)
@given(nav_files())
def test_generated_files_round_trip(nav):
    text = write_nav(nav)
    assert read_nav(text) == nav
    assert write_nav(read_nav(text)) == text
    for record in nav.records:
        assert list(nav_fields(nav, record)) == list(
            _nav._layout(nav.version[0], nav.file_type, record).names)
