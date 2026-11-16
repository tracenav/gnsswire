"""Galileo I/NAV and F/NAV (Galileo OS SIS ICD 2.2): pages, CRC, word layouts, assembly."""

from __future__ import annotations

import dataclasses
import random

import pytest

from gnsswire import rtcm3, skytraq
from gnsswire.bits import layout
from gnsswire.nav import FieldError, ParityError, galileo
from gnsswire.nav._common import width

rng = random.Random(21)


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


# --- widths (Tables 28, 38, 42 to 47, 51, 54, 30 to 33) ------------------------------------

def test_widths():
    assert width(galileo.InavPage) == 240
    for cls in (*galileo.INAV_WORDS.values(), galileo.InavOther):
        assert width(cls) == 128, cls
    for cls in (*galileo.FNAV_PAGES.values(), galileo.FnavOther):
        assert width(cls) == 244, cls


# --- the AN0039 0xE6 example: a nominal E1-B page with a valid CRC --------------------------

AN0039_E6 = ("A0 A1 00 25 E6 01 03 1E 08 06 FF FF FF FF 00 00 00 12 78 35 89 E2 4D 80 00 86 EE "
             "80 00 00 00 00 2A AA AA 66 4E 75 3F 40 00 ED 0D 0A")


def test_an0039_e6_page_crc():
    msg = skytraq.decode(skytraq.parse(bytes.fromhex(AN0039_E6.replace(" ", "")), 0))
    assert (msg.gnss_signal & 0xF, msg.gnss_signal >> 4, msg.svid) == (3, 0, 30)
    w = msg.words
    # Words 1 to 4: the even page part and 8 pad bits; words 5 to 8: the odd part and 8.
    even = (w[0] << 96 | w[1] << 64 | w[2] << 32 | w[3]) >> 8
    odd = (w[4] << 96 | w[5] << 64 | w[6] << 32 | w[7]) >> 8
    page = galileo.decode_inav(even, odd)   # checks the CRC
    assert (page.even, page.odd, page.page_type, page.page_type_odd) == (0, 1, 0, 0)
    word = galileo.inav_word(page)
    # Word type 6, GST-UTC conversion (Table 47): the leap second count of the time.
    assert type(word) is galileo.InavWord6
    assert (word.dt_ls, word.dt_lsf, word.wn_lsf, word.dn) == (18, 18, 137, 7)
    assert galileo.encode_inav(page) == (even, odd)
    # The CRC protects every bit it covers: flip each, and the page is refused.
    for bit in range(120):
        if 6 <= bit:    # not the tail
            with pytest.raises(ParityError):
                galileo.decode_inav(even ^ (1 << bit), odd)
    for bit in range(38, 120):   # odd part bits 1 to 82 (the CRC bits themselves too)
        with pytest.raises(ParityError):
            galileo.decode_inav(even, odd ^ (1 << bit))


def test_an0039_e6_table_words_are_not_a_page():
    # AN0039's 0xE6 field table prints words 5 to 8 as 0000002A AAAA664E 753F4000
    # 08D500C5, not the example frame's 86EE8000 0000002A AAAA664E 753F4000. The frame's
    # words are a page whose CRC checks (above); the table's are not.
    w = (0x06FFFFFF, 0xFF000000, 0x12783589, 0xE24D8000,
         0x0000002A, 0xAAAA664E, 0x753F4000, 0x08D500C5)
    even = (w[0] << 96 | w[1] << 64 | w[2] << 32 | w[3]) >> 8
    odd = (w[4] << 96 | w[5] << 64 | w[6] << 32 | w[7]) >> 8
    with pytest.raises(ParityError):
        galileo.decode_inav(even, odd)


def test_crc_does_not_cover_tail_or_ssp():
    page = galileo.inav_page(rand(galileo.InavWord1, word_type=1), ssp=0x5A)
    even, odd = galileo.encode_inav(page)
    assert galileo.decode_inav(even ^ 0x3F, odd ^ 0x3F ^ (0xFF << 6)) is not None


def test_part_widths_are_checked():
    with pytest.raises(FieldError):
        galileo.decode_inav(1 << 120, 0)


# --- I/NAV words ----------------------------------------------------------------------------

@pytest.mark.parametrize("cls", list(galileo.INAV_WORDS.values()))
def test_word_round_trip_through_a_page(cls):
    for _ in range(20):
        word = rand(cls, word_type=cls.TYPE)
        page = galileo.inav_page(word, osnma=rng.getrandbits(40), sar=rng.getrandbits(22))
        even, odd = galileo.encode_inav(page)
        back = galileo.decode_inav(even, odd)
        assert back == page and galileo.inav_word(back) == word


