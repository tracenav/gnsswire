"""RINEX 3 and 4 observation files against RINEX 3.05 and 4.02, Tables A2 and A3.

- The record tables are transcribed a second time here, column for column.
- Files are built line by line from the tables' Fortran formats, with the
  values of RINEX 3.05 Table A4 ("GNSS observation data file - example #1").
  The example itself is not quoted as text: its columns cannot be taken
  reliably from the document (proportional rendering moves them).
- Generated files round-trip: ``write(read(text)) == text``.
- data/rtklib-read.json holds a synthetic file written by this module and
  what RTKLIB's RINEX reader (independent) reads from it; the values must
  agree (make_data/README.md).
"""

import json
import struct
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import rinex
from gnsswire.rinex import (
    Epoch,
    EpochRecord,
    HeaderRecord,
    Invalid,
    ObsFile,
    Observation,
    SatelliteRecord,
    Unsupported,
    number,
)
from gnsswire.rinex._records import join

DATA = Path(__file__).parent / "data"

# (field, width, format) as Table A3 prints the EPOCH record after "> ".
EPOCH_TABLE = [("year", 5, "1X,I4"), ("month", 3, "1X,I2.2"), ("day", 3, "1X,I2.2"),
               ("hour", 3, "1X,I2.2"), ("minute", 3, "1X,I2.2"), ("second", 11, "F11.7"),
               ("flag", 3, "2X,I1"), ("count", 3, "I3"), ("reserved", 6, "6X"),
               ("clock", 15, "F15.12"), ("picoseconds", 6, "1X,I5.5")]


def test_tables_are_the_documents():
    assert [(n, c.width, c.fmt) for n, c in rinex.columns(EpochRecord)] == EPOCH_TABLE
    assert [(n, c.width, c.fmt) for n, c in rinex.columns(Observation)] == [
        ("value", 14, "F14.3"), ("lli", 1, "I1"), ("ssi", 1, "I1")]
    assert [(n, c.width) for n, c in rinex.columns(HeaderRecord)] == [("content", 60),
                                                                       ("label", 20)]


def test_epoch_columns():
    # Table A3 by column, 1-based, with the record identifier ">" in column
    # 1: year 3-6, month 8-9, day 11-12, hour 14-15, minute 17-18, second
    # 19-29, flag 32, count 33-35, reserved 36-41, clock 42-56, and in 4.02
    # picoseconds 58-62.
    record = EpochRecord(" YYYY", " MM", " DD", " hh", " mm", "sssssssssss", "  F", "CCC",
                         "rrrrrr", "ooooooooooooooo", " ppppp")
    line = ">" + join(record)
    assert len(line) == 62
    spans = {c: (line.index(c) + 1, line.rindex(c) + 1) for c in "YMDhmsFCrop"}
    assert spans == {"Y": (3, 6), "M": (8, 9), "D": (11, 12), "h": (14, 15), "m": (17, 18),
                     "s": (19, 29), "F": (32, 32), "C": (33, 35), "r": (36, 41),
                     "o": (42, 56), "p": (58, 62)}


# ---- building files from the formats ------------------------------------------

def h(content: str, label: str) -> str:
    """A header line: A60 content, then the label (Table A2)."""
    assert len(content) <= 60
    return content.ljust(60) + label


def types_lines(system: str, types: list[str]) -> list[str]:
    """SYS / # / OBS TYPES: A1,2X,I3,13(1X,A3), continuation lines 6X,13(1X,A3)."""
    out = []
    for i in range(0, len(types), 13):
        head = f"{system}  {len(types):3d}" if i == 0 else " " * 6
        out.append(h(head + "".join(f" {t}" for t in types[i:i + 13]), "SYS / # / OBS TYPES"))
    return out


def epoch(year="", month="", day="", hour="", minute="", sec=None, flag=0, count=0,
          clock=None) -> str:
    """An EPOCH record: >,1X,I4,4(1X,I2.2),F11.7,2X,I1,I3,6X,F15.12."""
    time = (f" {year:4d}" + "".join(f" {v:02d}" for v in (month, day, hour, minute))
            + f"{sec:11.7f}") if year else " " * 28
    line = ">" + time + f"  {flag:1d}{count:3d}"
    return line + (" " * 6 + f"{clock:15.12f}" if clock is not None else "")


def sat(name: str, *obs: tuple) -> str:
    """An OBSERVATION record: A1,I2.2, then m(F14.3,I1,I1), trailing blanks truncated."""
    fields = []
    for o in obs:
        value, lli, ssi = (o + (None, None))[:3] if o else (None, None, None)
        fields.append((f"{value:14.3f}" if value is not None else " " * 14)
                      + (str(lli) if lli is not None else " ")
                      + (str(ssi) if ssi is not None else " "))
    return (name + "".join(fields)).rstrip()


