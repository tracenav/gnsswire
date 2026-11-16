"""IGS SSR (RTCM message 4076) against IGS SSR v1.00, RTKLIB and pyrtcm.

- Tables: every sub-type is built from fields, encoded, compared bit for bit
  with the rows of section 8's tables as transcribed here (``SPEC``), and
  decoded back; lengths follow Tables 4 and 6 ("No. of Bytes").
- Boundary and invalid values: each row at the ends of its type's range
  round-trips and one beyond is refused; reserved sub-types raise
  ``Unsupported``; short messages raise ``FieldError``.
- RTKLIB (pyrtklib 0.2.7, not a dependency; data/rtklib-igs.hex and
  data/rtklib-igs-decoded.json, made by make_data/gen_rtklib_igs.py):
  RTKLIB encodes sub-types 21 to 27, 41 to 47, 61 to 67, 81 to 87, 101 to
  107 and 121 to 127 (not IM201); every frame round-trips here, and every
  value its decoder reads equals ours scaled by Table 7, except where
  RTKLIB departs from the specification (the signal identifiers Table 7
  reserves, and sub-type 126, below).
- pyrtcm 1.2.1 (a dev dependency) decodes every sub-type, IM201 included;
  every IDF it reports equals ours times Table 7's resolution.
"""

import json
import math
import warnings
from collections import Counter, defaultdict
from dataclasses import fields, replace
from pathlib import Path

import pyrtcm
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from gnsswire import rtcm3
from gnsswire.bits import Extension, Group, S, U, layout

DATA = Path(__file__).resolve().parent / "data"


def load_hex(name: str) -> list[tuple[bytes, str]]:
    out = []
    for line in (DATA / name).read_text().splitlines():
        if line and not line.startswith("#"):
            hexpart, _, note = line.partition("#")
            out.append((bytes.fromhex(hexpart.strip()), note.strip()))
    return out


RTKLIB = load_hex("rtklib-igs.hex")
RTKLIB_READ = json.loads((DATA / "rtklib-igs-decoded.json").read_text())["frames"]
SUBTYPES = sorted(rtcm3.IGS_MESSAGES)


# --- the tables of section 8, transcribed for the tests --------------------------------
#
# (row, bits, signed), in the order of the spec's tables. The header rows
# common to every table (Tables 8, 10, 12, 14, 16, 19, 22, 24).
HEAD = [("number", 12, 0), ("version", 3, 0), ("subtype", 8, 0), ("epoch", 20, 0),
        ("interval", 4, 0), ("multiple", 1, 0), ("iod_ssr", 4, 0), ("provider", 16, 0),
        ("solution", 4, 0)]
ORBIT = [("satellite", 6, 0), ("iod", 8, 0), ("radial", 22, 1), ("along", 20, 1),
         ("cross", 20, 1), ("dot_radial", 21, 1), ("dot_along", 19, 1), ("dot_cross", 19, 1)]
CLOCK = [("c0", 22, 1), ("c1", 21, 1), ("c2", 27, 1)]
SPEC = {   # class: (header after HEAD, satellite part, bias part)
    rtcm3.IgsOrbit: ([("regional", 1, 0), ("satellite_count", 6, 0)], ORBIT, None),   # 8, 9
    rtcm3.IgsClock: ([("satellite_count", 6, 0)], [("satellite", 6, 0)] + CLOCK, None),  # 10, 11
    rtcm3.IgsCombined: ([("regional", 1, 0), ("satellite_count", 6, 0)], ORBIT + CLOCK,
                        None),                                                          # 12, 13
    rtcm3.IgsHighRateClock: ([("satellite_count", 6, 0)],
                             [("satellite", 6, 0), ("high_rate_clock", 22, 1)], None),  # 14, 15
    rtcm3.IgsCodeBias: ([("satellite_count", 6, 0)], [("satellite", 6, 0), ("bias_count", 5, 0)],
                        [("signal", 5, 0), ("bias", 14, 1)]),                         # 16 to 18
    rtcm3.IgsPhaseBias: ([("dispersive", 1, 0), ("mw", 1, 0), ("satellite_count", 6, 0)],
                         [("satellite", 6, 0), ("bias_count", 5, 0), ("yaw", 9, 0),
                          ("yaw_rate", 8, 1)],
                         [("signal", 5, 0), ("integer", 1, 0), ("wide_lane", 2, 0),
                          ("discontinuity", 4, 0), ("bias", 20, 1)]),                 # 19 to 21
    rtcm3.IgsUra: ([("satellite_count", 6, 0)], [("satellite", 6, 0), ("ura", 6, 0)], None),
    rtcm3.IgsVtec: ([("quality", 9, 0), ("layers_minus_1", 2, 0)],
                    [("height", 8, 0), ("degree_minus_1", 4, 0), ("order_minus_1", 4, 0)],
                    None),                                                            # 24, 25
}


def spec_bits(m) -> str:
    """The message as a bit string, row by row from SPEC (independent of the codec's tables)."""
    head, sat_rows, bias_rows = SPEC[type(m)]

    def put(obj, rows):
        out = ""
        for name, bits, signed in rows:
            v = getattr(obj, name)
            assert (-(1 << (bits - 1)) <= v < 1 << (bits - 1)) if signed else 0 <= v < 1 << bits
            out += format(v & ((1 << bits) - 1), f"0{bits}b")
        return out

    s = put(m, HEAD + head)
    items = m.layers if isinstance(m, rtcm3.IgsVtec) else m.satellites
    for item in items:
        s += put(item, sat_rows)
        if isinstance(m, rtcm3.IgsVtec):   # Tables 26 and 27
            s += "".join(format(c & 0xFFFF, "016b") for c in item.cosine + item.sine)
        elif bias_rows:
            s += "".join(put(b, bias_rows) for b in item.biases)
    return s


