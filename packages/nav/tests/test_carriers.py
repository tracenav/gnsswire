"""UBX-RXM-SFRBX (UBX-13003221 chapter 10) and SkyTraq (AN0039) presentations of the units."""

from __future__ import annotations

import dataclasses
import random

import pytest

from gnsswire import skytraq, ubx
from gnsswire.bits import layout
from gnsswire.nav import (
    Assembler,
    FieldError,
    ParityError,
    Unsupported,
    beidou,
    carriers,
    from_sfrbx,
    from_skytraq,
    galileo,
    glonass,
    gps,
)

rng = random.Random(13003221)


def rand(cls, **fixed):
    values = {}
    for row in layout(cls).rows:
        kind = row.kind
        w = kind.width.eval(lambda n: 0)
        n = None if kind.count is None else kind.count.eval(lambda n: 0)
        name = type(kind).__name__

        def one():
            v = rng.getrandbits(w - 1 if name == "SM" else w)
            if name == "S" and v >> (w - 1):
                return v - (1 << w)
            return -v if name == "SM" and v and rng.getrandbits(1) else v
        values[row.name] = one() if n is None else tuple(one() for _ in range(n))
    values.update(fixed)
    return cls(**values)


def sfrbx(system, sat, message, **kw):
    return ubx.RxmSfrbx(**carriers.to_sfrbx(system, sat, message, **kw))


def round_trip(msg):
    received = from_sfrbx(msg)
    assert ubx.RxmSfrbx(**carriers.sfrbx_fields(received)) == msg
    frame = ubx.encode(msg)
    assert ubx.decode(ubx.parse(frame, 0)) == msg
    return received


# --- UBX-RXM-SFRBX ----------------------------------------------------------------------------

def test_ubx_gps_words_are_source_data_bits():
    # 10.2.1: 2 pad bits, 24 data bits, 6 parity bits; the receiver undoes the inversion
    # (10.1), so the data bits are the source bits d1 to d24 whatever D30* was.
    sf = gps.solve_t(rand(gps.Subframe2, preamble=gps.PREAMBLE, subframe=2))
    msg = sfrbx(carriers.GPS, 5, sf)
    assert (msg.gnss_id, msg.sig_id, msg.num_words) == (0, 0, 10)
    data = gps.encode_data(sf)
    transmitted = gps.encode(sf)
    for k, w in enumerate(msg.dwrd):
        assert w >> 30 == 0
        assert (w >> 6) & 0xFFFFFF == (data >> (24 * (9 - k))) & 0xFFFFFF
        # The parity bits are complemented with the data (repository README, "Limitations").
        inverted = k > 0 and transmitted[k - 1] & 1
        assert w & 0x3F == (transmitted[k] ^ (0x3F if inverted else 0)) & 0x3F
    assert round_trip(msg).message == sf


def test_ubx_gps_parity_failure():
    msg = sfrbx(carriers.GPS, 5, rand(gps.Subframe1, preamble=gps.PREAMBLE, subframe=1))
    bad = dataclasses.replace(msg, dwrd=(msg.dwrd[0] ^ 1, *msg.dwrd[1:]))
    with pytest.raises(ParityError):
        from_sfrbx(bad)


def test_ubx_gps_pad_bits_are_kept():
    msg = sfrbx(carriers.GPS, 5, rand(gps.Subframe3, preamble=gps.PREAMBLE, subframe=3))
    padded = dataclasses.replace(msg, dwrd=tuple(w | 2 << 30 for w in msg.dwrd))
    assert round_trip(padded).message == from_sfrbx(msg).message


def test_ubx_galileo_page_parts():
    word = rand(galileo.InavWord3, word_type=3)
    page = galileo.inav_page(word, osnma=rng.getrandbits(40))
    msg = sfrbx(carriers.GALILEO_INAV, 12, page, sig_id=1)
    even, odd = galileo.encode_inav(page)
    w = msg.dwrd
    # 10.5.1: words 1-4 the even part then 8 pad bits, words 5-8 the odd part then 8.
    assert (w[0] << 96 | w[1] << 64 | w[2] << 32 | w[3]) == even << 8
    assert (w[4] << 96 | w[5] << 64 | w[6] << 32 | w[7]) == odd << 8
    assert round_trip(msg).message == page
    padded = dataclasses.replace(msg, dwrd=(*w[:3], w[3] | 0xA5, *w[4:7], w[7] | 0x3C))
    assert round_trip(padded).message == page
    for sig in (0, 1, 5, 6):   # E1 C, E1 B, E5 bI, E5 bQ: I/NAV
        assert from_sfrbx(dataclasses.replace(msg, sig_id=sig)).system == "galileo-inav"


