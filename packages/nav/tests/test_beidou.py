"""BeiDou D1 and D2 (BDS-SIS-ICD-B1I-3.0): BCH code, interleaving, layouts, assembly."""

from __future__ import annotations

import dataclasses
import random

import pytest

from gnsswire import rtcm3, skytraq
from gnsswire.bits import layout
from gnsswire.nav import FieldError, ParityError, beidou
from gnsswire.nav._common import width

rng = random.Random(1042)


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


def head(**kw):
    return dict(preamble=beidou.PREAMBLE, **kw)


def test_widths():
    for cls in beidou.TABLES:
        assert width(cls) == 224, cls


# --- BCH(15,11,1), section 5.1.3 ------------------------------------------------------------

def poly_mod(value: int, nbits: int, g: int = 0b10011) -> int:
    """value(X) mod g(X), g(X) = X^4 + X + 1, by long division (the MSB the highest power)."""
    for i in range(nbits - 1, 3, -1):
        if value >> i & 1:
            value ^= g << (i - 4)
    return value


def test_bch_code_words_are_multiples_of_g():
    # A systematic cyclic code: info(X)·X^4 + parity(X) is divisible by g(X).
    for info in range(1 << 11):
        assert poly_mod(info << 4 | beidou.bch(info), 15) == 0


def test_bch_distance_detects_single_errors():
    for info in range(1 << 11):
        code = info << 4 | beidou.bch(info)
        for bit in range(15):
            bad = code ^ (1 << bit)
            assert beidou.bch(bad >> 4) != bad & 0xF


def test_interleaving_of_words_2_to_10():
    # Section 5.1.3: X1(1) X2(1) ... X1(11) X2(11) P1(1) P2(1) ... P1(4) P2(4).
    data = rng.getrandbits(224)
    words = beidou.words_from_data(data)
    for k in range(9):
        info = (data >> (22 * (8 - k))) & 0x3FFFFF
        a, b = info >> 11, info & 0x7FF
        word = words[k + 1]
        assert all((word >> (29 - 2 * i)) & 1 == (a >> (10 - i)) & 1 for i in range(11))
        assert all((word >> (28 - 2 * i)) & 1 == (b >> (10 - i)) & 1 for i in range(11))
        pa, pb = beidou.bch(a), beidou.bch(b)
        assert all((word >> (7 - 2 * i)) & 1 == (pa >> (3 - i)) & 1 for i in range(4))
        assert all((word >> (6 - 2 * i)) & 1 == (pb >> (3 - i)) & 1 for i in range(4))
    # Word 1: 15 bits not encoded, then 11 information bits and their 4 parity bits.
    first = data >> 198
    assert words[0] == first << 4 | beidou.bch(first & 0x7FF)


def test_every_single_bit_error_is_detected():
    words = list(beidou.encode(rand(beidou.D1Subframe1, **head(fraid=1))))
    for i in range(10):
        for bit in range(30):
            if i == 0 and bit >= 15:   # word 1 bits 1 to 15 (preamble, Rev) are not encoded
                continue
            bad = words.copy()
            bad[i] ^= 1 << bit
            with pytest.raises(ParityError):
                beidou.decode(bad, d2=False)


# --- tables ---------------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [beidou.D1Subframe1, beidou.D1Subframe2, beidou.D1Subframe3])
def test_d1_round_trip(cls):
    for _ in range(20):
        sf = rand(cls, **head(fraid=cls.FRAID))
        assert beidou.decode(beidou.encode(sf), d2=False) == sf


@pytest.mark.parametrize("pnum", range(1, 11))
def test_d2_round_trip(pnum):
    cls = beidou.D2_PAGES[pnum]
    for _ in range(10):
        page = rand(cls, **head(fraid=1, pnum=pnum))
        assert beidou.decode(beidou.encode(page), d2=True) == page
        # The same bits read as D1 are subframe 1 of D1, a different table.
        assert type(beidou.decode_data(beidou.encode_data(page), d2=False)) is \
            beidou.D1Subframe1


@pytest.mark.parametrize(("pnum", "d1", "d2"), [(7, beidou.Health1, 35), (8, beidou.Health2, 36),
                                                (10, beidou.Utc, 102)])
def test_subframe_5_pages(pnum, d1, d2):
    page = rand(d1, **head(fraid=5, pnum=pnum))
    assert beidou.decode_data(beidou.encode_data(page), d2=False) == page
    page2 = dataclasses.replace(page, pnum=d2)
    assert beidou.decode_data(beidou.encode_data(page2), d2=True) == page2
    assert type(beidou.decode_data(beidou.encode_data(page2), d2=False)) is beidou.Other


def test_d1_subframe_1_layout():
    # Figure 5-8: after Pre 11, Rev 4, FraID 3, SOW 20: SatH1 1, AODC 5, URAI 4, WN 13,
    # toc 17, TGD1 10, TGD2 10 (information bits, word by word).
    sf = rand(beidou.D1Subframe1, **head(fraid=1), sat_h1=1, aodc=0, urai=0, week=0x1FFF,
              toc=0, tgd1=0)
    data = beidou.encode_data(sf)
    assert (data >> (224 - 39)) & 1 == 1                 # SatH1: bit 39
    assert (data >> (224 - 61)) & 0x1FFF == 0x1FFF       # WN: bits 49-61
    assert (data >> (224 - 48)) & 0x1FF == 0             # AODC, URAI: bits 40-48
    assert (data >> (224 - 18)) & 7 == 1                 # FraID: bits 16-18


# --- AN0039 examples: 0xE2 (D1, PRN 7) and 0xE3 (D2, PRN 3) ---------------------------------