def table_4_bits(m) -> int:
    """'No. of Bytes' of Tables 4 and 6, in bits."""
    ns = len(getattr(m, "satellites", ()))
    nb = sum(len(s.biases) for s in getattr(m, "satellites", ()) if hasattr(s, "biases"))
    return {
        rtcm3.IgsOrbit: lambda: 9.875 * 8 + 16.875 * 8 * ns,
        rtcm3.IgsClock: lambda: 9.75 * 8 + 9.5 * 8 * ns,
        rtcm3.IgsCombined: lambda: 9.875 * 8 + 25.625 * 8 * ns,
        rtcm3.IgsHighRateClock: lambda: 9.75 * 8 + 3.5 * 8 * ns,
        rtcm3.IgsCodeBias: lambda: 9.75 * 8 + 1.375 * 8 * ns + 2.375 * 8 * nb,
        rtcm3.IgsPhaseBias: lambda: 10.0 * 8 + 3.5 * 8 * ns + 4.0 * 8 * nb,
        rtcm3.IgsUra: lambda: 9.75 * 8 + 1.5 * 8 * ns,
        rtcm3.IgsVtec: lambda: 10.375 * 8 + 2 * 8 * len(m.layers)
        + 2 * 8 * sum(len(la.cosine) + len(la.sine) for la in m.layers),
    }[type(m)]()


def loop_counts(n: int, m: int) -> tuple[int, int]:
    """Section 8.4.1's sequence, Cnm (m=0,M, n=m,N) and Snm (m=1,M, n=m,N), counted."""
    cos = [(i, j) for j in range(0, m + 1) for i in range(j, n + 1)]
    sin = [(i, j) for j in range(1, m + 1) for i in range(j, n + 1)]
    return len(cos), len(sin)


# --- hand-built messages of every sub-type ------------------------------------------------

def head(subtype: int, **kw) -> dict:
    return dict(number=4076, version=1, subtype=subtype, epoch=345_600, interval=2, multiple=0,
                iod_ssr=5, provider=300, solution=2) | kw


def example(subtype: int):
    cls = rtcm3.IGS_MESSAGES[subtype]
    h = head(subtype)
    if cls is rtcm3.IgsOrbit:
        sats = (rtcm3.IgsOrbitSat(1, 77, -12_345, 6_789, -1, 2_000, -3_000, 4),
                rtcm3.IgsOrbitSat(0, 255, 0, 0, 0, 0, 0, 0))
        return cls(**h, regional=0, satellite_count=2, satellites=sats)
    if cls is rtcm3.IgsClock:
        return cls(**h, satellite_count=1, satellites=(rtcm3.IgsClockSat(9, -50_000, 123, -4),))
    if cls is rtcm3.IgsCombined:
        sats = (rtcm3.IgsCombinedSat(3, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9),)
        return cls(**h, regional=1, satellite_count=1, satellites=sats)
    if cls is rtcm3.IgsHighRateClock:
        sats = (rtcm3.IgsHighRateClockSat(5, -9),
                rtcm3.IgsHighRateClockSat(6, 1_000_000))
        return cls(**h, satellite_count=2, satellites=sats)
    if cls is rtcm3.IgsCodeBias:
        sats = (rtcm3.IgsCodeBiasSat(2, 2, (rtcm3.IgsCodeBiasSignal(0, 345),
                                            rtcm3.IgsCodeBiasSignal(14, -2_000))),
                rtcm3.IgsCodeBiasSat(7, 0, ()))
        return cls(**h, satellite_count=2, satellites=sats)
    if cls is rtcm3.IgsPhaseBias:
        sats = (rtcm3.IgsPhaseBiasSat(4, 1, 300, -100, (
            rtcm3.IgsPhaseBiasSignal(1, 1, 0b10, 15, -400_000),)),)
        return cls(**h, dispersive=1, mw=1, satellite_count=1, satellites=sats)
    if cls is rtcm3.IgsUra:
        sats = tuple(rtcm3.IgsUraSat(i, u) for i, u in ((1, 0), (2, 0b111111), (3, 0b010011)))
        return cls(**h, satellite_count=3, satellites=sats)
    # IM201, the example of section 8.4.1 (N = 3, M = 2) as the first layer.
    layers = (rtcm3.IgsVtecLayer(45, 2, 1, tuple(range(-4, 5)), tuple(range(10, 15))),
              rtcm3.IgsVtecLayer(30, 0, 0, (16_383, -16_384, 0), (-1,)))
    return cls(**h, quality=20, layers_minus_1=1, layers=layers)


@pytest.mark.parametrize("subtype", SUBTYPES)
def test_every_subtype_encodes_from_fields_and_decodes_back(subtype):
    m = example(subtype)
    raw = rtcm3.encode(m)
    frame = rtcm3.parse(raw)
    assert isinstance(frame, rtcm3.Frame) and rtcm3.message_number(frame) == 4076
    bits = spec_bits(m)
    assert len(bits) == table_4_bits(m)
    assert frame.payload == int(bits + "0" * (-len(bits) % 8), 2).to_bytes(math.ceil(len(bits) / 8),
                                                                            "big")
    assert rtcm3.igs_subtype(frame.payload) == subtype
    assert rtcm3.decode(frame) == m
    assert rtcm3.decode(frame, strict=True) == m


