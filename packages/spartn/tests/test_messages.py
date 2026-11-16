"""SPARTN messages against SPARTN v2.0.3 section 6.5.

- Field tables: each block's rows, SF numbers and fixed widths are compared
  with a transcription of Tables 6.3 to 6.24 here, and the per-constellation
  widths with one of Table 6.2.
- Sizes: the bit length of every generated message equals the "nominal size
  calculation" of Table 8.2, computed here from its own formulas.
- Hand-built payloads: GAD, HPAC with grids, and OCB with a DNU satellite,
  assembled bit by bit in this file in the order the tables print, decode to
  the values put in.
- Round trip: ``decode(encode(m)) == m`` for generated messages covering
  every block type, every equation type and coefficient size, every residual
  size, every mask size and every constellation, and ``encode(decode(f)) ==
  f`` for their frames.
- Encryption: AES-128-CTR with the initialisation vector of section 8.15.1,
  checked against the ``cryptography`` package and a vector built here.
- Cross-check: pyspartn, a dev-only dependency used as an oracle through its
  public API, decodes our frames (and decrypts our encrypted ones) to the
  same fields (test_pyspartn_*).

Private captures (build/private/, never committed) are decoded and checked
the same way when present (test_private_*).
"""

import datetime
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import pyspartn
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from gnsswire import spartn
from gnsswire.bits import BitError, BitWriter, Extension, layout, write
from gnsswire.bits._table import Const
from gnsswire.spartn import (
    Bias,
    Bpac,
    BpacArea,
    BpacGridPoint,
    Clock,
    Description,
    Encrypted,
    Gad,
    GadArea,
    Hpac,
    HpacArea,
    IonoLarge,
    IonoSatellite,
    IonoSmall,
    Ionosphere,
    Message,
    Ocb,
    OcbHeader,
    OcbSatellite,
    Orbit,
    PhaseBias,
    Troposphere,
    TropoLarge,
    TropoSmall,
    Unsupported,
)

# --- Table 6.2, per constellation (subtype 0 GPS, 1 GLONASS, 2 Galileo, 3 BeiDou, 4 QZSS) ----

EPHEMERIS_BITS = [2, 2, 3, 4, 3]                         # SF016, SF017, SF096, SF097, SF098
SAT_MASK_BITS = [(32, 44, 56, 64), (24, 36, 48, 63),     # SF011, SF012
                 (36, 45, 54, 64), (37, 46, 55, 64),     # SF093, SF094
                 (10, 40, 48, 64)]                       # SF095
IODE_BITS = [8, 7, 10, 8, 8]                             # SF018, SF019, SF099, SF100, SF101
PHASE_MASK_BITS = [(6, 11), (5, 9), (8, 15), (8, 15), (6, 11)]   # SF025 SF026 SF102 SF103 SF104
CODE_MASK_BITS = [(6, 11), (5, 9), (8, 15), (8, 15), (6, 11)]    # SF027 SF028 SF105 SF106 SF107

# --- Tables 6.3 to 6.24: (SF, bits) of the rows with a fixed width, in order -------------------

MASK = "SF011/SF012/SF093/SF094/SF095"   # the 2-bit size indicator that opens each mask
SPEC_ROWS = {
    Ocb: [("SF005", 9), ("SF010", 1), ("SF069", 1), ("SF008", 1), ("SF009", 1),
          (MASK, 2)],                                                                # Table 6.3
    OcbSatellite: [("SF013", 1), ("SF014", 3), ("SF015", 3)],                       # Table 6.4
    Orbit: [("SF020", 14), ("SF020", 14), ("SF020", 14), ("SF021", 6)],              # Table 6.5
    Clock: [("SF022", 3), ("SF020", 14), ("SF024", 3)],                              # Table 6.6
    PhaseBias: [("SF023", 1), ("SF015", 3), ("SF020", 14)],                          # Table 6.12
    Bias: [("SF025/SF026/SF102/SF103/SF104", 1), ("SF027/SF028/SF105/SF106/SF107", 1),
           ("SF029", 11)],                                                           # 6.7-6.11
    Hpac: [("SF005", 9), ("SF068", 4), ("SF069", 1), ("SF030", 5)],                  # Table 6.13
    HpacArea: [("SF031", 8), ("SF039", 7), ("SF040", 2), ("SF040", 2)],              # Table 6.15
    Troposphere: [("SF041", 3), ("SF042", 3), ("SF043", 8), ("SF044", 1), ("SF051", 1)],  # 6.16
    TropoSmall: [("SF045", 7), ("SF046", 7), ("SF046", 7), ("SF047", 9)],            # Table 6.17
    TropoLarge: [("SF048", 9), ("SF049", 9), ("SF049", 9), ("SF050", 11)],           # Table 6.18
    Ionosphere: [("SF054", 3), (MASK, 2)],                                           # Table 6.19
    IonoSatellite: [("SF055", 4), ("SF056", 1), ("SF063", 2)],                       # Table 6.20
    IonoSmall: [("SF057", 12), ("SF058", 12), ("SF058", 12), ("SF059", 13)],         # Table 6.21
    IonoLarge: [("SF060", 14), ("SF061", 14), ("SF061", 14), ("SF062", 15)],         # Table 6.22
    Gad: [("SF005", 9), ("SF068", 4), ("SF069", 1), ("SF030", 5)],                   # Table 6.23
    GadArea: [("SF031", 8), ("SF032", 11), ("SF033", 12), ("SF034", 3), ("SF035", 3),
              ("SF036", 5), ("SF037", 5)],                                           # Table 6.24
    Bpac: [("SF005", 9), ("SF069", 1), ("SF070", 2), ("SF071", 2)],                  # Table 6.25
    BpacArea: [("SF072", 2), ("SF073", 8), ("SF074", 9), ("SF075", 4), ("SF076", 4),
               ("SF077", 2), ("SF078", 2), ("SF080", 12)],                           # Table 6.27
    BpacGridPoint: [("SF055", 4), ("SF081", 1)],                                     # Table 6.28
}


def _layouts():
    """Every block's compiled layout, reached from the three message roots."""
    found = {}

    def walk(lay):
        found[lay.cls] = lay
        for row in lay.rows:
            if row.group is not None:
                walk(row.group)
    for root in (Ocb, Hpac, Gad, Bpac):
        walk(layout(root))
    return found


LAYOUTS = _layouts()


@pytest.mark.parametrize("cls", list(SPEC_ROWS), ids=lambda c: c.__name__)
def test_fixed_rows_are_the_spec_tables(cls):
    rows = [(r.kind.tag, r.kind.width.value) for r in LAYOUTS[cls].rows
            if r.group is None and isinstance(getattr(r.kind, "width", None), Const)]
    assert rows == SPEC_ROWS[cls]


def test_every_block_is_listed():
    assert set(LAYOUTS) == set(SPEC_ROWS)


def _width(cls, field, subtype, **fields):
    row = next(r for r in LAYOUTS[cls].rows if r.name == field)
    env = {"subtype": subtype, **fields}
    return row.kind.width.eval(env.__getitem__)