def test_ubx_beidou_parity_fields():
    sf = rand(beidou.D1Subframe3, preamble=beidou.PREAMBLE, fraid=3)
    msg = sfrbx(carriers.BEIDOU_D1, 30, sf)
    data = beidou.encode_data(sf)
    # 10.4: 2 pad bits, 22 data bits (de-interleaved), 8 parity bits; word 1: 26 + 4.
    assert msg.dwrd[0] >> 4 == data >> 198
    assert [(w >> 8) & 0x3FFFFF for w in msg.dwrd[1:]] == \
        [(data >> (22 * (8 - k))) & 0x3FFFFF for k in range(9)]
    assert round_trip(msg).message == sf
    # Receivers at hand send the parity fields as zero: accepted (nothing to check).
    zero = dataclasses.replace(msg, dwrd=(msg.dwrd[0] & ~0xF,
                                          *(w & ~0xFF for w in msg.dwrd[1:])))
    assert round_trip(zero).message == sf
    # Parity present and wrong: refused.
    wrong = dataclasses.replace(msg, dwrd=(*msg.dwrd[:4], msg.dwrd[4] ^ 1, *msg.dwrd[5:]))
    with pytest.raises(ParityError):
        from_sfrbx(wrong)


def test_ubx_beidou_d1_and_d2_by_signal():
    page = rand(beidou.D2Page4, preamble=beidou.PREAMBLE, fraid=1, pnum=4)
    msg = sfrbx(carriers.BEIDOU_D2, 1, page)
    assert msg.sig_id == 1 and round_trip(msg).message == page
    assert from_sfrbx(dataclasses.replace(msg, sig_id=3)).system == "beidou-d2"
    assert type(from_sfrbx(dataclasses.replace(msg, sig_id=0)).message) is beidou.D1Subframe1


def test_ubx_glonass_string_and_frame_number():
    s = glonass.with_hamming(rand(glonass.AlmanacOdd, idle=0, m=15))
    msg = sfrbx(carriers.GLONASS, 4, s, freq_id=7 - 3, sig_id=2)
    string = glonass.encode(s)
    w = msg.dwrd
    # 10.3: string bits 85 to 1 in words 1-3, then 11 pad bits; word 4: superframe, pad,
    # frame number.
    assert (w[0] << 64 | w[1] << 32 | w[2]) == string << 11 and w[3] == 0
    assert round_trip(msg).message == s
    in_frame_5 = dataclasses.replace(msg, dwrd=(*w[:3], 0x1234 << 16 | 5))
    assert type(round_trip(in_frame_5).message) is glonass.Other
    with pytest.raises(ParityError):
        from_sfrbx(dataclasses.replace(msg, dwrd=(w[0] ^ 1 << 20, *w[1:])))


# The signals of F9 HPG 1.32 section 1.5.4 without a layout here (IMES, gnssId 4, is no
# longer in 1.51), then those F9 HPG 1.51 section 1.5.4 (Table 4) adds: Galileo E6 B, C and
# A (8 to 10), BeiDou B3I D1 and D2 (4, 10), the B1C data and B2a data components (6, 8;
# 5 and 7 become the pilots), and QZSS L1C/B, which X20 HPG 2.11 adds.
@pytest.mark.parametrize(("gnss", "sig"), [(0, 3), (0, 4), (0, 6), (1, 0), (2, 3), (3, 5),
                                           (3, 7), (5, 0), (4, 0), (7, 0),
                                           (2, 8), (2, 9), (2, 10), (3, 4), (3, 10), (3, 6),
                                           (3, 8), (5, 12)])
def test_ubx_unsupported_signals(gnss, sig):
    msg = ubx.RxmSfrbx(gnss_id=gnss, sv_id=1, sig_id=sig, freq_id=0, num_words=10, chn=0,
                       version=2, reserved0=0, dwrd=(0,) * 10)
    with pytest.raises(Unsupported):
        from_sfrbx(msg)


def test_ubx_word_count_checked():
    msg = sfrbx(carriers.GPS, 5, rand(gps.Subframe1, preamble=gps.PREAMBLE, subframe=1))
    with pytest.raises(FieldError):
        from_sfrbx(dataclasses.replace(msg, num_words=9, dwrd=msg.dwrd[:9]))


# --- SkyTraq AN0039 examples ------------------------------------------------------------------