def test_subtype_table_5():
    # Seven IGM types per system, in blocks of twenty, and IM201.
    assert rtcm3.IGS_SUBTYPES[21] == ("GPS", "IGM01")
    assert rtcm3.IGS_SUBTYPES[47] == ("GLONASS", "IGM07")
    assert rtcm3.IGS_SUBTYPES[63] == ("Galileo", "IGM03")
    assert rtcm3.IGS_SUBTYPES[85] == ("QZSS", "IGM05")
    assert rtcm3.IGS_SUBTYPES[106] == ("BDS", "IGM06")
    assert rtcm3.IGS_SUBTYPES[124] == ("SBAS", "IGM04")
    assert rtcm3.IGS_SUBTYPES[201] == (None, "IM201")
    assert set(rtcm3.IGS_SUBTYPES) == set(rtcm3.IGS_MESSAGES)
    assert sorted(rtcm3.IGS_SUBTYPES) == [b + i for b in (21, 41, 61, 81, 101, 121)
                                          for i in range(7)] + [201]
    names = {rtcm3.IgsOrbit: "IGM01", rtcm3.IgsClock: "IGM02", rtcm3.IgsCombined: "IGM03",
             rtcm3.IgsHighRateClock: "IGM04", rtcm3.IgsCodeBias: "IGM05",
             rtcm3.IgsPhaseBias: "IGM06", rtcm3.IgsUra: "IGM07", rtcm3.IgsVtec: "IM201"}
    for subtype, cls in rtcm3.IGS_MESSAGES.items():
        assert names[cls] == rtcm3.IGS_SUBTYPES[subtype][1]


def test_part_widths_are_the_table_totals():
    # The TOTAL rows: Tables 9 (135), 11 (76), 13 (205), 15 (28), 17 (11),
    # 18 (19), 20 (28), 21 (32), 23 (12), 25 (16 before the coefficients).
    assert layout(rtcm3.IgsOrbitSat).fixed_bits == 135
    assert layout(rtcm3.IgsClockSat).fixed_bits == 76
    assert layout(rtcm3.IgsCombinedSat).fixed_bits == 205
    assert layout(rtcm3.IgsHighRateClockSat).fixed_bits == 28
    assert layout(rtcm3.IgsCodeBiasSignal).fixed_bits == 19
    assert layout(rtcm3.IgsPhaseBiasSignal).fixed_bits == 32
    assert layout(rtcm3.IgsUraSat).fixed_bits == 12
    rows = {cls: [r for r in layout(cls).rows] for cls in (rtcm3.IgsCodeBiasSat,
                                                            rtcm3.IgsPhaseBiasSat,
                                                            rtcm3.IgsVtecLayer)}
    def fixed(cls):
        return sum(r.kind.width.value for r in rows[cls] if r.kind.count is None)
    assert (fixed(rtcm3.IgsCodeBiasSat), fixed(rtcm3.IgsPhaseBiasSat),
            fixed(rtcm3.IgsVtecLayer)) == (11, 28, 16)
    # Header TOTALs: Tables 8 (79), 10 (78), 12 (79), 14 (78), 16 (78), 19
    # (80), 22 (78), 24 (83).
    totals = {rtcm3.IgsOrbit: 79, rtcm3.IgsClock: 78, rtcm3.IgsCombined: 79,
              rtcm3.IgsHighRateClock: 78, rtcm3.IgsCodeBias: 78, rtcm3.IgsPhaseBias: 80,
              rtcm3.IgsUra: 78, rtcm3.IgsVtec: 83}
    for cls, total in totals.items():
        assert sum(r.kind.width.value for r in layout(cls).rows
                   if isinstance(r.kind, U | S) and r.kind.count is None) == total


def test_rows_carry_the_table_7_identifiers():
    # Tags are Table 7's IDF numbers; the orbit rows follow Table 7 and
    # Table 13 where Table 9 prints IDF015 and IDF016 the other way round.
    tags = {r.name: r.kind.tag for r in layout(rtcm3.IgsOrbitSat).rows}
    assert tags == {"satellite": "IDF011", "iod": "IDF012", "radial": "IDF013",
                    "along": "IDF014", "cross": "IDF015", "dot_radial": "IDF016",
                    "dot_along": "IDF017", "dot_cross": "IDF018"}
    assert [r.kind.tag for r in layout(rtcm3.IgsCombinedSat).rows] == \
        [f"IDF0{n}" for n in range(11, 22)]


# --- generated messages ------------------------------------------------------------------------

def _int(kind, width):
    if isinstance(kind, S):
        return st.integers(-(1 << (width - 1)), (1 << (width - 1)) - 1)
    return st.integers(0, (1 << width) - 1)


SMALL = {"satellite_count": 6, "bias_count": 5, "layers_minus_1": 3}


def draw(data, cls, fixed: dict, outer=None):
    """A random ``cls``, row by row from its compiled table; counts kept small."""
    values: dict = {}

    def env(name):
        if name in values:
            return values[name]
        return outer(name)

    for row in layout(cls).rows:
        kind, name = row.kind, row.name
        if name == "extension":
            values[name] = None
        elif name in fixed:
            values[name] = fixed[name]
        elif isinstance(kind, Group):
            n = kind.count.eval(env)
            values[name] = tuple(draw(data, kind.cls, {}, env) for _ in range(n))
        elif name in SMALL:
            values[name] = data.draw(st.integers(0, SMALL[name]))
        elif kind.count is not None:
            n = kind.count.eval(env)
            values[name] = tuple(data.draw(_int(kind, kind.width.eval(env))) for _ in range(n))
        else:
            values[name] = data.draw(_int(kind, kind.width.eval(env)))
    return cls(**values)