@pytest.mark.parametrize("subtype", range(5))
def test_constellation_widths_are_table_6_2(subtype):
    assert _width(Ocb, "ephemeris_type", subtype) == EPHEMERIS_BITS[subtype]
    assert _width(Orbit, "iode", subtype) == IODE_BITS[subtype]
    for size in range(4):
        assert _width(Ocb, "mask", subtype, mask_size=size) == SAT_MASK_BITS[subtype][size]
        assert _width(Ionosphere, "mask", subtype, mask_size=size) == SAT_MASK_BITS[subtype][size]
    for size in range(2):
        assert _width(Bias, "phase_mask", subtype, phase_mask_size=size) == \
            PHASE_MASK_BITS[subtype][size]
        assert _width(Bias, "code_mask", subtype, code_mask_size=size) == \
            CODE_MASK_BITS[subtype][size]


def test_message_tables():
    assert spartn.MESSAGES == {**{(0, s): Ocb for s in range(5)},
                               **{(1, s): Hpac for s in range(5)}, (2, 0): Gad, (3, 0): Bpac}


def test_bpac_widths_are_table_6_2():
    # SF079 is N bits, N the number of grid points: (SF075 + 1) * (SF076 + 1),
    # 1 to 256; SF082 and SF083 are 7 and 11 bits by SF081.
    for lat, lon in [(0, 0), (3, 4), (15, 15)]:
        assert _width(BpacArea, "present", 0, latitude_nodes=lat, longitude_nodes=lon) \
            == (lat + 1) * (lon + 1)
    assert [_width(BpacGridPoint, "residual", 0, size=s) for s in (0, 1)] == [7, 11]


def test_ocb_header_is_the_start_of_ocb():
    # Same rows, same SF numbers, in the same order; decode_ocb_header reads them.
    head = [(r.name, r.kind.tag) for r in layout(OcbHeader).rows]
    assert head == [(r.name, r.kind.tag) for r in layout(Ocb).rows][:len(head)]
    assert len(head) == 8 and layout(Ocb).rows[len(head)].name == "satellites"


# --- strategies ----------------------------------------------------------------------------
#
# Values are drawn within their widths only: the codec keeps raw integers
# and does not apply the spec's ranges or special values. Masks have few
# bits set to keep a message inside TF003's 1023 bytes.

def u(bits: int) -> st.SearchStrategy[int]:
    return st.integers(0, (1 << bits) - 1)


@st.composite
def mask(draw, width: int, most: int, least: int = 1) -> int:
    positions = draw(st.sets(st.integers(0, width - 1), min_size=min(least, width),
                             max_size=min(most, width)))
    return sum(1 << (width - 1 - p) for p in positions)


@st.composite
def bias(draw, subtype: int, phase_size=None, code_size=None) -> Bias:
    ps = draw(u(1)) if phase_size is None else phase_size
    pm = draw(mask(PHASE_MASK_BITS[subtype][ps], 3, 0))
    phase = tuple(PhaseBias(draw(u(1)), draw(u(3)), draw(u(14))) for _ in range(pm.bit_count()))
    cs = draw(u(1)) if code_size is None else code_size
    cm = draw(mask(CODE_MASK_BITS[subtype][cs], 3, 0))
    return Bias(ps, pm, phase, cs, cm, tuple(draw(u(11)) for _ in range(cm.bit_count())))


@st.composite
def ocb_satellite(draw, subtype, yaw, dnu=None, present=None, bias_sizes=(None, None)):
    dnu = draw(st.sampled_from([0, 0, 0, 1])) if dnu is None else dnu
    if dnu:
        return OcbSatellite(1, None, None, None, None, None)
    present = draw(u(3)) if present is None else present
    orbit = clock = b = None
    if present & 4:
        orbit = Orbit(draw(u(IODE_BITS[subtype])), draw(u(14)), draw(u(14)), draw(u(14)),
                      draw(u(6)) if yaw else None)
    if present & 2:
        clock = Clock(draw(u(3)), draw(u(14)), draw(u(3)))
    if present & 1:
        b = draw(bias(subtype, *bias_sizes))
    return OcbSatellite(0, present, draw(u(3)), orbit, clock, b)


@st.composite
def ocb(draw, subtype, mask_size=None, yaw=None, **satellite) -> Ocb:
    yaw = draw(u(1)) if yaw is None else yaw
    ms = draw(u(2)) if mask_size is None else mask_size
    m = draw(mask(SAT_MASK_BITS[subtype][ms], 4))
    sats = tuple(draw(ocb_satellite(subtype, yaw, **satellite)) for _ in range(m.bit_count()))
    return Ocb(draw(u(9)), draw(u(1)), draw(u(1)), yaw, draw(u(1)),
               draw(u(EPHEMERIS_BITS[subtype])), ms, m, sats)


def _coefficients(draw, cls, equation, widths):
    c00, linear, c11 = widths
    return cls(draw(u(c00)), draw(u(linear)) if equation >= 1 else None,
               draw(u(linear)) if equation >= 1 else None, draw(u(c11)) if equation == 2 else None)


@st.composite
def troposphere(draw, blocks, grid, equation=None, size=None, residual=None) -> Troposphere:
    eq = draw(st.integers(0, 2)) if equation is None else equation
    cs = draw(u(1)) if size is None else size
    small = _coefficients(draw, TropoSmall, eq, (7, 7, 9)) if cs == 0 else None
    large = _coefficients(draw, TropoLarge, eq, (9, 9, 11)) if cs == 1 else None
    rs = residuals = None
    if blocks == 2:
        rs = draw(u(1)) if residual is None else residual
        residuals = tuple(draw(u((6, 8)[rs])) for _ in range(grid))
    return Troposphere(eq, draw(u(3)), draw(u(8)), cs, small, large, rs, residuals)


@st.composite
def iono_satellite(draw, blocks, grid, equation, size=None, residual=None) -> IonoSatellite:
    cs = draw(u(1)) if size is None else size
    small = _coefficients(draw, IonoSmall, equation, (12, 12, 13)) if cs == 0 else None
    large = _coefficients(draw, IonoLarge, equation, (14, 14, 15)) if cs == 1 else None
    rs = residuals = None
    if blocks == 2:
        rs = draw(u(2)) if residual is None else residual
        residuals = tuple(draw(u((4, 7, 10, 14)[rs])) for _ in range(grid))
    return IonoSatellite(draw(u(4)), cs, small, large, rs, residuals)


@st.composite
def ionosphere(draw, subtype, blocks, grid, equation=None, mask_size=None, size=None,
               residual=None) -> Ionosphere:
    eq = draw(st.integers(0, 2)) if equation is None else equation
    ms = draw(u(2)) if mask_size is None else mask_size
    m = draw(mask(SAT_MASK_BITS[subtype][ms], 3))
    sats = tuple(draw(iono_satellite(blocks, grid, eq, size, residual))
                 for _ in range(m.bit_count()))
    return Ionosphere(eq, ms, m, sats)


