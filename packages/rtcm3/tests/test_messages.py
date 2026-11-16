"""Message tables against RTCM 10403.3, public data and an independent encoder.

- Field tables: each fixed-length table's width is the TOTAL row of its
  spec table, and variable-length tables obey the spec's length formula on
  generated messages.
- Section 4.2's example 1005 decodes to the parameters the section lists.
- Round trip: ``encode(decode(frame)) == frame`` on every frame of
  ``data/public.hex`` (public reference-station streams, as received,
  including MSM7 of GPS, GLONASS, QZSS and BeiDou), ``data/rtklib.hex``
  (RTKLIB's encoder run on a public RINEX navigation file, on observations
  of those streams and on seeded synthetic data) and ``data/rtklib-msm.hex``
  (RTKLIB's encoder: MSM1 to MSM7 of every system, and 1044, from those
  streams and seeded synthetic data) and ``data/rtklib-station.hex``
  (RTKLIB's encoder: 1006 and 1005 from seeded synthetic station data) and
  ``data/rtklib-antenna.hex`` (RTKLIB's encoder: 1007, 1008 and 1033 from
  seeded synthetic antenna and receiver descriptors, with RTKLIB's decoding
  of each frame in ``data/rtklib-antenna-decoded.json``), and
  ``decode(encode(msg)) == msg`` on generated messages.
- Antenna descriptors (1007, 1008, and 1033 beside them): Tables 3.5-8,
  3.5-9 and 3.5-36 are transcribed again here, apart from ``_station``, and
  messages built from fields must give that table's bits.
- Cross-check: pyrtcm, a dev-only dependency, decodes the same frames and
  every DF it reports matches ours (test_pyrtcm_agrees). pyrtcm 1.2.1
  cannot parse MSM2 (it raises on its own definition of the MSM2 signal
  block), so MSM2 frames are left out of that comparison only.
"""

import json
import math
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import pyrtcm
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import rtcm3
from gnsswire.bits import (
    NEGATIVE_ZERO,
    SM,
    BitError,
    BitWriter,
    Extension,
    Octets,
    Rest,
    S,
    U,
    layout,
    write,
)

DATA = Path(__file__).resolve().parent / "data"


def load(name: str) -> list[tuple[bytes, str]]:
    out = []
    for line in (DATA / f"{name}.hex").read_text().splitlines():
        if line and not line.startswith("#"):
            hexpart, _, note = line.partition("#")
            out.append((bytes.fromhex(hexpart.strip()), note.strip()))
    return out


PUBLIC = load("public")
RTKLIB = load("rtklib") + load("rtklib-msm") + load("rtklib-station") + load("rtklib-antenna")
CORPUS = PUBLIC + RTKLIB
NUMBERS = sorted(rtcm3.MESSAGES)
GLONASS_MSM = range(1081, 1088)


def number_of(raw: bytes) -> int:
    return int.from_bytes(raw[3:5], "big") >> 4


# --- field tables ----------------------------------------------------------------

@pytest.mark.parametrize(("cls", "total"), [
    (rtcm3.Msg1005, 152),   # Table 3.5-6
    (rtcm3.Msg1006, 168),   # Table 3.5-7
    (rtcm3.Msg1019, 488),   # Table 3.5-21
    (rtcm3.Msg1020, 360),   # Table 3.5-22
    (rtcm3.Msg1042, 511),   # Table 3.5-113
    (rtcm3.Msg1044, 485),   # Table 3.5-112
    (rtcm3.Msg1045, 496),   # Table 3.5-110
    (rtcm3.Msg1046, 504),   # Table 3.5-111
])
def test_fixed_tables_have_the_spec_total(cls, total):
    assert layout(cls).fixed_bits == total


def bits_of(message) -> int:
    w = BitWriter()
    write(message, w)
    return w.pos


def spec_bits(m) -> int:
    """The TOTAL row of the spec table for a variable-length message."""
    if isinstance(m, rtcm3.Msg1007):   # Table 3.5-8
        return 40 + 8 * m.antenna_count
    if isinstance(m, rtcm3.Msg1008):   # Table 3.5-9
        return 48 + 8 * (m.antenna_serial_count + m.antenna_count)
    if isinstance(m, rtcm3.Msg1033):   # Table 3.5-36
        return 72 + 8 * (m.antenna_count + m.antenna_serial_count + m.receiver_count
                         + m.firmware_count + m.receiver_serial_count)
    if isinstance(m, rtcm3.Msg1230):   # Table 3.5-109
        return 32 + 16 * m.mask.bit_count()
    if isinstance(m, rtcm3.Msm):       # Tables 3.5-78 to 3.5-88
        nsat, nsig, ncell = (m.sat_mask.bit_count(), m.sig_mask.bit_count(),
                             m.cell_mask.bit_count())
        level = m.number % 10
        return 169 + nsat * nsig + MSM_SAT_BITS[level] * nsat + MSM_CELL_BITS[level] * ncell
    return layout(type(m)).fixed_bits


# The TOTAL rows per satellite (Tables 3.5-79 to 3.5-81) and per cell (Tables
# 3.5-82 to 3.5-88) of MSM1 to MSM7.
MSM_SAT_BITS = {1: 10, 2: 10, 3: 10, 4: 18, 5: 36, 6: 18, 7: 36}
MSM_CELL_BITS = {1: 15, 2: 27, 3: 42, 4: 48, 5: 63, 6: 65, 7: 80}