@settings(max_examples=400, derandomize=True, deadline=None)
@given(st.data())
def test_generated_messages_round_trip(data):
    subtype = data.draw(st.sampled_from(SUBTYPES))
    m = draw(data, rtcm3.IGS_MESSAGES[subtype], {"number": 4076, "subtype": subtype})
    raw = rtcm3.encode(m)
    frame = rtcm3.parse(raw)
    assert rtcm3.decode(frame) == m and rtcm3.encode(rtcm3.decode(frame)) == raw
    bits = spec_bits(m)
    assert len(frame.payload) == math.ceil(len(bits) / 8)
    if not isinstance(m, rtcm3.IgsVtec) or all(la.order_minus_1 <= la.degree_minus_1
                                               for la in m.layers):
        assert len(bits) == table_4_bits(m)


@pytest.mark.parametrize("n", range(1, 17))
def test_vtec_coefficient_counts(n):
    # Table 7, IDF039 and IDF040: (N+1)(N+2)/2 - (N-M)(N-M+1)/2 cosine and
    # N+1 fewer sine coefficients; section 8.4.1: their sum is
    # (N+1)(N+1) - (N-M)(N-M+1), and the loops count the same for M <= N
    # (section 4.5.1). For M > N the counts follow the loops (_igs).
    for m in range(1, 17):
        layer = layout(rtcm3.IgsVtecLayer)
        env = {"degree_minus_1": n - 1, "order_minus_1": m - 1}.__getitem__
        cos, sin = (r.kind.count.eval(env) for r in layer.rows if r.name in ("cosine", "sine"))
        assert (cos, sin) == loop_counts(n, m)
        if m <= n:
            assert cos == ((n + 1) * (n + 2) - (n - m) * (n - m + 1)) // 2
            assert sin == cos - (n + 1)
            assert cos + sin == (n + 1) * (n + 1) - (n - m) * (n - m + 1)
    assert loop_counts(3, 2) == (9, 5)   # the C00 ... S32 example of section 8.4.1


# --- boundary and invalid values -----------------------------------------------------------------

def _paths(m):
    """(path, row kind) for every integer row of the message's first item at each level."""
    out = []

    def walk(obj, prefix):
        for row in layout(type(obj)).rows:
            value = getattr(obj, row.name)
            if row.name == "extension":
                continue
            if isinstance(row.kind, Group):
                if value:
                    walk(value[0], prefix + [(row.name, 0)])
            elif row.kind.count is None and not row.name.endswith(("_count", "_minus_1")) \
                    and row.name not in ("number", "subtype"):
                out.append((prefix + [(row.name, None)], row.kind))
    walk(m, [])
    return out


def _set(obj, path, value):
    (name, index), rest = path[0], path[1:]
    if index is None:
        return replace(obj, **{name: value})
    items = list(getattr(obj, name))
    items[index] = _set(items[index], rest, value)
    return replace(obj, **{name: tuple(items)})


@pytest.mark.parametrize("subtype", SUBTYPES)
def test_every_field_at_the_ends_of_its_range(subtype):
    base = example(subtype)
    for path, kind in _paths(base):
        width = kind.width.value
        lo, hi = ((-(1 << (width - 1)), (1 << (width - 1)) - 1) if isinstance(kind, S)
                  else (0, (1 << width) - 1))
        for value in (lo, hi):
            m = _set(base, path, value)
            assert rtcm3.decode(rtcm3.parse(rtcm3.encode(m))) == m, (path, value)
        for value in (lo - 1, hi + 1):
            with pytest.raises(rtcm3.FieldError):
                rtcm3.encode(_set(base, path, value))


def test_counts_at_their_limits():
    # IDF010 up to 63 satellites, IDF023 up to 31 biases, IDF035 up to 4
    # layers, IDF037 and IDF038 up to 16.
    sats = tuple(rtcm3.IgsUraSat(i, 63 - i) for i in range(63))
    m = rtcm3.IgsUra(**head(27), satellite_count=63, satellites=sats)
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(m))) == m
    # 63 orbit satellites (79 + 135·63 bits, 1073 bytes) do not fit the
    # frame's 1023 bytes (RTCM 10403.3 Table 4-1); a sender splits them with
    # IDF005, the multiple message indicator (section 6).
    sats = tuple(rtcm3.IgsOrbitSat(i, i, -i, i, -i, i, -i, i) for i in range(63))
    with pytest.raises(rtcm3.FieldError, match="10-bit length"):
        rtcm3.encode(rtcm3.IgsOrbit(**head(21), regional=0, satellite_count=63, satellites=sats))
    m = rtcm3.IgsOrbit(**head(21, multiple=1), regional=0, satellite_count=60,
                       satellites=sats[:60])
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(m))) == m
    biases = tuple(rtcm3.IgsCodeBiasSignal(i, -i) for i in range(31))
    m = rtcm3.IgsCodeBias(**head(65), satellite_count=1,
                          satellites=(rtcm3.IgsCodeBiasSat(36, 31, biases),))
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(m))) == m
    layer = rtcm3.IgsVtecLayer(255, 15, 15, tuple(range(153)), tuple(range(136)))
    assert loop_counts(16, 16) == (153, 136)
    m = rtcm3.IgsVtec(**head(201), quality=511, layers_minus_1=0, layers=(layer,))
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(m))) == m
    four = rtcm3.IgsVtec(**head(201), quality=0, layers_minus_1=3,
                         layers=(rtcm3.IgsVtecLayer(0, 0, 0, (0, 0, 0), (0,)),) * 4)
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(four))) == four
    # A count is a field; it must equal the length of what follows it.
    for bad in (replace(example(21), satellite_count=1),
                replace(example(25), satellite_count=3),
                replace(m, layers_minus_1=1),
                replace(example(26), satellites=(replace(example(26).satellites[0],
                                                         bias_count=2),))):
        with pytest.raises(rtcm3.FieldError):
            rtcm3.encode(bad)
    with pytest.raises(rtcm3.FieldError):   # 64 satellites do not fit IDF010
        rtcm3.encode(replace(m := rtcm3.IgsUra(**head(27), satellite_count=64,
                                               satellites=(rtcm3.IgsUraSat(1, 1),) * 64)))