@st.composite
def hpac_area(draw, subtype, tropo=None, iono=None, tropo_variant=None,
              iono_variant=None) -> HpacArea:
    tb = draw(st.integers(0, 2)) if tropo is None else tropo
    ib = draw(st.integers(0, 2)) if iono is None else iono
    grid = draw(st.integers(0, 10))
    t = draw(troposphere(tb, grid, **(tropo_variant or {}))) if tb else None
    i = draw(ionosphere(subtype, ib, grid, **(iono_variant or {}))) if ib else None
    return HpacArea(draw(u(8)), grid, tb, ib, t, i)


@st.composite
def hpac(draw, subtype, **area) -> Hpac:
    areas = tuple(draw(hpac_area(subtype, **area)) for _ in range(draw(st.integers(1, 3))))
    return Hpac(draw(u(9)), draw(u(4)), draw(u(1)), len(areas) - 1, areas)


@st.composite
def gad(draw) -> Gad:
    n = draw(st.integers(1, 6))
    areas = tuple(GadArea(draw(u(8)), draw(u(11)), draw(u(12)), draw(u(3)), draw(u(3)),
                          draw(u(5)), draw(u(5))) for _ in range(n))
    return Gad(draw(u(9)), draw(u(4)), draw(u(1)), n - 1, areas)


@st.composite
def bpac(draw) -> Bpac:
    areas = []
    for _ in range(draw(st.integers(1, 4))):
        lat, lon = draw(u(4)), draw(u(4))
        present = draw(mask((lat + 1) * (lon + 1), 12, 0))
        points = []
        for _ in range(present.bit_count()):
            size = draw(u(1))
            points.append(BpacGridPoint(draw(u(4)), size, draw(u((7, 11)[size]))))
        areas.append(BpacArea(draw(u(2)), draw(u(8)), draw(u(9)), lat, lon, draw(u(2)),
                              draw(u(2)), draw(u(12)), present, tuple(points)))
    return Bpac(draw(u(9)), draw(u(1)), draw(u(2)), len(areas) - 1, tuple(areas))


@st.composite
def description(draw, subtype, eaf=0, time_tag_type=None) -> Description:
    tt = draw(u(1)) if time_tag_type is None else time_tag_type
    extra = (draw(u(4)), draw(u(6)), draw(st.integers(0, 1)), draw(u(3))) if eaf else (None,) * 4
    return Description(subtype, tt, draw(u(32 if tt else 16)), draw(u(7)), draw(u(4)), *extra)


@st.composite
def bodies(draw, ocb_options=None):
    kind = draw(st.sampled_from(["ocb", "hpac", "gad", "bpac"]))
    if kind == "gad":
        return 2, 0, draw(gad())
    if kind == "bpac":
        return 3, 0, draw(bpac())
    subtype = draw(st.integers(0, 4))
    if kind == "ocb":
        return 0, subtype, draw(ocb(subtype, **(ocb_options or {})))
    return 1, subtype, draw(hpac(subtype))


@st.composite
def messages(draw, eaf=0, time_tag_type=None, ocb_options=None) -> Message:
    message_type, subtype, body = draw(bodies(ocb_options))
    return Message(message_type, eaf, draw(st.integers(0, 3)),
                   draw(description(subtype, eaf, time_tag_type)), body)