A4_TYPES = {"G": ["C1C", "L1W", "L2W", "C1W", "S2W"], "R": ["C1C", "L1C"],
            "E": ["L1B", "L5I"], "S": ["C1C", "L1C"]}


def file(extra_header: list[str], version="3.05", body=(), types=None, newline="\n",
         system="M") -> str:
    types = A4_TYPES if types is None else types
    header = [h(f"{version:>9}{'':11}OBSERVATION DATA    {system}", "RINEX VERSION / TYPE"),
              h("XXRINEXO V9.9       AIUB                20060324 144333 UTC",
                "PGM / RUN BY / DATE")]
    for s, t in types.items():
        header += types_lines(s, t)
    header += extra_header + [h("", "END OF HEADER")]
    return newline.join([*header, *body]) + newline


# RINEX 3.05 Table A4, the first two epochs, an event with two comment
# lines, and a new site occupation with its header records.
A4_BODY = [
    epoch(2006, 3, 24, 13, 10, 36.0, 0, 5, -0.123456789012),
    sat("G06", (23629347.915,), (0.300, None, 8), (-0.353, None, 4), (23629347.158,), (24.158,)),
    sat("G09", (20891534.648,), (-0.120, None, 9), (-0.358, None, 6), (20891545.292,), (38.123,)),
    sat("G12", (20607600.189,), (-0.430, None, 9), (0.394, None, 5), (20607600.848,), (35.234,)),
    sat("E11", (0.324, None, 8), (0.178, None, 7)),
    sat("S20", (38137559.506,), (335849.135, None, 9)),
    epoch(2006, 3, 24, 13, 10, 54.0, 0, 7, -0.123456789210),
    sat("G06", (23619095.450,), (-53875.632, None, 8), (-41981.375, None, 4), (23619095.008,),
        (25.234,)),
    sat("G09", (20886075.667,), (-28688.027, None, 9), (-22354.535, None, 7), (20886076.101,),
        (42.231,)),
    sat("G12", (20611072.689,), (18247.789, None, 9), (14219.770, None, 6), (20611072.410,),
        (36.765,)),
    sat("R21", (21345678.576,), (12345.567, None, 5)),
    sat("R22", (22123456.789,), (23456.789, None, 5)),
    sat("E11", (65432.123, None, 5), (48861.586, None, 7)),
    sat("S20", (38137559.506,), (335849.135, None, 9)),
    epoch(2006, 3, 24, 13, 11, 12.0, 2, 2),
    h("       *** FROM NOW ON KINEMATIC DATA! ***", "COMMENT"),
    h("       TWO COMMENT LINES FOLLOW DIRECTLY THE EVENT RECORD", "COMMENT"),
    epoch(2006, 3, 24, 13, 11, 12.0, 0, 1, -0.123456789876),
    sat("G06", (21110991.756,), (16119.980, 7), (12560.510, None, 4), (21110991.441,), (25.543,)),
    epoch(flag=3, count=2),
    h("A 9081", "MARKER NAME"),
    h("9081.1.34", "MARKER NUMBER"),
]
A4 = file([h("A 9080", "MARKER NAME")], body=A4_BODY)


def test_a4_reads_and_writes_back():
    obs = rinex.read(A4)
    assert rinex.write(obs) == A4
    assert obs.version == "3.05"
    assert rinex.obs_types(obs.header) == {s: tuple(t) for s, t in A4_TYPES.items()}
    assert [e.record.flag for e in obs.epochs] == ["  0", "  0", "  2", "  0", "  3"]
    first = obs.epochs[0]
    assert first.record == EpochRecord(" 2006", " 03", " 24", " 13", " 10", " 36.0000000",
                                       "  0", "  5", "      ", "-0.123456789012", "")
    g06 = first.satellites[0]
    assert g06.sat == "G06" and len(g06.obs) == 5
    assert g06.obs[0] == Observation("  23629347.915", " ", " ")
    assert g06.obs[1] == Observation("         0.300", " ", "8")
    assert g06.obs[4] == Observation("        24.158", "", "")     # truncated record
    assert [number(o.value, 3) for o in g06.obs] == [23629347915, 300, -353, 23629347158,
                                                     24158]
    assert first.satellites[3].sat == "E11" and len(first.satellites[3].obs) == 2
    event = obs.epochs[2]
    assert event.satellites == () and [r.label.rstrip() for r in event.special] == [
        "COMMENT", "COMMENT"]
    assert obs.epochs[3].satellites[0].obs[1].lli == "7"
    site = obs.epochs[4]
    assert site.record.year == "     " and site.record.count == "  2"
    assert site.special[0] == HeaderRecord("A 9081".ljust(60), "MARKER NAME")