@pytest.mark.parametrize("subtype", [s for s in range(256) if s not in rtcm3.IGS_MESSAGES])
def test_reserved_subtypes_are_unsupported(subtype):
    # Table 5: IM000 to IM020, the 13 after each system's seven, NavIC's
    # IM141 to IM160, IM161 to IM200 and IM202 to IM254 are reserved, and 255
    # "reserved for extension" (IDF002).
    # DF002 = 4076 (12 bits), IDF001 = 1 (3), IDF002 (8), then zeros.
    payload = ((4076 << 11 | 1 << 8 | subtype) << 9).to_bytes(4, "big") + bytes(20)
    with pytest.raises(rtcm3.Unsupported, match=f"sub-type {subtype}"):
        rtcm3.decode(rtcm3.parse(rtcm3.encode_frame(payload)))


@pytest.mark.parametrize("subtype", SUBTYPES)
def test_short_messages_are_refused(subtype):
    # From two bytes on, where DF002 says 4076 (shorter, it is no message
    # number and Unsupported, as for every message).
    payload = rtcm3.parse(rtcm3.encode(example(subtype))).payload
    for cut in range(2, len(payload)):
        with pytest.raises(rtcm3.FieldError):
            rtcm3.decode(rtcm3.parse(rtcm3.encode_frame(payload[:cut])))


def test_encode_checks_number_and_subtype():
    m = example(21)
    for bad in (replace(m, subtype=22), replace(m, subtype=20), replace(m, subtype=201),
                replace(m, number=1005), replace(example(201), subtype=21)):
        with pytest.raises(TypeError):
            rtcm3.encode(bad)
    for subtype in (41, 61, 81, 101, 121):   # one class serves every system
        assert rtcm3.decode(rtcm3.parse(rtcm3.encode(replace(m, subtype=subtype)))).subtype \
            == subtype
    assert 4076 not in rtcm3.MESSAGES


@pytest.mark.parametrize("subtype", SUBTYPES)
def test_data_after_the_table_is_kept(subtype):
    # As for every RTCM message here (README, rtcm3): kept in ``extension``,
    # written back; strict=True refuses it.
    plain = example(subtype)
    payload = rtcm3.parse(rtcm3.encode(plain)).payload
    fill = -len(spec_bits(plain)) % 8
    for tail in (b"\x00", b"\xa5\x5a\x01"):
        longer = rtcm3.encode_frame(payload + tail)
        m = rtcm3.decode(rtcm3.parse(longer))
        assert m.extension == Extension(fill + 8 * len(tail), int.from_bytes(tail, "big"))
        assert replace(m, extension=None) == plain and rtcm3.encode(m) == longer
        with pytest.raises(rtcm3.FieldError, match="left over"):
            rtcm3.decode(rtcm3.parse(longer), strict=True)
    if fill:
        odd = rtcm3.encode_frame(payload[:-1] + bytes([payload[-1] | 1]))
        m = rtcm3.decode(rtcm3.parse(odd))
        assert m.extension == Extension(fill, 1) and rtcm3.encode(m) == odd


def test_update_interval_table():
    # IDF004, Table 7.
    assert [rtcm3.update_interval(c) for c in range(16)] == [
        1, 2, 5, 10, 15, 30, 60, 120, 240, 300, 600, 900, 1800, 3600, 7200, 10800]
    assert rtcm3.IGS_UPDATE_INTERVALS == tuple(rtcm3.update_interval(c) for c in range(16))
    for bad in (-1, 16, True, 1.0, None):
        with pytest.raises(ValueError):
            rtcm3.update_interval(bad)


