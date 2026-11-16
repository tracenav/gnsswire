"""GPS LNAV (IS-GPS-200N with IRN-IS-200N-003 and IRN-IS-200N-004, section 20.3): parity, bit
layout, Data ID, round trips, assembly."""

from __future__ import annotations

import dataclasses
import random

import pytest

from gnsswire import rtcm3, skytraq
from gnsswire.bits import layout
from gnsswire.nav import FieldError, ParityError, gps

rng = random.Random(200)


def rand(cls, **fixed):
    values = {}
    for row in layout(cls).rows:
        kind = row.kind
        w = kind.width.eval(lambda n: 0)
        n = None if kind.count is None else kind.count.eval(lambda n: 0)
        signed = type(kind).__name__ == "S"

        def one():
            v = rng.getrandbits(w)
            return v - (1 << w) if signed and v >> (w - 1) else v
        values[row.name] = one() if n is None else tuple(one() for _ in range(n))
    values.update(fixed)
    return cls(**values)


def header(subframe: int, **kw):
    return dict(preamble=gps.PREAMBLE, subframe=subframe, **kw)


# --- parity (section 20.3.5, Table 20-XIV) ------------------------------------------------

def test_round_trip_of_random_subframes():
    for cls in (gps.Subframe1, gps.Subframe2, gps.Subframe3, gps.Subframe4Page18,
                gps.Subframe4Page25, gps.Subframe5Page25):
        fixed = header(cls.SUBFRAME)
        if hasattr(cls, "SV_ID"):
            fixed.update(sv_id=cls.SV_ID, data_id=gps.DATA_ID)
        for _ in range(20):
            sf = rand(cls, **fixed)
            words = gps.encode(sf)
            assert all(0 <= w < 1 << 30 for w in words)
            assert gps.decode(words) == sf
            assert gps.decode_data(gps.encode_data(sf)) == sf


def test_every_single_bit_error_is_detected():
    # The (32,26) Hamming code of Table 20-XIV has distance 4 within a word, and a
    # flipped D29 or D30 changes how the next word is read: each flip must fail.
    sf = gps.solve_t(rand(gps.Subframe1, **header(1)))
    words = list(gps.encode(sf))
    for i in range(10):
        for bit in range(30):
            bad = words.copy()
            bad[i] ^= 1 << bit
            with pytest.raises(ParityError):
                gps.decode(bad)


def test_data_bits_are_complemented_after_d30_star():
    # "D1 ... D24 ... are complemented when D30* is 1" (20.3.5.2): word 2 after a word 1
    # whose D30 is 1 carries the complement of its source bits.
    for _ in range(50):
        data = rng.getrandbits(240)
        words = gps.words_from_data(data)
        for k in range(1, 10):
            d = (data >> (24 * (9 - k))) & 0xFFFFFF
            expect = d ^ 0xFFFFFF if words[k - 1] & 1 else d
            assert words[k] >> 6 == expect
        assert gps.data_from_words(words) == data


def test_solve_t_zeroes_d29_d30_of_words_2_and_10():
    for cls in (gps.Subframe1, gps.Subframe2, gps.Subframe3):
        for _ in range(20):
            words = gps.encode(gps.solve_t(rand(cls, **header(cls.SUBFRAME))))
            assert words[1] & 3 == 0 and words[9] & 3 == 0


def test_words_not_ten_30_bit():
    with pytest.raises(FieldError):
        gps.decode([0] * 9)
    with pytest.raises(FieldError):
        gps.decode([1 << 30] + [0] * 9)


# --- bit layout (Figure 20-1, subframe bit numbers 1 to 300 with parity) -----------------

# (field, ((first bit, last bit), ...)) read off Figure 20-1 sheets 1 to 3; a field in two
# pieces is MSBs first.
LAYOUT = {
    gps.Subframe1: {
        "week": [(61, 70)], "l2_code": [(71, 72)], "ura": [(73, 76)], "health": [(77, 82)],
        "iodc_msb": [(83, 84)], "l2p_data": [(91, 91)], "tgd": [(197, 204)],
        "iodc_lsb": [(211, 218)], "toc": [(219, 234)], "af2": [(241, 248)],
        "af1": [(249, 264)], "af0": [(271, 292)],
    },
    gps.Subframe2: {
        "iode": [(61, 68)], "crs": [(69, 84)], "delta_n": [(91, 106)],
        "m0": [(107, 114), (121, 144)], "cuc": [(151, 166)], "e": [(167, 174), (181, 204)],
        "cus": [(211, 226)], "sqrt_a": [(227, 234), (241, 264)], "toe": [(271, 286)],
        "fit_interval": [(287, 287)], "aodo": [(288, 292)],
    },
    gps.Subframe3: {
        "cic": [(61, 76)], "omega0": [(77, 84), (91, 114)], "cis": [(121, 136)],
        "i0": [(137, 144), (151, 174)], "crc": [(181, 196)], "omega": [(197, 204), (211, 234)],
        "omega_dot": [(241, 264)], "iode": [(271, 278)], "idot": [(279, 292)],
    },
}
HEADER = {"preamble": [(1, 8)], "tow": [(31, 47)], "subframe": [(50, 52)]}


def subframe_bits(data: int, pieces) -> int:
    """The value at Figure 20-1 bit positions ``pieces`` of the 240 data bits."""
    value = 0
    for first, last in pieces:
        for b in range(first, last + 1):
            word, pos = divmod(b - 1, 30)
            assert pos < 24, f"bit {b} is a parity bit"
            value = value << 1 | (data >> (239 - (24 * word + pos))) & 1
    return value