def test_records_may_hold_fewer_observations_than_types():
    # 3.05 section 5.3.3: "(if last in the record) can be truncated".
    text = file([], body=[epoch(2006, 3, 24, 13, 10, 36.0, 0, 2), "G01", sat("G02", (1.0,))])
    obs = rinex.read(text)
    assert [len(s.obs) for s in obs.epochs[0].satellites] == [0, 1]
    assert rinex.write(obs) == text


def test_more_observations_than_types_are_refused():
    body = [epoch(2006, 3, 24, 13, 10, 36.0, 0, 1), sat("R01", (1.0,), (2.0,), (3.0,))]
    with pytest.raises(Invalid, match="3 observations"):
        rinex.read(file([], body=body))


def test_header_event_redefines_obs_types():
    # Flag 4, "header information follows"; 3.05 section 6.5: "each value
    # remains valid until changed by an additional header record".
    body = [epoch(2006, 3, 24, 13, 10, 36.0, 0, 1), sat("R01", (1.0,), (2.0,)),
            epoch(2006, 3, 24, 13, 10, 37.0, 4, 1), *types_lines("R", ["C1C", "L1C", "D1C"]),
            epoch(2006, 3, 24, 13, 10, 38.0, 0, 1), sat("R01", (1.0,), (2.0,), (3.0,))]
    text = file([], body=body)
    assert rinex.write(rinex.read(text)) == text
    # The same records under flag 2 change nothing.
    body[2] = epoch(2006, 3, 24, 13, 10, 37.0, 2, 1)
    with pytest.raises(Invalid, match="3 observations"):
        rinex.read(file([], body=body))


def test_cycle_slip_records():
    # Flag 6: "same format as OBSERVATIONS records".
    body = [epoch(2006, 3, 24, 13, 10, 36.0, 6, 1), sat("G06", None, (1.0, 1))]
    obs = rinex.read(file([], body=body))
    assert obs.epochs[0].satellites[0].obs[1] == Observation("         1.000", "1", "")


def test_obs_types_continuation_lines():
    types = [f"C{b}{a}" for b in "125678" for a in "CQXI"][:23]
    lines = types_lines("E", types)
    assert len(lines) == 2 and lines[1][:6] == " " * 6
    text = file([], types={"E": types})
    assert rinex.obs_types(rinex.read(text).header) == {"E": tuple(types)}
    wrong = file([], types={"E": types}).replace(" 23 C1C", " 24 C1C")
    with pytest.raises(Invalid, match="23 types, says 24"):
        rinex.read(wrong)


def test_rinex_4_picoseconds():
    # 4.02 Table A3: "Additional 5 digits to append to 'seconds'", 1X,I5.5.
    line = epoch(2024, 10, 1, 0, 0, 0.0, 0, 1, 0.0) + " 12345"
    obs = rinex.read(file([], version="4.02", body=[line, sat("G01", (1.0,))]))
    assert obs.epochs[0].record.picoseconds == " 12345"
    assert obs.version == "4.02"
    with pytest.raises(Invalid, match="RINEX 4"):
        rinex.read(file([], version="3.05", body=[line, sat("G01", (1.0,))]))
    with pytest.raises(Invalid, match="past column"):
        rinex.read(file([], version="4.02", body=[line + "9", sat("G01", (1.0,))]))


def test_line_endings_are_kept():
    for newline in ("\n", "\r\n"):
        text = file([], body=A4_BODY, newline=newline)
        obs = rinex.read(text)
        assert obs.newline == newline and obs.final_newline
        assert rinex.write(obs) == text
        assert rinex.write(rinex.read(text[:-len(newline)])) == text[:-len(newline)]
    with pytest.raises(Invalid, match="both LF and CR LF"):
        rinex.read(A4.replace("\n", "\r\n", 1))


@pytest.mark.parametrize("version, system", [("2.11", "M"), ("1.00", "G"), ("5.00", "M")])
def test_other_versions_are_unsupported(version, system):
    with pytest.raises(Unsupported):
        rinex.read(file([], version=version, system=system))


def test_other_file_types_are_unsupported():
    nav = h("     3.05           NAVIGATION DATA     M", "RINEX VERSION / TYPE")
    with pytest.raises(Unsupported, match="file type 'N'"):
        rinex.read(nav + "\n" + h("", "END OF HEADER") + "\n")