def test_identifier_tables_of_table_7():
    sat = rtcm3.IGS_SATELLITES
    assert (sat["GPS"][1], sat["GPS"][63], sat["GPS"][0]) == (1, 63, 64)
    assert sat["GLONASS"][0] == 64 and sat["BDS"][0] == 64 and len(sat["BDS"]) == 64
    assert sorted(sat["Galileo"]) == list(range(1, 37))
    assert (sat["QZSS"][1], sat["QZSS"][2], sat["QZSS"][10], len(sat["QZSS"])) == (193, 194, 202, 10)
    assert (sat["SBAS"][1], sat["SBAS"][2], sat["SBAS"][39], len(sat["SBAS"])) == (120, 121, 158, 39)
    sig = rtcm3.IGS_SIGNALS
    assert set(sig) == set(rtcm3.IGS_SYSTEMS) == set(sat)
    assert (sig["GPS"][0], sig["GPS"][6], sig["GPS"][15], 9 in sig["GPS"]) == ("1C", "2D", "5Q",
                                                                              False)
    assert (sig["GLONASS"][4], sig["GLONASS"][9], 10 in sig["GLONASS"]) == ("4A", "3Q", False)
    assert (sig["Galileo"][1], sig["Galileo"][8], sig["Galileo"][16]) == ("1B", "7I", "6C")
    assert (sig["QZSS"][9], sig["QZSS"][17], 18 in sig["QZSS"]) == ("6S", "6E", False)
    assert (sig["BDS"][0], sig["BDS"][15], sig["BDS"][18], 19 in sig["BDS"]) == ("2I", "1A", "6A",
                                                                                 False)
    assert sig["SBAS"] == {0: "1C", 1: "5I", 2: "5Q"}
    assert all(0 <= i <= 31 and len(c) == 2 for t in sig.values() for i, c in t.items())


# --- RTKLIB ---------------------------------------------------------------------------------------

LETTER = {"GPS": "G", "GLONASS": "R", "Galileo": "E", "QZSS": "J", "BDS": "C", "SBAS": "S"}
# Where RTKLIB's decoder departs from Table 7: it gives
# RINEX codes to identifiers the table reserves, and reads no satellite
# from SBAS phase bias frames (sub-type 126), its own included.
RTKLIB_EXTRA_SIGNALS = {"GPS": {9: "2X"}, "Galileo": {11: "8L", 12: "8Q"}}
RTKLIB_READS_NOTHING = {126}


def test_rtklib_data_is_complete():
    assert len(RTKLIB) == len(RTKLIB_READ)
    rtklib_made = {rtcm3.igs_subtype(raw[3:-3]) for raw, note in RTKLIB if note.startswith("RTKLIB")}
    assert rtklib_made == set(SUBTYPES) - {201}
    probes = {rtcm3.igs_subtype(raw[3:-3]) for raw, note in RTKLIB if note.startswith("gnsswire")}
    assert probes == {f + o for f in rtcm3.IGS_SYSTEMS.values() for o in (4, 5)}


@pytest.mark.parametrize(("raw", "note"), RTKLIB, ids=[f"{i}:{n}" for i, (_, n) in enumerate(RTKLIB)])
def test_rtklib_frames_round_trip(raw, note):
    m = rtcm3.decode(rtcm3.parse(raw), strict=True)
    assert rtcm3.encode(m) == raw
    assert len(spec_bits(m)) == table_4_bits(m)


def test_rtklib_reads_what_we_read():
    compared = defaultdict(int)
    for (raw, note), read in zip(RTKLIB, RTKLIB_READ, strict=True):
        m = rtcm3.decode(rtcm3.parse(raw))
        assert read["subtype"] == m.subtype, note
        system, igm = rtcm3.IGS_SUBTYPES[m.subtype]
        if m.subtype in RTKLIB_READS_NOTHING:
            assert read["sats"] == {} and m.satellites, note
            continue
        theirs = read["sats"]
        names = [f"{LETTER[system]}{rtcm3.IGS_SATELLITES[system][s.satellite]:03d}"
                 for s in m.satellites]
        assert sorted(names) == sorted(theirs), note
        signals = rtcm3.IGS_SIGNALS[system] | RTKLIB_EXTRA_SIGNALS.get(system, {})
        for name, s in zip(names, m.satellites):
            t = theirs[name]
            assert (t["tow"], t["udi"], t["iod_ssr"]) == \
                (m.epoch, rtcm3.update_interval(m.interval), m.iod_ssr), note
            close = lambda a, b: math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)  # noqa: E731
            if igm in ("IGM01", "IGM03"):
                assert t["iode"] == s.iod
                assert all(map(close, t["deph"], (s.radial * 1e-4, s.along * 4e-4,
                                                  s.cross * 4e-4))), note
                assert all(map(close, t["ddeph"], (s.dot_radial * 1e-6, s.dot_along * 4e-6,
                                                   s.dot_cross * 4e-6))), note
            if igm in ("IGM02", "IGM03"):
                assert all(map(close, t["dclk"], (s.c0 * 1e-4, s.c1 * 1e-6, s.c2 * 2e-8))), note
            if igm == "IGM04":
                assert close(t["hrclk"], s.high_rate_clock * 1e-4)
            if igm == "IGM07":
                assert t["ura"] == s.ura
            if igm in ("IGM05", "IGM06"):
                key, unit = ("cbias", 0.01) if igm == "IGM05" else ("pbias", 1e-4)
                ours = {signals[b.signal]: b.bias * unit for b in s.biases
                        if b.bias and b.signal in signals}
                got = t[key]
                assert sorted(ours) == sorted(got), note
                assert all(math.isclose(ours[c], got[c], rel_tol=1e-6) for c in ours), note
            if igm == "IGM06":
                assert close(t["yaw_ang"], s.yaw * 180 / 256)
                assert close(t["yaw_rate"], s.yaw_rate * 180 / 8192)
            compared[igm] += 1
    assert set(compared) == set(rtcm3.IGM_TYPES)