def test_word_1_layout():
    # Table 42: Type 6, IODnav 10, t0e 14, M0 32, e 32, sqrt(A) 32, Reserved 2.
    word = galileo.InavWord1(word_type=1, iodnav=0x3FF, toe=0, m0=-1, e=0, sqrt_a=0xFFFFFFFF,
                             reserved=0)
    bits = galileo.encode_inav_word(word)
    assert bits == (1 << 122 | 0x3FF << 112 | 0xFFFFFFFF << 66 | 0xFFFFFFFF << 2)


def test_word_4_layout():
    # Table 45: Type 6, IODnav 10, SVID 6, Cic 16, Cis 16, t0c 14, af0 31, af1 21, af2 6,
    # Spare 2.
    word = galileo.InavWord4(word_type=4, iodnav=0, svid=0x3F, cic=0, cis=0, toc=0x3FFF,
                             af0=0, af1=-1, af2=0, spare=0)
    bits = galileo.encode_inav_word(word)
    assert bits == 4 << 122 | 0x3F << 106 | 0x3FFF << 60 | 0x1FFFFF << 8


def test_alert_page_has_no_word():
    page = dataclasses.replace(galileo.inav_page(0), page_type=1, page_type_odd=1)
    with pytest.raises(FieldError):
        galileo.inav_word(page)


# --- F/NAV pages ----------------------------------------------------------------------------

@pytest.mark.parametrize("cls", list(galileo.FNAV_PAGES.values()))
def test_fnav_round_trip_and_crc(cls):
    for _ in range(20):
        page = galileo.with_crc(rand(cls, page_type=cls.TYPE, tail=0))
        bits = galileo.encode_fnav(page)
        assert galileo.decode_fnav(bits) == page
        for bit in range(30, 244):   # every protected bit and every CRC bit
            with pytest.raises(ParityError):
                galileo.decode_fnav(bits ^ (1 << bit))


def test_fnav_other_page_type():
    page = galileo.with_crc(rand(galileo.FnavOther, page_type=63))
    assert galileo.decode_fnav(galileo.encode_fnav(page)) == page


# --- assembly and RTCM 1046 / 1045 ----------------------------------------------------------

def inav_issue(iodnav: int, svid: int):
    return [
        rand(galileo.InavWord1, word_type=1, iodnav=iodnav),
        rand(galileo.InavWord2, word_type=2, iodnav=iodnav),
        rand(galileo.InavWord3, word_type=3, iodnav=iodnav),
        rand(galileo.InavWord4, word_type=4, iodnav=iodnav, svid=svid),
        rand(galileo.InavWord5, word_type=5),
    ]


def test_inav_assembler():
    asm = galileo.InavAssembler()
    words = inav_issue(100, 11)
    assert [asm.push(11, w) for w in words[:4]] == [None] * 4
    eph = asm.push(11, words[4])
    assert eph is not None and (eph.iodnav, eph.satellite, eph.week) == (100, 11, words[4].wn)
    assert asm.push(11, words[0]) is None                 # nothing new
    newer = inav_issue(101, 11)
    assert asm.push(11, newer[0]) is None                 # IODnav 101 with 100: mixed
    assert asm.push(11, newer[1]) is None
    assert asm.push(11, newer[2]) is None
    assert asm.push(11, newer[3]).iodnav == 101
    # Word 5 has no issue of data: a new one gives a new ephemeris of the same issue.
    w5 = dataclasses.replace(newer[4], e1b_hs=(newer[4].e1b_hs + 1) % 4)
    assert asm.push(11, w5).e1b_health == w5.e1b_hs


def test_inav_rtcm_1046():
    eph = galileo.inav_ephemeris(*inav_issue(7, 30))
    msg = rtcm3.Msg1046(**galileo.rtcm_fields(eph))
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(msg), 0)) == msg
    names = {f.name for f in dataclasses.fields(rtcm3.Msg1046)}
    assert names - {"number", "reserved", "extension"} == \
        {f.name for f in dataclasses.fields(galileo.InavEphemeris)}


def test_fnav_assembler_and_rtcm_1045():
    pages = [rand(cls, page_type=cls.TYPE, iodnav=55) for cls in galileo.FNAV_PAGES.values()]
    asm = galileo.FnavAssembler()
    assert [asm.push(4, p) for p in pages[:3]] == [None] * 3
    eph = asm.push(4, pages[3])
    assert eph.iodnav == 55 and eph.satellite == pages[0].svid
    msg = rtcm3.Msg1045(**galileo.rtcm_fields(eph))
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(msg), 0)) == msg
    with pytest.raises(FieldError):
        galileo.fnav_ephemeris(pages[0], pages[1], pages[2], dataclasses.replace(pages[3],
                                                                                 iodnav=56))