@pytest.mark.parametrize("damage, match", [
    (lambda t: t.replace("RINEX VERSION / TYPE", "COMMENT"), "first record"),
    (lambda t: t.split(h("", "END OF HEADER"))[0], "no END OF HEADER"),
    (lambda t: t.replace(h("A 9080", "MARKER NAME"), "A 9080"), "label"),
    (lambda t: t.replace("> 2006 03 24 13 10 54", "  2006 03 24 13 10 54"), "starts with '>'"),
    (lambda t: t.replace("  0  7", "  9  7"), "epoch flag"),
    (lambda t: t.replace("  3  2", "  3  3"), "records announced"),
    (lambda t: t.replace("  0  7", "  0 x7"), "not I3"),
    (lambda t: t.replace("R21", "X21"), "satellite number"),
    (lambda t: t.replace("R21", "R2 "), "satellite number"),
    (lambda t: t.replace("\nR21", "\nC21"), "no SYS / # / OBS TYPES record for system C"),
    (lambda t: t.replace("MARKER NAME", "MARKER NAME" + "x" * 10), "past column"),
    (lambda t: t.replace("R21", "R21\r"), "CR inside"),
    (lambda t: "", "empty"),
])
def test_refusals(damage, match):
    with pytest.raises(Invalid, match=match):
        rinex.read(damage(A4))


def test_write_checks_what_read_would_refuse():
    obs = rinex.read(A4)
    first = obs.epochs[0]

    def with_first(**changes):
        e = Epoch(**{"record": first.record, "satellites": first.satellites,
                     "special": first.special, **changes})
        return ObsFile(obs.header, (e, *obs.epochs[1:]), obs.newline, obs.final_newline)

    bad = [
        with_first(satellites=first.satellites[:-1]),                       # count is 5
        with_first(special=(obs.header[1],)),                               # flag 0
        with_first(satellites=(SatelliteRecord("G06", (Observation("1", "", ""),
                                                       Observation("2", "", ""))),
                               *first.satellites[1:])),                     # short inside
        with_first(satellites=(SatelliteRecord("G06", (Observation("", "", ""),)),
                               *first.satellites[1:])),                     # reads back as ()
        with_first(satellites=(SatelliteRecord("G6", ()), *first.satellites[1:])),
        with_first(record=EpochRecord(" 2006", " 03", " 24", " 13", " 10", " 36.0000000",
                                      "  0", "  5", "", "-0.123456789012", "")),
        with_first(record=EpochRecord(" 2006", " 03", " 24", " 13", " 10", " 36.0000000",
                                      "  0", "  5", "      ", "-0.123456789012", " 12345")),
        ObsFile(obs.header[:-1], obs.epochs),
        ObsFile((obs.header[0], obs.header[-1], *obs.header[1:]), obs.epochs),
        ObsFile((obs.header[0], HeaderRecord("x" * 59, "COMMENT"), *obs.header[1:]), ()),
        ObsFile((obs.header[0], HeaderRecord("x" * 60, "C\nMMENT"), *obs.header[1:]), ()),
        ObsFile(obs.header, obs.epochs, newline="\r"),
    ]
    for b in bad:
        with pytest.raises(Invalid):
            rinex.write(b)


# ---- number ----------------------------------------------------------------------

@pytest.mark.parametrize("field, decimals, value", [
    ("  23629347.915", 3, 23629347915), ("         -.353", 3, -353), ("          .300", 3, 300),
    ("        +1.000", 3, 1000), ("-0.123456789012", 12, -123456789012), ("  5", 0, 5),
    (" 2006", 0, 2006), ("  0", 0, 0), (" 36.0000000", 7, 360000000), ("              ", 3, None),
    ("", 3, None), ("-0", 0, 0),
])
def test_number(field, decimals, value):
    assert number(field, decimals) == value


@pytest.mark.parametrize("field, decimals", [
    ("1.23", 3), ("1.2345", 3), ("12", 3), ("1.0", 0), ("1 2", 0), ("1e3", 0), (".", 0),
    ("-", 0), ("x", 0), ("--1", 0),
])
def test_number_refuses(field, decimals):
    with pytest.raises(ValueError):
        number(field, decimals)


# ---- generated files --------------------------------------------------------------

blank_or = lambda s: st.one_of(st.just(" "), s)                         # noqa: E731
digits = st.sampled_from("0123456789")


@st.composite
def observations(draw):
    value = draw(st.one_of(st.just(" " * 14), st.floats(-9e8, 9e8).map(lambda v: f"{v:14.3f}")))
    return Observation(value, draw(blank_or(digits)), draw(blank_or(digits)))