AN0039_E2 = ("A0 A1 00 1F E2 CF 01 E2 40 47 37 58 00 0D A0 E1 00 AC 03 87 8E 31 5B 53 B4 12 B2 "
             "C0 02 5B 04 60 07 AB 81 B1 0D 0A")
AN0039_E3 = ("A0 A1 00 1F E3 CB 01 E2 40 47 37 95 A5 14 C8 CA EA CF A5 00 15 55 55 55 55 55 55 "
             "55 55 55 55 55 55 55 55 48 0D 0A")


def example(text: str):
    msg = skytraq.decode(skytraq.parse(bytes.fromhex(text.replace(" ", "")), 0))
    return msg, int.from_bytes(bytes(msg.data), "big")


def test_an0039_e2_example():
    msg, data = example(AN0039_E2)
    sf = beidou.decode_data(data, d2=False)
    assert (msg.svid - 200, msg.sfid) == (7, 1)
    assert type(sf) is beidou.D1Subframe1
    assert (sf.preamble, sf.fraid, sf.sow, sf.week) == (beidou.PREAMBLE, 1, 118230, 436)
    assert sf.toc * 8 <= sf.sow < sf.toc * 8 + 3600       # toc (2^3 s) within the hour
    assert beidou.encode_data(sf) == data


def test_an0039_e3_example():
    msg, data = example(AN0039_E3)
    page = beidou.decode_data(data, d2=True)
    assert (msg.svid - 200, msg.sfid) == (3, 1)
    assert type(page) is beidou.D2Page6
    assert (page.fraid, page.pnum, page.sow) == (1, 6, 118245)
    # sqrt(A) in 2^-19 m^1/2: a geostationary orbit's, about 6493.
    assert 6490 < page.sqrt_a * 2**-19 < 6496
    assert page.reserved == (0b0101010101010101010101,) * 5
    assert beidou.encode_data(page) == data


# --- assembly and RTCM 1042 -----------------------------------------------------------------

def d1_issue(sow: int):
    toe = rng.getrandbits(17)
    return [
        rand(beidou.D1Subframe1, **head(fraid=1, sow=sow)),
        rand(beidou.D1Subframe2, **head(fraid=2, sow=sow + 6), toe_msb=toe >> 15),
        rand(beidou.D1Subframe3, **head(fraid=3, sow=sow + 12), toe_lsb=toe & 0x7FFF),
    ], toe


def test_d1_assembler():
    asm = beidou.Assembler()
    sfs, toe = d1_issue(1000)
    assert asm.push(9, sfs[0]) is None and asm.push(9, sfs[1]) is None
    eph = asm.push(9, sfs[2])
    assert eph.toe == toe and eph.aode == sfs[0].aode and eph.satellite == 9
    later, _ = d1_issue(1030)
    assert asm.push(9, later[0]) is None   # subframe 1 at 1030 with 2 and 3 of 1000: refused
    assert asm.push(9, later[1]) is None
    assert asm.push(9, later[2]).aode == later[0].aode


def test_d1_week_wrap():
    sfs, _ = d1_issue(beidou.WEEK - 6)
    sfs[1] = dataclasses.replace(sfs[1], sow=0)
    sfs[2] = dataclasses.replace(sfs[2], sow=6)
    assert beidou.d1_ephemeris(1, *sfs) is not None
    with pytest.raises(FieldError):
        beidou.d1_ephemeris(1, sfs[0], sfs[2], sfs[1])


def test_d2_assembler_joins_split_fields():
    eph_fields = {"a1": -123456, "cuc": -54321, "e": 0x89ABCDEF, "cic": -77777,
                  "i0": -0x12345678, "omega": -0x2345678, "omega_dot": -0x123456}
    v = {k: x % (1 << w) for (k, x), w in zip(eph_fields.items(), (22, 18, 32, 18, 32, 32, 24))}
    split = {
        3: dict(a1_msb=v["a1"] >> 18), 4: dict(a1_lsb=v["a1"] & 0x3FFFF, cuc_msb=v["cuc"] >> 4),
        5: dict(cuc_lsb=v["cuc"] & 0xF, e_msb=v["e"] >> 22),
        6: dict(e_lsb=v["e"] & 0x3FFFFF, cic_msb=v["cic"] >> 8),
        7: dict(cic_lsb=v["cic"] & 0xFF, i0_msb=v["i0"] >> 11),
        8: dict(i0_lsb=v["i0"] & 0x7FF, omega_dot_msb=v["omega_dot"] >> 5),
        9: dict(omega_dot_lsb=v["omega_dot"] & 0x1F, omega_msb=v["omega"] >> 5),
        10: dict(omega_lsb=v["omega"] & 0x1F),
    }
    pages = [rand(beidou.D2_PAGES[k], **head(fraid=1, pnum=k, sow=500 + 3 * (k - 1)),
                  **split.get(k, {})) for k in range(1, 11)]
    asm = beidou.Assembler()
    out = [asm.push(2, p) for p in pages]
    assert out[:9] == [None] * 9
    eph = out[9]
    assert {k: getattr(eph, k) for k in eph_fields} == eph_fields
    assert eph.toe == pages[6].toe and eph.week == pages[0].week
    shuffled = [dataclasses.replace(p, sow=p.sow + 3) if p.pnum == 5 else p for p in pages]
    with pytest.raises(FieldError):
        beidou.d2_ephemeris(2, shuffled)


def test_rtcm_1042():
    sfs, _ = d1_issue(3000)
    eph = beidou.d1_ephemeris(14, *sfs)
    msg = rtcm3.Msg1042(**beidou.rtcm_fields(eph))
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(msg), 0)) == msg
    assert {f.name for f in dataclasses.fields(rtcm3.Msg1042)} - {"number", "extension"} == \
        {f.name for f in dataclasses.fields(beidou.Ephemeris)}