often = settings(max_examples=300, derandomize=True, deadline=None,
                 suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
few = settings(max_examples=4, derandomize=True, deadline=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


# --- Table 8.2 -------------------------------------------------------------------------------

TPC = {0: (7, 21, 30), 1: (9, 27, 38)}      # troposphere coefficient bits by SF044, SF041
IPC = {0: (12, 36, 49), 1: (14, 42, 57)}    # ionosphere coefficient bits by SF056, SF054
TGR, IGR = (6, 8), (4, 7, 10, 14)


def table_8_2_bits(body, subtype: int) -> int:
    if isinstance(body, Gad):
        return 19 + 47 * len(body.areas)
    if isinstance(body, Bpac):
        # HeaderBlock 14; AreaDataBlock 43 + NGp; VTECBlock (5 + Vs) * NGpPrst.
        return 14 + sum(43 + (a.latitude_nodes + 1) * (a.longitude_nodes + 1)
                        + sum(5 + (7, 11)[p.size] for p in a.grid_points) for a in body.areas)
    if isinstance(body, Ocb):
        mnsc = 2 + SAT_MASK_BITS[subtype][body.mask_size]
        total = 13 + EPHEMERIS_BITS[subtype] + mnsc       # "15 + MNsc" with GPS's 2-bit SF016
        for s in body.satellites:
            if s.dnu:
                total += 1                                 # SF013 alone (see OcbSatellite)
                continue
            total += 7
            if s.orbit:
                total += IODE_BITS[subtype] + 42 + 6 * body.yaw_present
            if s.clock:
                total += 20
            if s.bias:
                b = s.bias
                total += (1 + PHASE_MASK_BITS[subtype][b.phase_mask_size] + 18 * len(b.phase)
                          + 1 + CODE_MASK_BITS[subtype][b.code_mask_size] + 11 * len(b.code))
        return total
    total = 19
    for a in body.areas:
        total += 19
        if a.troposphere:
            t = a.troposphere
            total += 15 + TPC[t.coefficient_size][t.equation_type]
            if a.tropo_blocks == 2:
                total += 1 + TGR[t.residual_size] * a.grid_points
        if a.ionosphere:
            i = a.ionosphere
            total += 3 + 2 + SAT_MASK_BITS[subtype][i.mask_size]
            for s in i.satellites:
                total += 5 + IPC[s.coefficient_size][i.equation_type]
                if a.iono_blocks == 2:
                    total += 2 + IGR[s.residual_size] * a.grid_points
    return total


def bits_of(body, subtype: int) -> int:
    w = BitWriter()
    write(body, w, **spartn._params(type(body), subtype, body))
    return w.pos


@often
@given(messages())
def test_sizes_are_table_8_2(message):
    subtype = message.description.subtype
    bits = bits_of(message.body, subtype)
    assert bits == table_8_2_bits(message.body, subtype)
    assert len(spartn.to_frame(message).payload) == (bits + 7) // 8   # TF016 fill bits


# --- round trip ------------------------------------------------------------------------------

def round_trip(message: Message) -> None:
    raw = spartn.encode(message)
    frame = spartn.parse(raw)
    assert isinstance(frame, spartn.Frame), frame
    assert spartn.decode(frame) == message
    assert spartn.encode(spartn.decode(frame)) == raw


@often
@given(messages())
def test_generated_messages_round_trip(message):
    round_trip(message)


def _wrap(message_type, subtype, body, data):
    return Message(message_type, 0, data.draw(st.integers(0, 3)),
                   data.draw(description(subtype)), body)


TROPO_VARIANTS = ([(1, dict(equation=e, size=s)) for e in range(3) for s in range(2)]
                  + [(2, dict(equation=e, size=s, residual=r))
                     for e in range(3) for s in range(2) for r in range(2)])
IONO_VARIANTS = ([(1, dict(equation=e, size=s)) for e in range(3) for s in range(2)]
                 + [(2, dict(equation=e, size=s, residual=r))
                    for e in range(3) for s in range(2) for r in range(4)])


@pytest.mark.parametrize(("blocks", "variant"), TROPO_VARIANTS)
@few
@given(data=st.data())
def test_every_troposphere_block_round_trips(blocks, variant, data):
    body = data.draw(hpac(0, tropo=blocks, iono=0, tropo_variant=variant))
    t = body.areas[0].troposphere
    assert (t.equation_type, t.coefficient_size, t.residual_size) == (
        variant["equation"], variant["size"], variant.get("residual"))
    round_trip(_wrap(1, 0, body, data))


@pytest.mark.parametrize(("blocks", "variant"), IONO_VARIANTS)
@few
@given(data=st.data())
def test_every_ionosphere_block_round_trips(blocks, variant, data):
    body = data.draw(hpac(2, tropo=0, iono=blocks, iono_variant=variant))
    i = body.areas[0].ionosphere
    assert i.equation_type == variant["equation"]
    assert all((s.coefficient_size, s.residual_size) == (variant["size"], variant.get("residual"))
               for s in i.satellites)
    round_trip(_wrap(1, 2, body, data))


@pytest.mark.parametrize("subtype", range(5))
@pytest.mark.parametrize("mask_size", range(4))
@few
@given(data=st.data())
def test_every_constellation_and_mask_size_round_trips(subtype, mask_size, data):
    round_trip(_wrap(0, subtype, data.draw(ocb(subtype, mask_size)), data))
    body = data.draw(hpac(subtype, iono=data.draw(st.integers(1, 2)),
                          iono_variant=dict(mask_size=mask_size)))
    round_trip(_wrap(1, subtype, body, data))


@pytest.mark.parametrize("subtype", range(5))
@pytest.mark.parametrize("present", range(8))
@pytest.mark.parametrize("bias_sizes", [(0, 0), (0, 1), (1, 0), (1, 1)])
@few
@given(data=st.data())
def test_every_satellite_block_round_trips(subtype, present, bias_sizes, data):
    body = data.draw(ocb(subtype, yaw=present & 1, dnu=0, present=present,
                         bias_sizes=bias_sizes))
    round_trip(_wrap(0, subtype, body, data))
    assert all(s.present == present for s in body.satellites)


@few
@given(data=st.data())
def test_gad_and_dnu_round_trip(data):
    round_trip(_wrap(2, 0, data.draw(gad()), data))
    round_trip(_wrap(0, 3, data.draw(ocb(3, dnu=1)), data))


# --- hand-built payloads -----------------------------------------------------------------------

def assemble(fields: list[tuple[int, int]]) -> bytes:
    w = BitWriter()
    for value, bits in fields:
        w.uint(value, bits)
    return w.to_bytes()


def frame_of(message_type: int, subtype: int, payload: bytes) -> spartn.Frame:
    d = Description(subtype, 1, 1000, 1, 2, None, None, None, None)
    return spartn.parse(spartn.encode_frame(message_type, 0, 2, d, payload))


def test_hand_built_gad():
    # Table 6.23 then two Table 6.24 blocks; SF030 = 1 for two areas.
    payload = assemble([(300, 9), (7, 4), (0, 1), (1, 5),
                        (17, 8), (1294, 11), (2817, 12), (3, 3), (4, 3), (9, 5), (11, 5),
                        (18, 8), (1300, 11), (2830, 12), (7, 3), (0, 3), (31, 5), (0, 5)])
    assert len(payload) == (19 + 2 * 47 + 7) // 8
    m = spartn.decode(frame_of(2, 0, payload))
    assert m.body == Gad(300, 7, 0, 1, (GadArea(17, 1294, 2817, 3, 4, 9, 11),
                                        GadArea(18, 1300, 2830, 7, 0, 31, 0)))
    assert spartn.encode(m) == spartn.encode(frame_of(2, 0, payload))


def test_hand_built_hpac_with_grids():
    # One area, GPS (subtype 0), two grid points, both blocks indicators 2:
    # troposphere equation 1, large coefficients, large residuals; ionosphere
    # equation 2, a 32-bit mask with PRN 3, small coefficients, extra-large residuals.
    payload = assemble([
        (511, 9), (15, 4), (0, 1), (0, 5),                 # Table 6.13
        (200, 8), (2, 7), (2, 2), (2, 2),                  # Table 6.15
        (1, 3), (4, 3), (128, 8), (1, 1),                  # Table 6.16
        (300, 9), (301, 9), (302, 9),                      # Table 6.18, T00 T01 T10
        (1, 1), (255, 8), (0, 8),                          # SF051, two SF053
        (2, 3), (0, 2), (1 << 29, 32),                     # Table 6.19
        (9, 4), (0, 1),                                    # Table 6.20
        (1000, 12), (1001, 12), (1002, 12), (4000, 13),    # Table 6.21, C00 C01 C10 C11
        (3, 2), (16383, 14), (1, 14),                      # SF063, two SF067
    ])
    m = spartn.decode(frame_of(1, 0, payload))
    tropo = Troposphere(1, 4, 128, 1, None, TropoLarge(300, 301, 302, None), 1, (255, 0))
    iono = Ionosphere(2, 0, 1 << 29, (IonoSatellite(9, 0, IonoSmall(1000, 1001, 1002, 4000),
                                                    None, 3, (16383, 1)),))
    assert m.body == Hpac(511, 15, 0, 0, (HpacArea(200, 2, 2, 2, tropo, iono),))


def test_hand_built_ocb_with_dnu():
    # GLONASS (subtype 1): a 24-bit mask with slots 1 and 2; slot 1 is DNU
    # (SF013 alone), slot 2 has orbit and clock, no yaw.
    payload = assemble([
        (5, 9), (1, 1), (0, 1), (0, 1), (1, 1), (3, 2), (0, 2), (0b11 << 22, 24),
        (1, 1),                                            # DNU
        (0, 1), (0b110, 3), (5, 3),                        # Table 6.4
        (100, 7), (1, 14), (2, 14), (3, 14),               # Table 6.5, 7-bit SF019
        (6, 3), (4, 14), (1, 3),                           # Table 6.6
    ])
    m = spartn.decode(frame_of(0, 1, payload))
    assert m.body == Ocb(5, 1, 0, 0, 1, 3, 0, 0b11 << 22, (
        OcbSatellite(1, None, None, None, None, None),
        OcbSatellite(0, 0b110, 5, Orbit(100, 1, 2, 3, None), Clock(6, 4, 1), None)))


@pytest.mark.parametrize("size", [0, 1])
def test_hand_built_ocb_with_galileo_e5_and_e6_biases(size):
    # SPARTN v2.0.3 Table 6.2, SF102 and SF105: bits 3 and 4 are L8Q and L6C
    # phase biases and C8Q and C6C code biases (v2.0.2 left them spare), in
    # the same 8- or 15-bit masks. Galileo (subtype 2): a 36-bit satellite
    # mask with PRN 1, whose satellite has a bias block only, with those two
    # bits set in each mask: two phase bias blocks and two code biases.
    width = (8, 15)[size]
    bits_3_and_4 = 0b11 << (width - 5)
    payload = assemble([
        (9, 9), (0, 1), (0, 1), (0, 1), (0, 1), (1, 3), (0, 2), (1 << 35, 36),   # Table 6.3
        (0, 1), (0b001, 3), (2, 3),                                         # Table 6.4
        (size, 1), (bits_3_and_4, width),                                   # Table 6.9, SF102
        (1, 1), (2, 3), (300, 14), (0, 1), (5, 3), (16383, 14),             # Table 6.12, twice
        (size, 1), (bits_3_and_4, width), (7, 11), (2047, 11),              # SF105, two SF029
    ])
    frame = frame_of(0, 2, payload)
    m = spartn.decode(frame, strict=True)
    bias = Bias(size, bits_3_and_4, (PhaseBias(1, 2, 300), PhaseBias(0, 5, 16383)),
                size, bits_3_and_4, (7, 2047))
    assert m.body == Ocb(9, 0, 0, 0, 0, 1, 0, 1 << 35,
                         (OcbSatellite(0, 0b001, 2, None, None, bias),))
    assert spartn.encode(m) == spartn.encode(frame)


# --- refusals --------------------------------------------------------------------------------

GOOD_AREA = HpacArea(1, 0, 1, 1, Troposphere(0, 0, 0, 0, TropoSmall(1, None, None, None), None,
                                             None, None),
                     Ionosphere(0, 0, 1 << 31, (IonoSatellite(0, 0, IonoSmall(1, None, None, None),
                                                              None, None, None),)))


def _hpac_payload(area: HpacArea) -> bytes:
    return spartn.to_frame(Message(1, 0, 2, Description(0, 1, 0, 0, 0, None, None, None, None),
                                   Hpac(0, 0, 0, 0, (area,)))).payload


def test_undefined_layouts_are_refused():
    good = _hpac_payload(GOOD_AREA)
    assert spartn.decode(frame_of(1, 0, good)).body.areas[0] == GOOD_AREA
    # The area data block starts at bit 19: SF031 (8), SF039 (7), then the two SF040.
    for at, value in [(34, 3), (36, 3)]:          # SF040 = 3 is not defined
        raw = bytearray(good)
        as_int = int.from_bytes(raw, "big") | (value << (8 * len(raw) - at - 2))
        with pytest.raises(BitError):
            spartn.decode(frame_of(1, 0, as_int.to_bytes(len(raw), "big")))
    for equation in range(3, 8):                  # SF041 and SF054 3 to 7 are TBD
        t = replace(GOOD_AREA.troposphere, equation_type=equation)
        i = replace(GOOD_AREA.ionosphere, equation_type=equation)
        for area in (replace(GOOD_AREA, troposphere=t), replace(GOOD_AREA, ionosphere=i)):
            with pytest.raises(BitError):
                _hpac_payload(area)
        # and on the wire: patch the 3-bit tropo equation type at bit 38
        raw = int.from_bytes(good, "big") | (equation << (8 * len(good) - 38 - 3))
        with pytest.raises(BitError):
            spartn.decode(frame_of(1, 0, raw.to_bytes(len(good), "big")))


@pytest.mark.parametrize(("message_type", "subtype"), [(0, 5), (1, 15), (2, 1), (3, 1), (4, 0),
                                                       (4, 1), (120, 1)])
def test_unsupported(message_type, subtype):
    with pytest.raises(Unsupported):
        spartn.decode(frame_of(message_type, subtype, b"\0" * 8))


def test_data_after_the_table_is_kept():
    # Section 8.4 item 4: reserved bits "may be used to extend message content
    # at the end of the payload", so a decoder "should not use payload length
    # to indicate where they stop decoding". decode keeps what follows the
    # table in ``extension`` and encode writes it back; strict=True refuses it.
    gad_body = Gad(0, 0, 0, 0, (GadArea(1, 2, 3, 4, 5, 6, 7),))
    good = spartn.to_frame(Message(2, 0, 2, Description(0, 1, 0, 0, 0, None, None, None, None),
                                   gad_body)).payload
    assert len(good) == 9 and good[-1] & 0x3F == 0      # 66 bits: six fill bits
    cases = {good + b"\0": Extension(14, 0), good + b"\x81\x7e": Extension(22, 0x817E),
             good[:-1] + bytes((good[-1] | 0x3F,)): Extension(6, 0x3F)}
    for payload, extension in cases.items():
        frame = frame_of(2, 0, payload)
        message = spartn.decode(frame)
        assert message.body == replace(gad_body, extension=extension)
        assert spartn.encode(message) == spartn.encode(frame)
        with pytest.raises(spartn.FieldError, match="left over" if extension.bits > 8 else "fill"):
            spartn.decode(frame, strict=True)
    assert spartn.decode(frame_of(2, 0, good), strict=True).body == gad_body
    with pytest.raises(spartn.FieldError):
        spartn.decode(frame_of(2, 0, good[:-1]))


# --- the two readings of a DNU satellite (OcbSatellite) ------------------------------------

def _dnu_ocb_payload(reading: int) -> tuple[Ocb, bytes]:
    # GPS: satellites 1, 2 and 3; satellite 2 is DNU, and under Table 8.2's
    # reading it keeps SF014 = 0 and SF015 = 4. Satellite 3 has a clock block.
    dnu = (OcbSatellite(1, 0, 4, None, None, None) if reading
           else OcbSatellite(1, None, None, None, None, None))
    body = Ocb(9, 1, 0, 0, 0, 1, 0, 0b111 << 29,
               (OcbSatellite(0, 0b010, 3, None, Clock(1, 8191, 2), None), dnu,
                OcbSatellite(0, 0b010, 3, None, Clock(2, 4000, 7), None)))
    payload = spartn.to_frame(Message(0, 0, 2, Description(0, 1, 1, 1, 1, None, None, None,
                                                           None), body)).payload
    return body, payload


def test_dnu_reading_of_table_6_2_is_the_default():
    body, payload = _dnu_ocb_payload(spartn.DNU_TABLE_6_2)
    # 13 + 2 + 2 + 32 header bits, then 7 + 20, 1, 7 + 20.
    assert len(payload) == (49 + 27 + 1 + 27 + 7) // 8
    message = spartn.decode(frame_of(0, 0, payload))
    assert message.body == body and spartn.dnu_reading(message.body) == spartn.DNU_TABLE_6_2
    assert spartn.decode(frame_of(0, 0, payload), strict=True).body == body


def test_dnu_reading_of_table_8_2_is_reported_when_the_length_shows_it():
    # A payload laid out by Table 8.2's reading (six more bits for the DNU
    # satellite) misreads under Table 6.2's; the tolerant decode then tries
    # Table 8.2's, which fits the payload exactly, and returns it.
    body, payload = _dnu_ocb_payload(spartn.DNU_TABLE_8_2)
    assert len(payload) == (49 + 27 + 7 + 27 + 7) // 8
    frame = frame_of(0, 0, payload)
    message = spartn.decode(frame)
    assert message.body == body and spartn.dnu_reading(message.body) == spartn.DNU_TABLE_8_2
    assert spartn.encode(message) == spartn.encode(frame)
    with pytest.raises(spartn.FieldError):
        spartn.decode(frame, strict=True)          # strict: Table 6.2 only


def test_dnu_reading_without_a_dnu_satellite_is_not_taken():
    # Data after a table with no DNU satellite stays an extension.
    body, payload = _dnu_ocb_payload(spartn.DNU_TABLE_6_2)
    plain = replace(body, satellites=body.satellites[:1], mask=0b1 << 31)
    raw = spartn.to_frame(Message(0, 0, 2, Description(0, 1, 1, 1, 1, None, None, None, None),
                                  plain)).payload + b"\x12"
    message = spartn.decode(frame_of(0, 0, raw))
    assert message.body.extension is not None
    assert spartn.dnu_reading(message.body) == spartn.DNU_TABLE_6_2


# --- OCB header block of any subtype (section 8.4 item 5) ---------------------------------

@pytest.mark.parametrize("subtype", range(16))
def test_ocb_header_of_any_subtype(subtype):
    # SF005 = 300, SF010 = 1, SF069 = 0, SF008 = 1, SF009 = 0, then for a
    # known subtype its ephemeris type and satellite mask, then anything.
    fields = [(300, 9), (1, 1), (0, 1), (1, 1), (0, 1)]
    if subtype < 5:
        fields += [(1, EPHEMERIS_BITS[subtype]), (1, 2), (1, SAT_MASK_BITS[subtype][1])]
    payload = assemble(fields) + b"\xff" * 30          # satellite blocks not read
    header = spartn.decode_ocb_header(frame_of(0, subtype, payload))
    known = (1, 1, 1) if subtype < 5 else (None, None, None)
    assert header == OcbHeader(300, 1, 0, 1, 0, *known)
    if subtype < 5:
        body = spartn.decode(spartn.parse(spartn.encode(
            Message(0, 0, 2, Description(subtype, 1, 5, 1, 1, None, None, None, None),
                    Ocb(300, 1, 0, 1, 0, 1, 1, 1, (OcbSatellite(1, None, None, None, None,
                                                                None),))))))
        assert spartn.decode_ocb_header(spartn.to_frame(body)) == header


def test_ocb_header_refusals():
    with pytest.raises(Unsupported):
        spartn.decode_ocb_header(frame_of(1, 0, b"\0" * 8))
    with pytest.raises(spartn.FieldError):
        spartn.decode_ocb_header(frame_of(0, 0, b"\0"))
    d = Description(0, 1, 0, 0, 0, 0, 0, 0, 0)
    encrypted = spartn.parse(spartn.encode_frame(0, 1, 2, d, b"\0" * 12))
    with pytest.raises(Encrypted):
        spartn.decode_ocb_header(encrypted)
    assert spartn.decode_ocb_header(spartn.decrypt(encrypted, KEY)).siou is not None


# --- BPAC, SM 3-0 -------------------------------------------------------------------------

def test_hand_built_bpac():
    # Table 6.25, then one area (SF071 = 0): Table 6.27 with a 2 x 3 grid
    # (SF075 = 1, SF076 = 2: six grid points, SF079 six bits) of which the
    # first and the last are present, each with its Table 6.28 block.
    payload = assemble([
        (77, 9), (0, 1), (2, 2), (0, 2),                   # Table 6.25
        (3, 2), (130, 8), (300, 9), (1, 4), (2, 4),        # Table 6.27: SF072 to SF076
        (1, 2), (3, 2), (2047, 12), (0b100001, 6),         # SF077, SF078, SF080, SF079
        (8, 4), (0, 1), (0x7F, 7),                         # Table 6.28, small residual
        (2, 4), (1, 1), (1000, 11),                        # Table 6.28, large residual
    ])
    assert len(payload) * 8 - (14 + 43 + 6 + 12 + 16) < 8     # Table 8.2
    m = spartn.decode(frame_of(3, 0, payload))
    assert m.body == Bpac(77, 0, 2, 0, (BpacArea(3, 130, 300, 1, 2, 1, 3, 2047, 0b100001, (
        BpacGridPoint(8, 0, 0x7F), BpacGridPoint(2, 1, 1000))),))
    assert spartn.encode(m) == spartn.encode(frame_of(3, 0, payload))


def test_bpac_largest_grid_has_a_256_bit_mask():
    points = tuple(BpacGridPoint(1, 0, 5) for _ in range(256))
    area = BpacArea(0, 0, 0, 15, 15, 0, 0, 0, (1 << 256) - 1, points)
    body = Bpac(0, 0, 0, 0, (area,))
    m = Message(3, 0, 2, Description(0, 1, 0, 0, 0, None, None, None, None), body)
    assert bits_of(body, 0) == 14 + 43 + 256 + 256 * 12
    assert spartn.decode(spartn.parse(spartn.encode(m))) == m


def test_encode_refuses():
    d = Description(0, 1, 0, 0, 0, None, None, None, None)
    gad_body = Gad(0, 0, 0, 0, (GadArea(1, 2, 3, 4, 5, 6, 7),))
    with pytest.raises(TypeError):
        spartn.encode(Message(0, 0, 2, d, gad_body))     # a GAD body under SM 0-0
    with pytest.raises(TypeError):
        spartn.encode(object())
    with pytest.raises(BitError):
        spartn.encode(Message(2, 0, 2, d, replace(gad_body, area_count=1)))
    enc = Description(0, 1, 0, 0, 0, 0, 0, 0, 0)
    with pytest.raises(Encrypted):
        spartn.encode(Message(2, 1, 2, enc, gad_body))   # plain text with EAF set


# --- encryption ------------------------------------------------------------------------------

KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")   # a test key, not a service's


def iv_by_hand(message_type, length, subtype, time_tag, solution, processor, enc_id, seq) -> bytes:
    """Section 8.15.1, items a to i, as one integer shifted into 96 bits."""
    value = 0
    for v, n in ((message_type, 7), (length, 10), (subtype, 4), (time_tag, 32), (solution, 7),
                 (processor, 4), (enc_id, 4), (seq, 6)):
        value = (value << n) | v
    return (value << (96 - 74)).to_bytes(12, "big")


def test_iv_is_section_8_15_1():
    d = Description(3, 1, 0x89AB_CDEF, 0x55, 0xA, 0x6, 0x2A, 1, 0)
    frame = replace(spartn.to_frame(Message(0, 1, 2, d, spartn.Ocb(
        0, 0, 0, 0, 0, 0, 0, 1 << 36, (OcbSatellite(1, None, None, None, None, None),)))),
        decrypted=False)
    assert spartn.iv(frame) == iv_by_hand(0, len(frame.payload), 3, 0x89AB_CDEF, 0x55, 0xA, 6, 42)
    short = replace(frame, description=replace(d, time_tag_type=0, time_tag=7))
    with pytest.raises(ValueError, match="32-bit"):
        spartn.iv(short)
    with pytest.raises(spartn.TimeTagError, match="16-bit tag is 7"):
        spartn.iv(short, 0x89AB_CDEF)            # 0x89ABCDEF % 43200 is not 7
    full = 0x89AB_CDEF - 0x89AB_CDEF % spartn.HALF_DAY + 7
    assert spartn.iv(short, full) == iv_by_hand(0, len(frame.payload), 3, full, 0x55, 0xA, 6, 42)
    with pytest.raises(spartn.TimeTagError, match="differs"):
        spartn.iv(frame, 0x89AB_CDEE)
    for bad in (-1, 1 << 32, True, 7.0):
        with pytest.raises(spartn.TimeTagError):
            spartn.iv(short, bad)
    with pytest.raises(Encrypted):
        spartn.iv(replace(frame, eaf=0))


def test_a_full_tag_that_contradicts_the_half_day_tag_is_refused():
    # TF009: the 16-bit tag is the second of the half day (0 to 43,199), the
    # 32-bit one seconds since 2010-01-01 00:00:00, a half-day boundary; so
    # full % 43200 must be the frame's tag. 0.1.0 accepted any full tag and
    # decrypted to garbage.
    d = Description(0, 0, 1234, 0, 0, 0, 0, 0, 0)
    cipher = spartn.parse(spartn.encode_frame(2, 1, 2, d, b"\x01" * 20))
    for wrong in (999, 1235, 1234 + 43_199):
        with pytest.raises(spartn.TimeTagError):
            spartn.decrypt(cipher, KEY, wrong)
    for right in (1234, 1234 + 43_200 * 9_000):
        plain = spartn.decrypt(cipher, KEY, right)
        assert spartn.encrypt(plain, KEY, right) == cipher
        with pytest.raises(spartn.TimeTagError):
            spartn.encrypt(plain, KEY, right + 1)


@often
@given(messages(eaf=1, time_tag_type=1))
def test_encrypt_round_trip_and_cryptography_agrees(message):
    plain = spartn.to_frame(message)
    with pytest.raises(Encrypted):
        spartn.encode(plain)
    raw = spartn.encode(spartn.encrypt(plain, KEY))
    frame = spartn.parse(raw)
    assert isinstance(frame, spartn.Frame)
    with pytest.raises(Encrypted):
        spartn.decode(frame)
    assert spartn.decode(spartn.decrypt(frame, KEY)) == message
    assert spartn.encode(spartn.encrypt(spartn.decrypt(frame, KEY), KEY)) == raw
    # AES-128-CTR with counter block IV || 00000001, from an independent library.
    counter = spartn.iv(frame) + (1).to_bytes(4, "big")
    other = Cipher(algorithms.AES(KEY), modes.CTR(counter)).decryptor()
    assert other.update(frame.payload) + other.finalize() == plain.payload


def test_decrypt_refusals():
    d = Description(0, 0, 100, 0, 0, 0, 0, 0, 0)
    plain = spartn.to_frame(Message(2, 1, 2, d, Gad(0, 0, 0, 0, (GadArea(1, 2, 3, 4, 5, 6, 7),))))
    with pytest.raises(ValueError, match="32-bit"):
        spartn.encrypt(plain, KEY)
    full = 100 + 25 * spartn.HALF_DAY                     # the frame's tag is 100
    cipher = spartn.encrypt(plain, KEY, full)
    with pytest.raises(Encrypted):
        spartn.encrypt(cipher, KEY, full)
    with pytest.raises(Encrypted):
        spartn.decrypt(spartn.decrypt(cipher, KEY, full), KEY, full)
    with pytest.raises(ValueError, match="16-byte"):
        spartn.decrypt(cipher, bytes(32), full)
    dynamic_key = replace(cipher, message_type=4, description=replace(d, subtype=0))
    with pytest.raises(Unsupported):
        spartn.decrypt(dynamic_key, KEY, full)


# --- cross-check with pyspartn -----------------------------------------------------------------
#
# pyspartn 1.1.2 names fields by SF number (SF020R_01, SF052_01_03...),
# splits SF014 into its three flags, names the mask size bits
# SatBitmaskLen, PhaseBiasBitmaskLen and CodeBiasBitmaskLen, and scales
# many fields to physical units. So the two sides are compared as the
# sequence of SF numbers in wire order; unscaled values must be equal, and
# for a scaled field ``theirs - ours * resolution`` (resolutions from Table
# 6.2) must be one constant across all frames compared.
#
# Two disagreements were found and are kept out of the generated frames
# here: pyspartn refuses every OCB frame with an extended
# (size bit 1) phase or code bias mask, and (as this codec now does) reads a
# DNU satellite as SF013 alone.

RESOLUTION = {"SF020": .002, "SF021": 6, "SF029": .02, "SF032": .1, "SF033": .1, "SF036": .1,
              "SF037": .1, "SF043": .004, "SF045": .004, "SF046": .001, "SF047": .0002,
              "SF048": .004, "SF049": .001, "SF050": .0002, "SF052": .004, "SF053": .004,
              "SF057": .04, "SF058": .008, "SF059": .002, "SF060": .04, "SF061": .008,
              "SF062": .002, "SF064": .04, "SF065": .04, "SF066": .04, "SF067": .04,
              "SF073": 1, "SF074": 1, "SF080": .25, "SF082": .25, "SF083": .25}
# Fields Table 6.2 gives as a list of values; the oracle may report the value or the index.
LISTED = {"SF077": (2.5, 5.0, 10.0, 15.0), "SF078": (2.5, 5.0, 10.0, 15.0)}
# Fields whose all-ones value is "invalid" (Table 6.2); the oracle may report those otherwise.
INVALID = {"SF021": 63, "SF052": 63, "SF053": 255, "SF064": 15, "SF065": 127, "SF066": 1023,
           "SF067": 16383, "SF082": 127, "SF083": 2047}
SIZE_KEYS = {"mask_size": "SatBitmaskLen", "phase_mask_size": "PhaseBiasBitmaskLen",
             "code_mask_size": "CodeBiasBitmaskLen"}


def ours_flat(body, subtype: int) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []

    def walk(obj, lay):
        for row in lay.rows:
            value = getattr(obj, row.name)
            if value is None:
                continue
            if row.group is not None:
                for item in value if isinstance(value, tuple) else (value,):
                    walk(item, row.group)
                continue
            tag = row.kind.tag
            if row.name in SIZE_KEYS:
                key = SIZE_KEYS[row.name]
            elif "/" in tag:
                options = tag.split("/")
                if len(options) == 5:
                    key = options[subtype]
                elif isinstance(obj, BpacGridPoint):
                    key = options[obj.size]
                else:
                    key = options[obj.residual_size]
            else:
                key = tag
            for v in value if isinstance(value, tuple) else (value,):
                if key == "SF014":
                    out.extend([("SF014", v >> 2 & 1), ("SF014", v >> 1 & 1), ("SF014", v & 1)])
                else:
                    out.append((key, v))
    walk(body, layout(type(body)))
    return out


def theirs_flat(parsed) -> list[tuple[str, object]]:
    out = []
    for name, value in vars(parsed).items():
        base = name.split("_")[0]
        if base in SIZE_KEYS.values():
            out.append((base, value))
        elif base.startswith("SF"):
            out.append((base[:5], value))
    return out


HEADER = {"msgType": "message_type", "eaf": "eaf", "crcType": "crc_type"}
DESCRIPTION = {"msgSubtype": "subtype", "timeTagtype": "time_tag_type",
               "gnssTimeTag": "time_tag", "solutionId": "solution_id",
               "solutionProcId": "processor_id"}


class Agreement:
    """Collects the per-field offsets of scaled values across many frames."""

    def __init__(self) -> None:
        self.offsets: dict[str, list[float]] = defaultdict(list)
        self.frames = 0

    def check(self, message: Message, raw: bytes, **oracle) -> None:
        parsed = pyspartn.SPARTNReader.parse(raw, decode=True, **oracle)
        for theirs, ours in HEADER.items():
            assert getattr(parsed, theirs) == getattr(message, ours), theirs
        for theirs, ours in DESCRIPTION.items():
            assert getattr(parsed, theirs) == getattr(message.description, ours), theirs
        mine = ours_flat(message.body, message.description.subtype)
        other = theirs_flat(parsed)
        assert [k for k, _ in mine] == [k for k, _ in other]
        for (key, a), (_, b) in zip(mine, other):
            if key in INVALID and a == INVALID[key]:
                continue
            if key in RESOLUTION:
                self.offsets[key].append(b - a * RESOLUTION[key])
            elif key in LISTED:
                assert b in (a, LISTED[key][a]), (key, a, b)
            else:
                assert a == b, (key, a, b)
        self.frames += 1

    def settle(self) -> None:
        for key, seen in self.offsets.items():
            assert max(seen) - min(seen) < 1e-6, (key, min(seen), max(seen))


oracle_settings = settings(max_examples=150, derandomize=True, deadline=None,
                           suppress_health_check=[HealthCheck.too_slow,
                                                  HealthCheck.data_too_large])


@oracle_settings
@given(st.lists(messages(time_tag_type=1, ocb_options=dict(bias_sizes=(0, 0))),
                min_size=1, max_size=4))
def test_pyspartn_decodes_our_frames_alike(batch):
    agreement = Agreement()
    for message in batch:
        agreement.check(message, spartn.encode(message))
    agreement.settle()


@oracle_settings
@given(messages(eaf=1, ocb_options=dict(bias_sizes=(0, 0))), st.integers(0, 99_000))
def test_pyspartn_decrypts_our_frames_alike(message, half_days):
    # A 16-bit tag is expanded by the caller (section 8.15.1), here as the
    # same second in a later half day; pyspartn takes the expanded tag as
    # its "basedate". Both sides then build the same IV.
    # A 16-bit tag of 43200 or more is no second of a half day, so no
    # full tag agrees with it and spartn.iv refuses it.
    d = message.description
    assume(d.time_tag_type or d.time_tag < 43_200)
    full = d.time_tag if d.time_tag_type else half_days * 43_200 + d.time_tag
    raw = spartn.encode(spartn.encrypt(spartn.to_frame(message), KEY,
                                       None if d.time_tag_type else full))
    oracle = {"key": KEY.hex()} | ({} if d.time_tag_type else {"basedate": full})
    Agreement().check(message, raw, **oracle)


def test_pyspartn_sees_the_dnu_reading():
    # With DNU set the satellite block is SF013 alone (OcbSatellite); pyspartn
    # reads the same bits so.
    sats = (OcbSatellite(1, None, None, None, None, None),
            OcbSatellite(0, 2, 7, None, Clock(7, 8191, 2), None))
    m = Message(0, 0, 2, Description(0, 1, 1000, 1, 2, None, None, None, None),
                Ocb(1, 0, 0, 0, 0, 0, 0, 0b11 << 30, sats))
    a = Agreement()
    a.check(m, spartn.encode(m))
    a.settle()


# --- private captures ------------------------------------------------------------------------
#
# build/private/ (gitignored, never committed) may hold unencrypted SPARTN
# streams (spartn_ip_*.bin) and UBX recordings of RXM-PMP frames carrying
# an encrypted SPARTN stream (pmp_*.bin). Nothing from these files is
# copied into the repository. They stand in for a public unencrypted
# sample, which was not found.

PRIVATE = Path(__file__).resolve().parents[3] / "build" / "private"
private = pytest.mark.skipif(not PRIVATE.is_dir(),
                             reason="private captures (build/private/) are absent")


def private_frames():
    for path in sorted(PRIVATE.glob("spartn_ip_*.bin")):
        stream = path.read_bytes()
        for frame in spartn.scan(stream):
            yield path.name, frame, stream[frame.offset:frame.offset + frame.length]


@private
def test_private_ip_frames_decode_round_trip_and_agree_with_pyspartn():
    seen, failures = defaultdict(int), []
    agreement = Agreement()
    for name, frame, raw in private_frames():
        try:
            message = spartn.decode(frame)
        except spartn.Error as exc:
            failures.append((name, frame.offset, str(exc)))
            continue
        if spartn.encode(message) != raw:
            failures.append((name, frame.offset, "round trip"))
            continue
        seen[(frame.message_type, frame.description.subtype)] += 1
        basedate = None
        if frame.description.time_tag_type == 0:
            # pyspartn wants a date to resolve the half-day tag; any will do
            # for decoding without a key.
            basedate = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        agreement.check(message, raw, **({"basedate": basedate} if basedate else {}))
    agreement.settle()
    assert not failures, failures[:10]
    assert seen and set(seen) <= set(spartn.MESSAGES)


@private
def test_private_ip_frames_have_no_extension_and_a_header_everywhere():
    for _, frame, _ in private_frames():
        message = spartn.decode(frame, strict=True)
        assert message.body.extension is None
        if frame.message_type == 0:
            header = spartn.decode_ocb_header(frame)
            assert header.end_of_set == message.body.end_of_set


@private
def test_private_lband_frames_are_encrypted():
    from gnsswire import ubx
    frames = []
    for path in sorted(PRIVATE.glob("pmp_*.bin")):
        stream = b"".join(ubx.decode(f).user_data for f in ubx.scan(path.read_bytes()))
        frames += [f for f in spartn.scan(stream) if f.eaf]
    assert frames
    for f in frames:
        with pytest.raises(Encrypted):
            spartn.decode(f)