EXAMPLES = {
    0xE0: "A0A10021E002058B0BB43F22B54F31CF4EFD81FD4D00A10C9879E70908D5C5F8ED03EBFFF4040D0A",
    0xE1: "A0A1000CE1520EB405A9C394175004823 30D0A",
    0xE2: "A0A1001FE2CF01E240473758000DA0E100AC03878E315B53B412B2C0025B04600 7AB81B10D0A",
    0xE3: "A0A1001FE3CB01E240473795A514C8CAEACFA500155555555555555555555555555555480D0A",
    0xE6: "A0A10025E601031E0806FFFFFFFF0000001278358 9E24D800086EE8000000000 2AAAAA664E753F4000ED0D0A",
}


@pytest.mark.parametrize("msg_id", list(EXAMPLES))
def test_an0039_examples_round_trip(msg_id):
    msg = skytraq.decode(skytraq.parse(bytes.fromhex(EXAMPLES[msg_id].replace(" ", "")), 0))
    assert type(msg).MSG_ID == msg_id
    received = from_skytraq(msg)
    assert type(msg)(**carriers.skytraq_fields(received)) == msg
    system, sat = {0xE0: ("gps", 2), 0xE1: ("glonass", 18), 0xE2: ("beidou-d1", 7),
                   0xE3: ("beidou-d2", 3), 0xE6: ("galileo-inav", 30)}[msg_id]
    assert (received.system, received.satellite) == (system, sat)


def test_skytraq_e6_other_systems_unsupported():
    msg = skytraq.decode(skytraq.parse(bytes.fromhex(EXAMPLES[0xE6].replace(" ", "")), 0))
    for gnss_signal in (0x00, 0x02, 0x05, 0x43):   # GPS, GLONASS, BeiDou, Galileo E5a
        with pytest.raises(Unsupported):
            from_skytraq(dataclasses.replace(msg, gnss_signal=gnss_signal))
    assert from_skytraq(dataclasses.replace(msg, gnss_signal=0x53)).signal == 5   # E5b


def test_skytraq_encoders():
    sf = rand(gps.Subframe1, preamble=gps.PREAMBLE, subframe=1)
    fields = carriers.to_skytraq(carriers.GPS, 9, sf)
    assert from_skytraq(skytraq.GpsSubframe(**fields)).message == sf
    s = glonass.with_hamming(rand(glonass.String2, idle=0, m=2))
    assert from_skytraq(skytraq.GlonassString(**carriers.to_skytraq(carriers.GLONASS, 3, s))
                        ).message == s
    p = rand(beidou.D2Page9, preamble=beidou.PREAMBLE, fraid=1, pnum=9)
    got = from_skytraq(skytraq.BeidouD2Subframe(**carriers.to_skytraq(carriers.BEIDOU_D2, 1, p)))
    assert got.message == p and got.satellite == 1
    page = galileo.inav_page(rand(galileo.InavWord2, word_type=2))
    got = from_skytraq(skytraq.GeneralSubframe(**carriers.to_skytraq(carriers.GALILEO_INAV, 8,
                                                                     page, signal=5)))
    assert got.message == page and got.signal == 5


def test_not_a_navigation_message():
    with pytest.raises(Unsupported):
        from_skytraq(skytraq.MeasTime(iod=0, week=0, tow=0, period=1000))


# --- the combined assembler -------------------------------------------------------------------

def test_assembler_routes_by_system():
    asm = Assembler()
    iodc = 0x3C
    head = dict(preamble=gps.PREAMBLE)
    out = [asm.push(from_sfrbx(sfrbx(carriers.GPS, 6, gps.solve_t(sf)))) for sf in (
        rand(gps.Subframe1, **head, subframe=1, iodc_msb=0, iodc_lsb=iodc),
        rand(gps.Subframe2, **head, subframe=2, iode=iodc),
        rand(gps.Subframe3, **head, subframe=3, iode=iodc))]
    assert out[:2] == [None, None] and isinstance(out[2], gps.Ephemeris)
    strings = [glonass.with_hamming(rand(cls, idle=0, m=m)) for m, cls in
               ((1, glonass.String1), (2, glonass.String2), (3, glonass.String3),
                (4, glonass.String4), (5, glonass.String5))]
    out = [asm.push(from_sfrbx(sfrbx(carriers.GLONASS, 11, s, freq_id=5))) for s in strings]
    assert isinstance(out[4], glonass.Ephemeris)
    alert = dataclasses.replace(galileo.inav_page(0), page_type=1, page_type_odd=1)
    alert = dataclasses.replace(alert, crc24=galileo.crc24q(alert.crc_input(), 196))
    assert asm.push(from_sfrbx(sfrbx(carriers.GALILEO_INAV, 2, alert))) is None