@pytest.mark.parametrize("cls", list(LAYOUT))
def test_figure_20_1_positions(cls):
    for _ in range(10):
        sf = rand(cls, **header(cls.SUBFRAME))
        data = gps.encode_data(sf)
        for name, pieces in {**HEADER, **LAYOUT[cls]}.items():
            width = sum(last - first + 1 for first, last in pieces)
            assert subframe_bits(data, pieces) == getattr(sf, name) % (1 << width), name


def test_table_dispatch_by_subframe_and_page():
    for cls in gps.TABLES.values():
        fixed = header(cls.SUBFRAME)
        if hasattr(cls, "SV_ID"):
            fixed.update(sv_id=cls.SV_ID, data_id=gps.DATA_ID)
        assert type(gps.decode_data(gps.encode_data(rand(cls, **fixed)))) is cls
    page = rand(gps.Subframe4Page18, **header(4), sv_id=57)   # page 1, 6, 11, ... : no table
    assert type(gps.decode_data(gps.encode_data(page))) is gps.OtherSubframe


@pytest.mark.parametrize("cls", [c for c in gps.TABLES.values() if hasattr(c, "SV_ID")])
def test_pages_of_another_data_id_are_kept_whole(cls):
    # IRN-IS-200N-003: 20.3.3.5.1.1 no longer calls Data ID 2 (binary 01) "the only valid
    # value", and the new 6.4.6.4 "Data ID Numbers Other Than 2" reserves the others for
    # "future data structures": "determine the Data ID before decoding and using LNAV data".
    assert gps.DATA_ID == 0b01
    for data_id in (0b00, 0b10, 0b11):
        page = rand(cls, **header(cls.SUBFRAME), sv_id=cls.SV_ID, data_id=data_id)
        data = gps.encode_data(page)
        assert (data >> (240 - 50)) & 3 == data_id          # the two MSBs of word 3
        other = gps.decode_data(data)
        assert type(other) is gps.OtherSubframe
        assert gps.encode_data(other) == data and gps.decode(gps.encode(other)) == other
    page = rand(cls, **header(cls.SUBFRAME), sv_id=cls.SV_ID, data_id=gps.DATA_ID)
    assert type(gps.decode(gps.encode(page))) is cls


# --- SkyTraq AN0039 0xE0 example ------------------------------------------------------------

AN0039_E0 = ("A0 A1 00 21 E0 02 05 8B 0B B4 3F 22 B5 4F 31 CF 4E FD 81 FD 4D 00 A1 0C 98 79 E7 "
             "09 08 D5 C5 F8 ED 03 EB FF F4 04 0D 0A")


def test_an0039_e0_example():
    # AN0039 0xE0: "the 24 higher bits of each of the navigation words", parity
    # checked and polarity adjusted by the receiver, i.e. the source data bits.
    msg = skytraq.decode(skytraq.parse(bytes.fromhex(AN0039_E0.replace(" ", "")), 0))
    data = 0
    for w in msg.words:
        data = data << 24 | w
    sf = gps.decode_data(data)
    assert (sf.preamble, sf.subframe) == (gps.PREAMBLE, msg.sfid) == (0x8B, 5)
    assert sf.tow == 0x3F22B5 >> 7
    assert type(sf) is gps.OtherSubframe   # data ID 1, SV ID 15: an almanac page
    assert gps.encode_data(sf) == data
    assert gps.decode(gps.encode(sf)) == sf


# --- assembly and RTCM 1019 -----------------------------------------------------------------

def issue(iodc: int):
    sf1 = rand(gps.Subframe1, **header(1), iodc_msb=iodc >> 8, iodc_lsb=iodc & 0xFF)
    sf2 = rand(gps.Subframe2, **header(2), iode=iodc & 0xFF)
    sf3 = rand(gps.Subframe3, **header(3), iode=iodc & 0xFF)
    return sf1, sf2, sf3


def test_assembler_needs_one_issue():
    asm = gps.Assembler()
    sf1, sf2, sf3 = issue(0x155)
    assert asm.push(7, sf1) is None
    assert asm.push(7, sf2) is None
    eph = asm.push(7, sf3)
    assert eph is not None and eph.iodc == 0x155 and eph.iode == 0x55 and eph.satellite == 7
    assert asm.push(7, sf1) is None                      # the same issue again
    new1, new2, new3 = issue(0x156)
    assert asm.push(7, new1) is None                     # IODC 0x156, IODE 0x55: mixed
    assert asm.push(7, new2) is None
    assert asm.push(7, new3).iodc == 0x156
    assert asm.push(8, sf3) is None                      # another satellite starts afresh


def test_mixed_issues_are_refused():
    sf1, sf2, sf3 = issue(0x10)
    with pytest.raises(FieldError):
        gps.ephemeris(1, sf1, dataclasses.replace(sf2, iode=0x11), sf3)


def test_rtcm_1019_fields():
    sf1, sf2, sf3 = issue(0x2AB)
    eph = gps.ephemeris(12, sf1, sf2, sf3)
    msg = rtcm3.Msg1019(**gps.rtcm_fields(eph))
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(msg), 0)) == msg
    assert (msg.satellite, msg.week, msg.accuracy, msg.toe, msg.m0, msg.af0) == \
        (12, sf1.week, sf1.ura, sf2.toe, sf2.m0, sf1.af0)
    assert msg.iodc == 0x2AB and msg.fit_interval == sf2.fit_interval
    # 1019 has every field of the ephemeris but AODO; the ephemeris has every field of 1019.
    names = {f.name for f in dataclasses.fields(rtcm3.Msg1019)} - {"number", "extension"}
    assert names == {f.name for f in dataclasses.fields(gps.Ephemeris)} - set(gps.NOT_IN_RTCM)