@st.composite
def records(draw, types):
    system = draw(st.sampled_from(sorted(types)))
    obs = draw(st.lists(observations(), max_size=len(types[system])))
    text = "".join(o.value + o.lli + o.ssi for o in obs)
    if draw(st.booleans()):
        text = text.rstrip()          # truncated trailing blanks
    name = f"{system}{draw(st.integers(1, 99)):02d}"
    return SatelliteRecord(name, tuple(Observation(text[i:i + 14], text[i + 14:i + 15],
                                                   text[i + 15:i + 16])
                                       for i in range(0, len(text), 16)))


@st.composite
def obs_files(draw):
    version = draw(st.sampled_from(["3.05", "4.02", "3.04", "4.00"]))
    types = draw(st.dictionaries(st.sampled_from(rinex.SYSTEMS), st.lists(
        st.from_regex(r"[CLDSX][1-9][A-Z]", fullmatch=True), min_size=1, max_size=30),
        min_size=1, max_size=4))
    head = [h(f"{version:>9}{'':11}OBSERVATION DATA    M", "RINEX VERSION / TYPE")]
    for s, t in types.items():
        head += types_lines(s, t)
    head += [h(draw(st.text(st.characters(min_codepoint=32, max_codepoint=126), max_size=60)),
               "COMMENT"), h("", "END OF HEADER")]
    header = tuple(HeaderRecord(line[:60], line[60:]) for line in head)
    epochs = []
    for _ in range(draw(st.integers(0, 5))):
        flag = draw(st.sampled_from([0, 0, 1, 2, 5, 6]))
        clock = draw(st.one_of(st.just(""), st.floats(-1, 1).map(lambda v: f"{v:15.12f}")))
        pico = draw(st.one_of(st.just(""), digits.map(lambda d: " " + d * 5))) if (
            clock and version.startswith("4")) else ""
        if flag in (2, 5):
            special = tuple(HeaderRecord(draw(st.text("ABC xyz", max_size=60)).ljust(60),
                                         "COMMENT") for _ in range(draw(st.integers(0, 3))))
            sats = ()
        else:
            special = ()
            sats = tuple(draw(st.lists(records(types), max_size=4)))
        n = len(special) + len(sats)
        record = EpochRecord(" 2026", " 01", " 02", " 03", " 04", " 05.0000000", f"  {flag}",
                             f"{n:3d}", "      " if clock else "", clock, pico)
        epochs.append(Epoch(record, sats, special))
    return ObsFile(header, tuple(epochs), draw(st.sampled_from(["\n", "\r\n"])),
                   draw(st.booleans()))


@settings(max_examples=150, derandomize=True, deadline=None)
@given(obs_files())
def test_generated_files_round_trip(obs):
    text = rinex.write(obs)
    assert rinex.read(text) == obs
    assert rinex.write(rinex.read(text)) == text


# ---- RTKLIB --------------------------------------------------------------------------

def test_rtklib_reads_the_same_values():
    data = json.loads((DATA / "rtklib-read.json").read_text())
    obs = rinex.read(data["rinex"])
    assert rinex.write(obs) == data["rinex"]
    types = rinex.obs_types(obs.header)
    ours = {}
    for e in obs.epochs:
        r = e.record
        # 2026-01-01 is a Thursday: GPS time of week 4 days in, at r.minute:r.second.
        tow = 4 * 86400 + number(r.minute) * 60 + number(r.second, 7) / 1e7
        for s in e.satellites:
            for t, o in zip(types[s.sat[0]], s.obs):
                ours[(tow, s.sat, t)] = o
    compared = 0
    for tow, name, signal, p, l, d, snr, lli in data["rtklib"]:
        for kind, got in (("C", p), ("L", l), ("D", d), ("S", snr)):
            o = ours.get((tow, name, kind + signal))
            if o is None or not o.value.strip():
                assert got == 0, (tow, name, kind + signal)   # missing reads as 0
                continue
            v = number(o.value, 3)
            if kind == "S":
                assert got == v, (name, signal)              # 0.001 dB-Hz
            elif kind == "D":                                # RTKLIB keeps a float32
                assert got == struct.unpack("f", struct.pack("f", v / 1000))[0]
            else:
                assert got == float(o.value), (name, kind + signal)
            compared += 1
        # RTKLIB keeps LLI bits 0 and 1 (3.05 section 6.7.1) and drops bit 2.
        phase = ours.get((tow, name, "L" + signal))
        assert lli == (number(phase.lli) or 0 if phase and phase.lli.strip() else 0) & 3
    assert compared > 2500