def test_rtklib_maps_every_signal_of_table_7():
    # The probe frames carry identifiers 0 to 31: RTKLIB gives every one
    # Table 7 lists the same RINEX code, and codes to RTKLIB_EXTRA_SIGNALS only.
    for (raw, note), read in zip(RTKLIB, RTKLIB_READ, strict=True):
        if not note.startswith("gnsswire") or read["subtype"] in RTKLIB_READS_NOTHING:
            continue
        system = rtcm3.IGS_SUBTYPES[read["subtype"]][0]
        key, unit = ("cbias", 1.0) if read["subtype"] % 20 == 5 else ("pbias", 0.1)
        found = {round(v / unit) - 1: code for s in read["sats"].values()
                 for code, v in s[key].items()}
        assert found == rtcm3.IGS_SIGNALS[system] | RTKLIB_EXTRA_SIGNALS.get(system, {}), note


# --- pyrtcm -------------------------------------------------------------------------------------

# Table 7 resolutions, in Table 7's units (pyrtcm reports those units).
RESOLUTION = {"IDF013": 0.1, "IDF014": 0.4, "IDF015": 0.4, "IDF016": 0.001, "IDF017": 0.004,
              "IDF018": 0.004, "IDF019": 0.1, "IDF020": 0.001, "IDF021": 0.00002,
              "IDF022": 0.1, "IDF025": 0.01, "IDF026": 1 / 256, "IDF027": 1 / 8192,
              "IDF028": 0.0001, "IDF036": 10, "IDF039": 0.005, "IDF040": 0.005, "IDF041": 0.05}


def _ours(m) -> dict[str, int]:
    """Our fields keyed as pyrtcm keys them: IDFnnn, IDFnnn_ii, IDFnnn_ii_jj."""
    out: dict[str, int] = {}

    def walk(obj, suffix):
        for row in layout(type(obj)).rows:
            value, tag = getattr(obj, row.name), row.kind.tag
            if row.name == "extension":
                continue
            if isinstance(row.kind, Group):
                for i, item in enumerate(value, 1):
                    walk(item, f"{suffix}_{i:02d}")
            elif row.kind.count is not None:
                for i, v in enumerate(value, 1):
                    out[f"{tag}{suffix}_{i:02d}"] = v
            else:
                out[f"{tag}{suffix}"] = value
    walk(m, "")
    return out


def _agree_with_pyrtcm(raw: bytes):
    m = rtcm3.decode(rtcm3.parse(raw))
    theirs = {k: v for k, v in vars(pyrtcm.RTCMReader.parse(raw)).items()
              if k.startswith(("DF", "IDF"))}
    ours = _ours(m)
    assert sorted(ours) == sorted(theirs)
    if isinstance(m, rtcm3.IgsOrbit):
        # Table 9's fifth and sixth rows: pyrtcm reads other bits
        # (test_pyrtcm_reads_table_9_by_its_idf_numbers).
        for key in [k for k in ours if k.startswith(("IDF015_", "IDF016_"))]:
            del ours[key], theirs[key]
    for key, mine in ours.items():
        scale = RESOLUTION.get(key.split("_")[0], 1)
        assert math.isclose(theirs[key], mine * scale, rel_tol=1e-9, abs_tol=1e-12), key


@pytest.mark.parametrize(("raw", "note"), RTKLIB, ids=[f"{i}:{n}" for i, (_, n) in enumerate(RTKLIB)])
def test_pyrtcm_agrees_on_rtklib_frames(raw, note):
    _agree_with_pyrtcm(raw)


@pytest.mark.parametrize("subtype", SUBTYPES)
def test_pyrtcm_agrees_on_examples(subtype):
    _agree_with_pyrtcm(rtcm3.encode(example(subtype)))


@settings(max_examples=300, derandomize=True, deadline=None)
@given(st.data())
def test_pyrtcm_agrees_on_generated_messages(data):
    subtype = data.draw(st.sampled_from(SUBTYPES))
    m = draw(data, rtcm3.IGS_MESSAGES[subtype], {"number": 4076, "subtype": subtype})
    # M > N: pyrtcm reads the counts of IDF039's formula, not the loops of
    # section 8.4.1 (test_pyrtcm_reads_m_above_n_by_the_formula).
    assume(not isinstance(m, rtcm3.IgsVtec)
           or all(la.order_minus_1 <= la.degree_minus_1 for la in m.layers))
    _agree_with_pyrtcm(rtcm3.encode(m))


def test_pyrtcm_reads_table_9_by_its_idf_numbers():
    # Table 9 prints its fifth row "Delta Orbit Cross-Track IDF016 int20"
    # and its sixth "Dot Orbit Delta Radial IDF015 int21". gnsswire (and
    # RTKLIB, and Table 13 for the combined message) read int20 then int21,
    # cross-track then radial rate. pyrtcm 1.2.1 reads the fifth row as
    # IDF016 with Table 7's int21 and the sixth as IDF015 with int20: the
    # same 41 bits, cut one bit later. The README, "Limitations", gives the
    # reading taken.
    sat = rtcm3.IgsOrbitSat(1, 2, 3, 4, cross=1, dot_radial=1, dot_along=5, dot_cross=6)
    m = rtcm3.IgsOrbit(**head(21), regional=0, satellite_count=1, satellites=(sat,))
    theirs = vars(pyrtcm.RTCMReader.parse(rtcm3.encode(m)))
    bits = spec_bits(m)
    at = 79 + 6 + 8 + 22 + 20               # the fifth satellite row
    def sint(s):
        return int(s, 2) - (1 << len(s)) * (s[0] == "1")
    assert math.isclose(theirs["IDF016_01"], sint(bits[at:at + 21]) * 0.001)   # 2 here
    assert math.isclose(theirs["IDF015_01"], sint(bits[at + 21:at + 41]) * 0.4)
    assert (sint(bits[at:at + 20]), sint(bits[at + 20:at + 41])) == (1, 1)
    # Their combined message (Table 13, no swap) agrees with ours.
    _agree_with_pyrtcm(rtcm3.encode(example(23)))