def test_msm_upper_bounds_of_table_3_5_71():
    # "No. of Bits (upper bound)" for Nsat = 16 and Nsig = 4, all 64 cells.
    bound = {1: 1353, 2: 2121, 3: 3081, 4: 3593, 5: 4841, 6: 4681, 7: 5929}
    for level, bits in bound.items():
        assert 169 + 16 * 4 + 16 * MSM_SAT_BITS[level] + 64 * MSM_CELL_BITS[level] == bits


# --- generated messages --------------------------------------------------------------

def _int_value(kind, width: int):
    if isinstance(kind, U):
        return st.integers(0, (1 << width) - 1)
    if isinstance(kind, S):
        return st.integers(-(1 << (width - 1)), (1 << (width - 1)) - 1)
    assert isinstance(kind, SM)
    # A negative zero is what a receiver copying GLONASS string bits may send.
    return st.one_of(st.integers(-(1 << (width - 1)) + 1, (1 << (width - 1)) - 1),
                     st.just(NEGATIVE_ZERO))


def _bits(data, positions: int, count: int) -> int:
    chosen = data.draw(st.lists(st.integers(0, positions - 1), min_size=count, max_size=count,
                                unique=True))
    return sum(1 << (positions - 1 - p) for p in chosen)


def draw_message(data, cls, number: int):
    """A random message of ``cls``, drawn row by row from its compiled table."""
    values: dict = {}
    for row in layout(cls).rows:
        kind, name = row.kind, row.name
        env = values.__getitem__
        if kind.when is not None and not kind.when.eval(env) or isinstance(kind, Rest):
            values[name] = None
            continue
        if name == "number":
            values[name] = number
        elif name.endswith("_count"):            # DF029 etc.: the spec's range is 0 to 31
            values[name] = data.draw(st.integers(0, 31))
        elif name == "sat_mask":                 # keep Nsat·Nsig within the 64-bit cell mask
            values[name] = _bits(data, 64, data.draw(st.integers(0, 64)))
        elif name == "sig_mask":
            nsat = values["sat_mask"].bit_count()
            values[name] = _bits(data, 32, data.draw(st.integers(0, min(32, 64 // max(nsat, 1)))))
        else:
            def one():
                if isinstance(kind, Octets):
                    n = kind.length.eval(env)
                    return data.draw(st.binary(min_size=n, max_size=n))
                return data.draw(_int_value(kind, kind.width.eval(env)))
            n = None if kind.count is None else kind.count.eval(env)
            values[name] = one() if n is None else tuple(one() for _ in range(n))
    return cls(**values)


@settings(max_examples=300, derandomize=True, deadline=None)
@given(st.data())
def test_generated_messages_round_trip(data):
    number = data.draw(st.sampled_from(NUMBERS))
    message = draw_message(data, rtcm3.MESSAGES[number], number)
    raw = rtcm3.encode(message)
    frame = rtcm3.parse(raw)
    assert isinstance(frame, rtcm3.Frame) and frame.length == len(raw)
    assert bits_of(message) == spec_bits(message)
    assert len(frame.payload) == math.ceil(spec_bits(message) / 8)
    assert rtcm3.decode(frame) == message
    assert rtcm3.encode(rtcm3.decode(frame)) == raw


# --- spec example and corpus ------------------------------------------------------------

def test_section_4_2_example():
    raw = bytes.fromhex("D3 00 13 3E D7 D3 02 02 98 0E DE EF 34 B4 BD 62"
                        "AC 09 41 98 6F 33 36 0B 98")
    m = rtcm3.decode(rtcm3.parse(raw))
    # "Reference Station Id = 2003; GPS Service supported, but not GLONASS or
    # Galileo; ARP ECEF-X = 1114104.5999 meters, ECEF-Y = -4850729.7108,
    # ECEF-Z = 3975521.4643" (DF025 to DF027 count 0.0001 m).
    assert (m.number, m.station, m.gps, m.glonass, m.galileo) == (1005, 2003, 1, 0, 0)
    assert (m.x, m.y, m.z) == (11141045999, -48507297108, 39755214643)
    assert rtcm3.encode(m) == raw


def test_1006_is_1005_with_the_antenna_height():
    # Table 3.5-7 is Table 3.5-6 followed by DF028 (uint16, 0.0001 m). RTKLIB
    # encoded each synthetic station as both; heights 0 and 6.5535 m are the
    # ends of DF028's range.
    station = load("rtklib-station")
    assert [number_of(r) for r, _ in station] == [1006, 1005] * (len(station) // 2)
    heights = set()
    for (raw6, _), (raw5, _) in zip(station[::2], station[1::2]):
        m6, m5 = rtcm3.decode(rtcm3.parse(raw6)), rtcm3.decode(rtcm3.parse(raw5))
        assert isinstance(m6, rtcm3.Msg1006)
        fields = {f: getattr(m5, f) for f in rtcm3.Msg1005.__dataclass_fields__ if f != "number"}
        assert {f: getattr(m6, f) for f in fields} == fields
        heights.add(m6.height)
    assert {0, 65535} <= heights and len(heights) >= 3


@pytest.mark.parametrize("number", [1005, 1006, 1007, 1008, 1033, 1230])
def test_station_messages_encode_from_their_fields(number):
    # Built field by field (not from a decoded message), encoded, and read
    # back by pyrtcm, which agrees on every DF; then the corpus frames.
    for raw, note in [(r, n) for r, n in CORPUS if number_of(r) == number][:4]:
        decoded = rtcm3.decode(rtcm3.parse(raw))
        cls = rtcm3.MESSAGES[number]
        built = cls(**{f: getattr(decoded, f) for f in cls.__dataclass_fields__
                       if f != "extension"})
        assert rtcm3.encode(built) == raw, note
        _agree_with_pyrtcm([(rtcm3.encode(built), note)])


# --- antenna descriptors: 1007, 1008, and 1033 beside them -------------------------------
#
# Tables 3.5-8 (1007), 3.5-9 (1008) and 3.5-36 (1033), transcribed again from
# RTCM 10403.3, row by row: (DF, data type, field name here). "char8(DFnnn)"
# is a string whose length is the value of counter DFnnn (Table 3.4-1, DF029:
# "the number of characters (bytes) to follow"). Table 3.5-36 prints char(N)
# where the others print char8(N); Table 3.4-1 gives DF030 to DF232 as char8.

TABLE_3_5_8 = [("DF002", "uint12", "number"), ("DF003", "uint12", "station"),
               ("DF029", "uint8", "antenna_count"), ("DF030", "char8(DF029)", "antenna"),
               ("DF031", "uint8", "antenna_setup")]
TABLE_3_5_9 = TABLE_3_5_8 + [("DF032", "uint8", "antenna_serial_count"),
                             ("DF033", "char8(DF032)", "antenna_serial")]
TABLE_3_5_36 = TABLE_3_5_9 + [("DF227", "uint8", "receiver_count"),
                              ("DF228", "char8(DF227)", "receiver"),
                              ("DF229", "uint8", "firmware_count"),
                              ("DF230", "char8(DF229)", "firmware"),
                              ("DF231", "uint8", "receiver_serial_count"),
                              ("DF232", "char8(DF231)", "receiver_serial")]
ANTENNA_TABLES = {1007: TABLE_3_5_8, 1008: TABLE_3_5_9, 1033: TABLE_3_5_36}
# The counter of each string, by field name.
COUNTERS = {"antenna": "antenna_count", "antenna_serial": "antenna_serial_count",
            "receiver": "receiver_count", "firmware": "firmware_count",
            "receiver_serial": "receiver_serial_count"}


def table_bits(number: int, values: dict) -> str:
    """The message as a string of '0' and '1', written from the transcribed table alone."""
    out = []
    for df, dtype, name in ANTENNA_TABLES[number]:
        value = values[name]
        if dtype.startswith("uint"):
            width = int(dtype[4:])
            assert 0 <= value < 1 << width, (df, value)
            out.append(format(value, f"0{width}b"))
        else:
            counter = next(n for d, _, n in ANTENNA_TABLES[number] if d == dtype[6:-1])
            assert len(value) == values[counter], df
            out.extend(format(byte, "08b") for byte in value)
    return "".join(out)


def antenna_message(number: int, station: int = 0, setup: int = 0, **strings: bytes):
    """A 1007, 1008 or 1033 built from its fields; counters from the strings' lengths."""
    names = [name for _, _, name in ANTENNA_TABLES[number]]
    values = {"number": number, "station": station, "antenna_setup": setup}
    for name in names:
        if name in COUNTERS:
            values[name] = strings.get(name, b"")
            values[COUNTERS[name]] = len(values[name])
    return rtcm3.MESSAGES[number](**values)


def as_bits(data: bytes) -> str:
    return "".join(format(byte, "08b") for byte in data)


# Every byte value, 0x00 included, in strings of the longest length the
# tables note (31), so that each value is sent in each string field.
EVERY_BYTE = [bytes(range(i, min(i + 31, 256))) for i in range(0, 256, 31)]
ANTENNA_CASES = [
    # Counters 0 (section 3.5.12.5: "unknown ... the length of the counters
    # should be set to zero"), lowest station and setup ID.
    dict(station=0, setup=0),
    # Counters 31, the top of DF029 and DF032's range; highest IDs.
    dict(station=4095, setup=255, antenna=b"A" * 31, antenna_serial=b"9" * 31),
    # An IGS-style 20-character antenna descriptor (section 3.5.4) and a serial number.
    dict(station=2003, setup=1, antenna=b"TRM59800.00     SCIS", antenna_serial=b"5000112345"),
    *(dict(station=k, setup=k, antenna=s, antenna_serial=EVERY_BYTE[-1 - k])
      for k, s in enumerate(EVERY_BYTE)),
]


@pytest.mark.parametrize("number", [1007, 1008, 1033])
def test_antenna_tables_are_the_spec_tables(number):
    # The compiled table, row for row: DF tag, kind and width, field name.
    kinds = {"uint": U, "char8": Octets}
    rows = layout(rtcm3.MESSAGES[number]).rows
    assert [row.name for row in rows] == [n for _, _, n in ANTENNA_TABLES[number]] + ["extension"]
    assert isinstance(rows[-1].kind, Rest) and rows[-1].kind.tag is None
    for row, (df, dtype, _) in zip(rows, ANTENNA_TABLES[number]):
        assert row.kind.tag == df and row.kind.when is None and row.kind.count is None
        kind = next(k for prefix, k in kinds.items() if dtype.startswith(prefix))
        assert type(row.kind) is kind, df
        if kind is U:
            assert row.kind.width.value == int(dtype[4:]), df
        else:
            counter = next(n for d, _, n in ANTENNA_TABLES[number] if d == dtype[6:-1])
            assert row.kind.length.eval({counter: 23}.__getitem__) == 23, df


@pytest.mark.parametrize("number", [1007, 1008, 1033])
@pytest.mark.parametrize("case", ANTENNA_CASES, ids=range(len(ANTENNA_CASES)))
def test_antenna_messages_built_from_fields_give_the_table_bits(number, case):
    strings = {k: v for k, v in case.items() if k in COUNTERS}
    if number == 1033:      # the receiver strings too, from the same bytes
        strings |= {"receiver": strings.get("antenna", b""), "firmware": b"1.0",
                    "receiver_serial": strings.get("antenna_serial", b"")}
    m = antenna_message(number, case["station"], case["setup"], **strings)
    raw = rtcm3.encode(m)
    expected = table_bits(number, {f: getattr(m, f) for f in m.__dataclass_fields__})
    assert len(expected) == spec_bits(m) and len(expected) % 8 == 0     # no fill bits
    assert as_bits(raw[3:-3]) == expected
    assert raw == rtcm3.encode_frame(int(expected, 2).to_bytes(len(expected) // 8, "big"))
    back = rtcm3.decode(rtcm3.parse(raw), strict=True)
    assert back == m and back.extension is None
    assert rtcm3.encode(back) == raw
    _agree_with_pyrtcm([(raw, f"{number} {case}")])


@pytest.mark.parametrize("number", [1007, 1008])
def test_antenna_fields_at_the_ends_of_their_ranges(number):
    base = antenna_message(number, 1, 1, antenna=b"ADVNULLANTENNA", antenna_serial=b"S1")
    ints = [(name, int(dtype[4:])) for _, dtype, name in ANTENNA_TABLES[number]
            if dtype.startswith("uint") and name != "number" and name not in COUNTERS.values()]
    assert [n for n, _ in ints] == ["station", "antenna_setup"]
    for name, width in ints:                  # DF003 0-4095, DF031 0-255
        for value in (0, (1 << width) - 1):
            m = replace(base, **{name: value})
            assert rtcm3.decode(rtcm3.parse(rtcm3.encode(m)), strict=True) == m
        for value in (-1, 1 << width):
            with pytest.raises(rtcm3.FieldError):
                rtcm3.encode(replace(base, **{name: value}))
    # DF002 is the message's own number; another is another table.
    for other in (1005, 1007, 1008, 1033):
        if other != number:
            with pytest.raises(TypeError):
                rtcm3.encode(replace(base, number=other))
    # Counters (DF029, DF032): 0 and 31 are the ends of Table 3.4-1's range.
    # 32 to 255 are outside it but inside the uint8; as for 1033 they are
    # kept (_station: ranges are not enforced), so they round-trip. -1 and
    # 256 do not fit the uint8 and are refused.
    strings = [s for s in COUNTERS if s in rtcm3.MESSAGES[number].__dataclass_fields__]
    for string in strings:
        counter = COUNTERS[string]
        for n in (0, 31, 32, 255):
            m = replace(base, **{string: bytes(range(n)), counter: n})
            raw = rtcm3.encode(m)
            assert len(raw) - 6 == spec_bits(m) // 8
            assert rtcm3.decode(rtcm3.parse(raw), strict=True) == m
        for n in (-1, 256):
            with pytest.raises(rtcm3.FieldError, match=counter):
                rtcm3.encode(replace(base, **{string: bytes(max(n, 0)), counter: n}))
        # A string must have its counter's length, as bytes.
        n = getattr(base, counter)
        for bad in (b"x" * (n - 1), b"x" * (n + 1), "x" * n, bytearray(b"x" * n)):
            with pytest.raises(rtcm3.FieldError, match=string):
                rtcm3.encode(replace(base, **{string: bad}))


def _antenna_frames() -> list[tuple[bytes, str]]:
    built = [(rtcm3.encode(antenna_message(number, c["station"], c["setup"],
                                           **{k: v for k, v in c.items() if k in COUNTERS})),
              f"built {number} {i}")
             for number in (1007, 1008) for i, c in enumerate(ANTENNA_CASES)]
    return built + [(r, n) for r, n in load("rtklib-antenna") if number_of(r) in (1007, 1008)]


def test_truncated_antenna_messages_are_refused():
    frames = _antenna_frames()
    assert {number_of(r) for r, _ in frames} == {1007, 1008}
    for raw, note in frames:
        payload = raw[3:-3]
        for cut in range(2, len(payload)):
            with pytest.raises(rtcm3.FieldError):
                rtcm3.decode(rtcm3.parse(rtcm3.encode_frame(payload[:cut])), strict=True)
            with pytest.raises(rtcm3.FieldError):
                rtcm3.decode(rtcm3.parse(rtcm3.encode_frame(payload[:cut])))
        # The last counter (DF029 of 1007 at byte 3; DF032 of 1008, after the
        # descriptor and setup ID), one more than the characters sent, runs
        # past the end.
        at = 3 if number_of(raw) == 1007 else 5 + payload[3]
        n = payload[at]
        if n < 255:
            longer = payload[:at] + bytes([n + 1]) + payload[at + 1:]
            with pytest.raises(rtcm3.FieldError):
                rtcm3.decode(rtcm3.parse(rtcm3.encode_frame(longer)))
        # One less leaves the last byte over: kept as an extension, refused
        # when strict, and written back.
        if n > 0:
            shorter = rtcm3.encode_frame(payload[:at] + bytes([n - 1]) + payload[at + 1:])
            m = rtcm3.decode(rtcm3.parse(shorter))
            assert m.extension == Extension(8, payload[-1]), note
            assert rtcm3.encode(m) == shorter
            with pytest.raises(rtcm3.FieldError, match="1 bytes left over"):
                rtcm3.decode(rtcm3.parse(shorter), strict=True)


# RTKLIB's names (its sta_t) for the fields of these tables.
RTKLIB_NAMES = {"staid": "station", "antsetup": "antenna_setup", "antdes": "antenna",
                "antsno": "antenna_serial", "rectype": "receiver", "recver": "firmware",
                "recsno": "receiver_serial"}


def test_rtklib_antenna_frames_agree_with_its_encoder_and_decoder():
    # Field for field: what RTKLIB's encoder was given, what its decoder read
    # back from each frame, and what decode reads here. Strings are stored in
    # the JSON as the latin-1 text of their bytes.
    frames = load("rtklib-antenna")
    readings = json.loads((DATA / "rtklib-antenna-decoded.json").read_text())["frames"]
    assert len(frames) == len(readings) == 42
    counts, characters = defaultdict(set), set()
    for (raw, note), reading in zip(frames, readings):
        m = rtcm3.decode(rtcm3.parse(raw), strict=True)
        assert m.number == reading["number"] == number_of(raw) and reading["ret"] == 5, note
        for side in ("given", "read"):
            theirs = {RTKLIB_NAMES[k]: v.encode("latin-1") if isinstance(v, str) else v
                      for k, v in reading[side].items()}
            fields = [n for n in m.__dataclass_fields__ if n in RTKLIB_NAMES.values()]
            assert sorted(theirs) == sorted(fields), (note, side)
            assert {f: getattr(m, f) for f in fields} == theirs, (note, side)
        for string, counter in COUNTERS.items():
            if string in m.__dataclass_fields__:
                assert getattr(m, counter) == len(getattr(m, string))
                counts[m.number].add(getattr(m, counter))
                characters |= set(getattr(m, string))
        assert rtcm3.encode(m) == raw
    # Empty and longest strings, and some between, in each message.
    for number in (1007, 1008, 1033):
        assert {0, 20, 31} <= counts[number] and len(counts[number]) >= 10
    # Characters from 0x01 to 0xFF, most of them sent. RTKLIB's strings end
    # at 0x00, so it cannot send 0x00; the built frames above do.
    assert (min(characters), max(characters)) == (0x01, 0xFF) and len(characters) > 200


def test_1007_is_1008_without_the_serial_number_and_1008_the_head_of_1033():
    # Section 3.5.4: Table 3.5-9 "provides the same information, plus the
    # antenna serial number"; section 3.5.12.5: 1033 "is an elaboration of
    # Message Type 1008". RTKLIB encoded each synthetic station as all three.
    def fields(m, names):
        return {n: getattr(m, n) for n in names}

    names = {number: [n for _, _, n in ANTENNA_TABLES[number] if n != "number"]
             for number in ANTENNA_TABLES}
    assert names[1008][:len(names[1007])] == names[1007]
    assert names[1033][:len(names[1008])] == names[1008]
    frames = load("rtklib-antenna")
    assert [number_of(r) for r, _ in frames] == [1007, 1008, 1033] * (len(frames) // 3)
    for i in range(0, len(frames), 3):
        m7, m8, m33 = (rtcm3.decode(rtcm3.parse(raw)) for raw, _ in frames[i:i + 3])
        assert fields(m8, names[1007]) == fields(m7, names[1007])
        assert fields(m33, names[1008]) == fields(m8, names[1008])
        # On the wire: after DF002, 1007's bits begin 1008's, whose bits
        # (after DF002) begin 1033's; 1007 ends with DF031, where 1008 goes on
        # with DF032.
        b7, b8, b33 = (as_bits(raw[3:-3]) for raw, _ in frames[i:i + 3])
        assert b8[12:len(b7)] == b7[12:] and b33[12:len(b8)] == b8[12:]
        assert rtcm3.Msg1007(1007, *[getattr(m8, n) for n in names[1007]]) == m7
        assert rtcm3.Msg1008(1008, *[getattr(m33, n) for n in names[1008]]) == m8


def test_char8_readings_on_public_data():
    # _station: AMBIGUOUS, which characters a char8 string holds: (a) ISO
    # 8859-1 graphic characters (Table 3.3-1), (b) printable ASCII (section
    # 3.5.4 "ASCII descriptor", DF030 and DF033 "Alphanumeric characters").
    # The public 1033 frames hold printable ASCII only, inside both readings;
    # bytes outside both (0x00, controls, 0x80 to 0x9F) are kept as sent
    # (test_antenna_messages_built_from_fields_give_the_table_bits).
    ascii_ = set(range(0x20, 0x7F))
    iso_8859_1 = ascii_ | set(range(0xA0, 0x100))
    seen = b""
    for raw, note in PUBLIC:
        if number_of(raw) in (1007, 1008, 1033):
            m = rtcm3.decode(rtcm3.parse(raw), strict=True)
            for string in COUNTERS:
                value = getattr(m, string)
                assert set(value) <= ascii_ <= iso_8859_1, note
                seen += value
    assert seen      # "TRIMBLE NETR9": a space too, so "alphanumeric" is not literal


def test_corpus_covers_every_message():
    for name, frames in (("public", PUBLIC), ("rtklib", RTKLIB)):
        assert frames, name
    assert {number_of(raw) for raw, _ in RTKLIB} == set(NUMBERS)
    assert {number_of(raw) for raw, _ in PUBLIC} >= {1005, 1019, 1020, 1033,
                                                     1077, 1087, 1117, 1127}


@pytest.mark.parametrize(("raw", "note"), CORPUS, ids=[f"{i}:{n}" for i, (_, n) in enumerate(CORPUS)])
def test_corpus_round_trip(raw, note):
    frame = rtcm3.parse(raw)
    assert isinstance(frame, rtcm3.Frame) and frame.length == len(raw)
    message = rtcm3.decode(frame)
    assert type(message) is rtcm3.MESSAGES[number_of(raw)]
    assert bits_of(message) == spec_bits(message)
    assert rtcm3.encode(message) == raw


def test_msm_masks_select_the_data():
    # Section 3.5.16.3.6 and .7: satellite data for each set bit of DF394,
    # cell data for each set bit of DF396; which rows a level has is Table
    # 3.5-72.
    sat_rows = {"rough_ms": {4, 5, 6, 7}, "extended_info": {5, 7}, "rough_mod": set(range(1, 8)),
                "rough_rate": {5, 7}}
    cell_rows = {"fine_range": {1, 3, 4, 5, 6, 7}, "fine_phase": {2, 3, 4, 5, 6, 7},
                 "lock": {2, 3, 4, 5, 6, 7}, "half_cycle": {2, 3, 4, 5, 6, 7},
                 "cnr": {4, 5, 6, 7}, "fine_rate": {5, 7}}
    levels = set()
    for raw, _ in CORPUS:
        m = rtcm3.decode(rtcm3.parse(raw))
        if not isinstance(m, rtcm3.Msm):
            continue
        level = m.number % 10
        levels.add(level)
        nsat = m.sat_mask.bit_count()
        assert m.cell_mask < 1 << (nsat * m.sig_mask.bit_count()) or nsat == 0
        for rows, n in ((sat_rows, nsat), (cell_rows, m.cell_mask.bit_count())):
            for name, present in rows.items():
                value = getattr(m, name)
                assert (value is None) == (level not in present), (m.number, name)
                assert value is None or len(value) == n, (m.number, name)
        glonass = m.number in GLONASS_MSM
        assert (m.epoch is None) == glonass
        assert (m.glonass_day is None) == (m.glonass_epoch is None) == (not glonass)
    assert levels == set(range(1, 8))


def test_high_resolution_rows_are_wider():
    # MSM6 and MSM7 carry DF405 to DF408 (int20, int24, uint10, uint10) where
    # MSM1 to MSM5 carry DF400 to DF403 (int15, int22, uint4, uint6).
    def widths(number):
        env = {"number": number}.__getitem__
        return {row.name: row.kind.width.eval(env) for row in layout(rtcm3.Msm).rows
                if row.name in ("fine_range", "fine_phase", "lock", "cnr")}
    for system in (107, 108, 109, 110, 111, 112):
        for level in range(1, 8):
            high = level >= 6
            assert widths(10 * system + level) == {
                "fine_range": 20 if high else 15, "fine_phase": 24 if high else 22,
                "lock": 10 if high else 4, "cnr": 10 if high else 6}


# --- errors -------------------------------------------------------------------------------

def test_unsupported_messages():
    # 1041 (NavIC) and 1043 (SBAS) ephemerides and NavIC MSM (1131 on) are not
    # in RTCM 10403.3 as staged.
    for payload in (b"", b"\x3f", *((n << 4).to_bytes(2, "big") + bytes(60)
                                     for n in (1041, 1043, 1070, 1078, 1131, 1137))):
        with pytest.raises(rtcm3.Unsupported):
            rtcm3.decode(rtcm3.parse(rtcm3.encode_frame(payload)))


@pytest.mark.parametrize("number", NUMBERS)
def test_short_message_is_refused(number):
    raw = next(r for r, _ in CORPUS if number_of(r) == number)
    with pytest.raises(rtcm3.FieldError):
        rtcm3.decode(rtcm3.parse(rtcm3.encode_frame(raw[3:-4])))


@pytest.mark.parametrize("number", NUMBERS)
def test_data_after_the_table_is_kept(number):
    # Section 3.5.16.3.4 (MSM; and section 3.5.17 for 1230): a decoder "shall
    # skip (ignore) any unexpected data at the end of the message", "as
    # normal". decode keeps it in ``extension`` and encode writes it back;
    # strict=True refuses it.
    raw = next(r for r, _ in CORPUS if number_of(r) == number)
    plain = rtcm3.decode(rtcm3.parse(raw))
    table_bits = bits_of(replace(plain, extension=None))
    fill = -table_bits % 8
    for tail in (b"\x00", b"\xa5\x5a\x01"):
        longer = rtcm3.encode_frame(raw[3:-3] + tail)
        message = rtcm3.decode(rtcm3.parse(longer))
        assert message.extension == Extension(fill + 8 * len(tail), int.from_bytes(tail, "big"))
        assert replace(message, extension=None) == plain
        assert rtcm3.encode(message) == longer
        with pytest.raises(rtcm3.FieldError, match=f"{len(tail)} bytes left over"):
            rtcm3.decode(rtcm3.parse(longer), strict=True)
    assert rtcm3.decode(rtcm3.parse(raw), strict=True) == plain


def test_nonzero_fill_bits_are_kept():
    raw = next(r for r, _ in CORPUS if number_of(r) == 1042)   # 511 bits: one fill bit
    payload = bytearray(raw[3:-3])
    payload[-1] |= 1
    framed = rtcm3.encode_frame(bytes(payload))
    message = rtcm3.decode(rtcm3.parse(framed))
    assert message.extension == Extension(1, 1)
    assert rtcm3.encode(message) == framed
    with pytest.raises(rtcm3.FieldError, match="fill"):
        rtcm3.decode(rtcm3.parse(framed), strict=True)


def test_negative_zero_in_1020_round_trips():
    # Table 3.5-22 sends the GLONASS fields as intS "See GLONASS ICD"; the ICD
    # (section 4.4, "the MSB is the sign bit") does not exclude a negative
    # zero, so a receiver copying string bits may send one. It decodes, equal
    # to 0, and re-encodes with its sign bit; 0.1.0 refused the message.
    raw = next(r for r, _ in CORPUS if number_of(r) == 1020)
    m = rtcm3.decode(rtcm3.parse(raw))
    negative = replace(m, x_ddot=NEGATIVE_ZERO, tau=NEGATIVE_ZERO, delta_tau=NEGATIVE_ZERO)
    positive = replace(m, x_ddot=0, tau=0, delta_tau=0)
    wire = rtcm3.encode(negative)
    assert wire != rtcm3.encode(positive)
    back = rtcm3.decode(rtcm3.parse(wire))
    assert back == positive and back.tau is NEGATIVE_ZERO and back.x_ddot is NEGATIVE_ZERO
    assert rtcm3.encode(back) == wire


def test_encode_checks_the_number():
    # One MSM table serves every MSM number; a number without that table is refused.
    m = rtcm3.decode(rtcm3.parse(next(r for r, _ in CORPUS if number_of(r) == 1074)))
    for number in (1094, 1104, 1114):
        assert rtcm3.decode(rtcm3.parse(rtcm3.encode(replace(m, number=number)))).number == number
    for bad in (replace(m, number=1078), replace(m, number=1131), replace(m, number=1019)):
        with pytest.raises(TypeError):
            rtcm3.encode(bad)
    with pytest.raises(TypeError):
        rtcm3.encode(object())


def test_msm_level_must_match_the_rows():
    # An MSM4 message relabelled MSM7 lacks the MSM7 rows, and the reverse has
    # rows MSM4 does not; both are refused, not padded or dropped.
    m4 = rtcm3.decode(rtcm3.parse(next(r for r, _ in CORPUS if number_of(r) == 1074)))
    m7 = rtcm3.decode(rtcm3.parse(next(r for r, _ in CORPUS if number_of(r) == 1077)))
    for bad in (replace(m4, number=1077), replace(m7, number=1074),
                replace(m4, number=1084), replace(m7, number=1087)):
        with pytest.raises(BitError):
            rtcm3.encode(bad)


def test_cell_mask_is_at_most_64_bits():
    m = rtcm3.decode(rtcm3.parse(next(r for r, _ in CORPUS if number_of(r) == 1094)))
    wide = replace(m, sat_mask=(1 << 64) - 1, sig_mask=0b11, cell_mask=0, rough_ms=(0,) * 64,
                   rough_mod=(0,) * 64, fine_range=(), fine_phase=(), lock=(), half_cycle=(),
                   cnr=())
    with pytest.raises(BitError, match="width 128"):
        rtcm3.encode(wide)


# --- cross-check with pyrtcm ------------------------------------------------------------------

EPOCH_TAG = {107: "DF004", 109: "DF248", 110: "DF004", 111: "DF428", 112: "DF427"}


def _ours(m) -> dict[str, object]:
    """Our fields keyed the way pyrtcm names them: DFnnn, DFnnn_01... for repeated rows."""
    out: dict[str, object] = {}
    for row in layout(type(m)).rows:
        tag, value = row.kind.tag, getattr(m, row.name)
        if tag is None or value is None:
            continue
        if row.name == "epoch":              # by system (_msm docstring)
            tag = EPOCH_TAG[m.number // 10]
        elif "/" in tag:                     # DF400/DF405 etc.: by MSM level
            tag = tag.split("/")[m.number % 10 >= 6]
        if row.name == "extended_info" and m.number not in GLONASS_MSM:
            # Reserved for every system but GLONASS; pyrtcm reports it only as DF419.
            continue
        if tag == "DF001":
            tag = f"DF001_{row.kind.width.value}"
        if isinstance(value, tuple):
            for i, v in enumerate(value, 1):
                out[f"{tag}_{i:02d}"] = v
        elif isinstance(value, bytes):
            for i, v in enumerate(value, 1):
                out[f"{tag}_{i:02d}"] = bytes([v])
        else:
            out[tag] = value
    return out


def _theirs(raw: bytes) -> dict[str, object]:
    parsed = pyrtcm.RTCMReader.parse(raw)
    found = {k: v for k, v in vars(parsed).items() if k.startswith("DF")}
    # pyrtcm reports a bit(n) mask such as DF422 bit by bit, DF422_1 first.
    for base in {k.rsplit("_", 1)[0] for k in found if k.count("_") == 1
                 and len(k.rsplit("_", 1)[1]) == 1 and not k.startswith("DF001_")}:
        bits = [found.pop(f"{base}_{i}") for i in range(1, 99) if f"{base}_{i}" in found]
        found[base] = int("".join(str(b) for b in bits), 2)
    return found


# MSM2 of every system: pyrtcm 1.2.1 raises on its own MSM2 definition.
PYRTCM_CANNOT = {10 * system + 2 for system in range(107, 113)}


def test_pyrtcm_cannot_parse_msm2():
    # If a later pyrtcm parses MSM2, take it into the cross-check.
    raw = next(r for r, _ in CORPUS if number_of(r) == 1072)
    with pytest.raises(pyrtcm.RTCMTypeError):
        pyrtcm.RTCMReader.parse(raw)


def test_pyrtcm_agrees():
    ratios = _agree_with_pyrtcm(CORPUS)
    unscaled = {k for k, seen in ratios.items() if seen == {1.0}}
    assert {"DF002", "DF003", "DF009", "DF038", "DF252", "DF488", "DF394", "DF396",
            "DF402", "DF403", "DF422", "DF429", "DF419", "DF407"} <= unscaled
    # Every DF of every table was compared.
    assert {"DF399", "DF404", "DF405", "DF406", "DF408", "DF428", "DF457"} <= set(ratios)


def _agree_with_pyrtcm(frames: list[tuple[bytes, str]]) -> dict[str, set[float]]:
    # pyrtcm scales many fields to physical units (and some integers, such
    # as DF081 in seconds). So for every numeric DF the ratio of its value
    # to our integer must be one constant across the whole corpus (a wrong
    # width, offset, sign or order breaks that), zero must stay zero, and
    # the unscaled fields must be equal.
    ratios: dict[str, set[float]] = defaultdict(set)
    for raw, note in frames:
        if number_of(raw) in PYRTCM_CANNOT:
            continue
        ours = _ours(rtcm3.decode(rtcm3.parse(raw)))
        theirs = _theirs(raw)
        if number_of(raw) == 1020:
            # Our 1020 keeps the untagged reserved row; pyrtcm names it DF001_7.
            theirs.pop("DF001_7")
        assert sorted(ours) == sorted(theirs), note
        for key, mine in ours.items():
            other = theirs[key]
            if isinstance(mine, bytes):
                assert other == mine.decode("latin-1"), (note, key)
            elif mine == 0:
                assert other == 0, (note, key)
            else:
                ratios[key.split("_")[0]].add(other / mine)
    for key, seen in ratios.items():
        assert max(seen) - min(seen) <= 1e-9 * max(abs(r) for r in seen), (key, sorted(seen)[:5])
    return ratios


# --- private captures ------------------------------------------------------------------------
#
# build/private/ (gitignored, never committed) may hold recorded RTCM
# streams (*.bin). When it is present, every frame of a supported message
# must decode, re-encode to its own bytes and agree with pyrtcm. Nothing
# from these files is copied into the repository.

PRIVATE = Path(__file__).resolve().parents[3] / "build" / "private"
private = pytest.mark.skipif(not PRIVATE.is_dir(),
                             reason="private captures (build/private/) are absent")


@private
def test_private_captures_round_trip_and_agree_with_pyrtcm():
    frames, failures, unsupported = [], [], set()
    for path in sorted(PRIVATE.glob("*.bin")):
        stream = path.read_bytes()
        for frame in rtcm3.scan(stream):
            raw = stream[frame.offset:frame.offset + frame.length]
            note = f"{path.name} at {frame.offset}"
            try:
                message = rtcm3.decode(frame)
            except rtcm3.Unsupported:
                unsupported.add(rtcm3.message_number(frame))
                continue
            except rtcm3.Error as exc:
                failures.append((note, str(exc)))
                continue
            if rtcm3.encode(message) != raw:
                failures.append((note, "round trip"))
            frames.append((raw, note))
    assert not failures, failures[:10]
    assert frames
    # NavIC (1041) and SBAS (1043) ephemerides have no table.
    assert unsupported <= {1041, 1043}
    _agree_with_pyrtcm(frames)


@private
def test_private_antenna_descriptors():
    # Every 1007 and 1008 frame of the local captures, in any directory of
    # build/private/, decodes, round-trips and agrees with pyrtcm.
    frames = []
    for path in sorted(PRIVATE.rglob("*.bin")):
        stream = path.read_bytes()
        for frame in rtcm3.scan(stream):
            if rtcm3.message_number(frame) in (1007, 1008):
                frames.append((stream[frame.offset:frame.offset + frame.length],
                               f"{path.name} at {frame.offset}"))
    if not frames:
        pytest.skip("no 1007 or 1008 frame in the private captures (build/private/)")
    for raw, note in frames:
        m = rtcm3.decode(rtcm3.parse(raw))
        assert rtcm3.encode(m) == raw, note
        assert bits_of(replace(m, extension=None)) == spec_bits(m), note
    _agree_with_pyrtcm(frames)


# build/private/live/ may hold broadcast-ephemeris streams (*_eph_*.bin).
# Every 1044 frame must decode and round-trip, and a sample of each message
# number agree with pyrtcm; 1041 and 1043 are the only numbers without a
# table.
LIVE = PRIVATE / "live"


@pytest.mark.skipif(not LIVE.is_dir(), reason="private captures (build/private/live/) are absent")
def test_private_live_ephemerides():
    sample: dict[int, list[tuple[bytes, str]]] = defaultdict(list)
    failures, unsupported = [], set()
    for path in sorted(LIVE.glob("*_eph_*.bin")):
        stream = path.read_bytes()
        for frame in rtcm3.scan(stream):
            raw = stream[frame.offset:frame.offset + frame.length]
            number = rtcm3.message_number(frame)
            if number not in rtcm3.MESSAGES:
                unsupported.add(number)
                continue
            if number != 1044 and len(sample[number]) >= 100:
                continue
            note = f"{path.name} at {frame.offset}"
            try:
                if rtcm3.encode(rtcm3.decode(frame)) != raw:
                    failures.append((note, "round trip"))
            except rtcm3.Error as exc:
                failures.append((note, str(exc)))
            if len(sample[number]) < 100:
                sample[number].append((raw, note))
    assert not failures, failures[:10]
    assert sample and unsupported <= {1041, 1043}
    _agree_with_pyrtcm([f for frames in sample.values() for f in frames])