def test_pyrtcm_reads_m_above_n_by_the_formula():
    # N = 1, M = 3 (outside section 4.5.1's M <= N): the loops of 8.4.1 give
    # 3 cosine and 1 sine coefficient (gnsswire); IDF039's formula,
    # (N+1)(N+2)/2 - (N-M)(N-M+1)/2, gives 2, and pyrtcm reads 2 cosine
    # and no sine. The README, "Limitations", gives the reading taken.
    layer = rtcm3.IgsVtecLayer(45, 0, 2, (1, 2, 3), (4,))
    m = rtcm3.IgsVtec(**head(201), quality=1, layers_minus_1=0, layers=(layer,))
    theirs = vars(pyrtcm.RTCMReader.parse(rtcm3.encode(m)))
    assert sorted(k for k in theirs if k.startswith(("IDF039", "IDF040"))) == \
        ["IDF039_01_01", "IDF039_01_02"]
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(m))) == m


# --- local recordings ---------------------------------------------------------------------------
#
# build/private/ (gitignored, never committed) may hold recorded RTCM
# streams (*.bin, in any subdirectory). Every 4076 frame of a sub-type
# Table 5 defines must decode, round-trip and agree with pyrtcm. A frame of
# a sub-type Table 5 reserves must be refused (Unsupported), which is the
# specified behaviour, not a failure; such frames are counted per sub-type
# and reported as a warning. Nothing from the recordings is copied into the
# repository.

PRIVATE = Path(__file__).resolve().parents[3] / "build" / "private"

# IDF002 values IGS SSR v1.00 reserves, written out from Table 5 ("IM000 -
# IM020 Reserved", "IM028 - IM040 Reserved for GPS" and the like for each
# system, "IM141 - IM160 Reserved for NavIC/IRNSS", "IM161 - IM200
# Reserved", "IM202 - IM254 Reserved") and Table 7, IDF002 ("255 - reserved
# for extension of sub-type message range").
TABLE_5_RESERVED = frozenset(
    [*range(0, 21), *(s for first in (28, 48, 68, 88, 108, 128) for s in range(first, first + 13)),
     *range(141, 161), *range(161, 201), *range(202, 255), 255])


def test_table_5_reserves_every_subtype_without_a_table():
    assert TABLE_5_RESERVED.isdisjoint(rtcm3.IGS_MESSAGES)
    assert TABLE_5_RESERVED | set(rtcm3.IGS_MESSAGES) == set(range(256))


def test_private_recordings_with_4076():
    if not PRIVATE.is_dir():
        pytest.skip("private captures (build/private/) are absent")
    frames = []
    for path in sorted(PRIVATE.rglob("*.bin")):
        stream = path.read_bytes()
        for frame in rtcm3.scan(stream):
            if rtcm3.message_number(frame) == 4076:
                frames.append((stream[frame.offset:frame.offset + frame.length],
                               f"{path.name} at {frame.offset}", frame))
    if not frames:
        pytest.skip("no message 4076 (IGS SSR) in the private captures (build/private/)")
    failures, reserved, checked = [], Counter(), Counter()
    for raw, note, frame in frames:
        subtype = rtcm3.igs_subtype(frame.payload)
        if subtype not in rtcm3.IGS_MESSAGES:
            # Not a failure of the codec, but only for a sub-type Table 5
            # reserves, and only if it is refused as Unsupported.
            reserved[subtype] += 1
            if subtype not in TABLE_5_RESERVED:
                failures.append((note, f"sub-type {subtype} neither defined nor reserved"))
                continue
            try:
                rtcm3.decode(frame)
            except rtcm3.Unsupported:
                continue
            except rtcm3.Error as exc:
                failures.append((note, f"reserved sub-type {subtype}: {exc}"))
                continue
            failures.append((note, f"reserved sub-type {subtype} decoded"))
            continue
        try:
            m = rtcm3.decode(frame)
        except rtcm3.Error as exc:     # Unsupported included: the sub-type has a table
            failures.append((note, str(exc)))
            continue
        if rtcm3.encode(m) != raw:
            failures.append((note, "round trip"))
            continue
        try:
            _agree_with_pyrtcm(raw)
        except AssertionError as exc:
            failures.append((note, f"pyrtcm: {exc}"))
            continue
        checked[subtype] += 1
    assert not failures, failures[:10]
    assert checked, "no 4076 frame of a defined sub-type in the private captures"
    if reserved:
        warnings.warn(f"private captures: 4076 frames of sub-types IGS SSR v1.00 Table 5 "
                      f"reserves, refused as specified (sub-type: frames): {dict(sorted(reserved.items()))}; "
                      f"{sum(checked.values())} frames of defined sub-types checked",
                      stacklevel=1)


def test_field_names_are_unique_per_class():
    for cls in set(rtcm3.IGS_MESSAGES.values()):
        names = [f.name for f in fields(cls)]
        assert len(names) == len(set(names)) and names[-1] == "extension"
