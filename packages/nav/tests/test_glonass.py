"""GLONASS strings (GLONASS ICD 5.1): Hamming code, string layouts, assembly, RTCM 1020."""

from __future__ import annotations

import dataclasses
import random

import pytest

from gnsswire import rtcm3, skytraq
from gnsswire.bits import layout
from gnsswire.nav import FieldError, ParityError, glonass
from gnsswire.nav._common import width

rng = random.Random(1020)


def rand(cls, **fixed):
    values = {}
    for row in layout(cls).rows:
        kind = row.kind
        w = kind.width.eval(lambda n: 0)
        n = None if kind.count is None else kind.count.eval(lambda n: 0)
        sm = type(kind).__name__ == "SM"

        def one():
            v = rng.getrandbits(w - 1 if sm else w)
            return -v if sm and v and rng.getrandbits(1) else v
        values[row.name] = one() if n is None else tuple(one() for _ in range(n))
    values["idle"] = 0
    values.update(fixed)
    return glonass.with_hamming(cls(**values))


def test_widths():
    for cls in glonass.ALL:
        assert width(cls) == 85, cls


# --- Hamming code, section 4.7 and Table 4.13 -------------------------------------------------

def test_hamming_makes_every_checksum_zero():
    for _ in range(500):
        data = rng.getrandbits(76) << 8   # bits 84 to 9; the idle chip 0
        string = data | glonass.hamming(data)
        assert glonass.checksums(string) == (0,) * 8


def test_every_single_bit_error_is_refused():
    string = glonass.encode(rand(glonass.String1, m=1))
    glonass.check(string)
    for bit in range(85):
        with pytest.raises(ParityError):
            glonass.decode(string ^ (1 << bit))


def test_single_error_position_rule():
    # Rule (b) of 4.7: with two or more of C1..C7 equal to 1 and CSigma = 1, the bit in
    # error is C7...C1 + 8 - K (K the smallest i with 2^i >= C7...C1). Every data bit 9 to
    # 85 is named by exactly that rule; decode does not correct, but the code is the ICD's.
    string = glonass.encode(rand(glonass.String3, m=3))
    for bit in range(9, 86):
        cs = glonass.checksums(string ^ (1 << (bit - 1)))
        syndrome = sum(c << i for i, c in enumerate(cs[:7]))
        assert cs[7] == 1 and sum(cs[:7]) >= 2, bit
        k = next(i for i in range(8) if 1 << i >= syndrome)
        assert syndrome + 8 - k == bit


def test_strings_are_85_bits():
    with pytest.raises(FieldError):
        glonass.decode(1 << 85)


# --- layouts (Table 4.6 for strings 1 to 4, Table 4.11 for string 5) -------------------------

def bits(string: int, high: int, low: int) -> int:
    return (string >> (low - 1)) & ((1 << (high - low + 1)) - 1)


def test_string_1_layout():
    s = rand(glonass.String1, m=1, p1=3, tk=0xABC, x_dot=-5, x_ddot=0, x=7)
    string = glonass.encode(s)
    assert bits(string, 84, 81) == 1 and bits(string, 78, 77) == 3
    assert bits(string, 76, 65) == 0xABC
    assert bits(string, 64, 41) == 1 << 23 | 5            # sign-magnitude: the MSB the sign
    assert bits(string, 40, 36) == 0 and bits(string, 35, 9) == 7


def test_string_4_layout():
    s = rand(glonass.String4, m=4, tau=-3, delta_tau=2, en=17, p4=1, ft=9, nt=1461, n=24,
             sat_type=1)
    string = glonass.encode(s)
    assert bits(string, 80, 59) == 1 << 21 | 3 and bits(string, 58, 54) == 2
    assert bits(string, 53, 49) == 17 and bits(string, 34, 34) == 1
    assert bits(string, 33, 30) == 9 and bits(string, 26, 16) == 1461
    assert bits(string, 15, 11) == 24 and bits(string, 10, 9) == 1


def test_string_5_layout():
    s = rand(glonass.String5, m=5, na=1461, tau_c=-1, n4=8, tau_gps=1, ln=1)
    string = glonass.encode(s)
    assert bits(string, 80, 70) == 1461 and bits(string, 69, 38) == 1 << 31 | 1
    assert bits(string, 36, 32) == 8 and bits(string, 31, 10) == 1 and bits(string, 9, 9) == 1


@pytest.mark.parametrize("m", range(1, 16))
def test_round_trip_by_string_number(m):
    cls = glonass.TABLES[m]
    for _ in range(10):
        s = rand(cls, m=m)
        assert glonass.decode(glonass.encode(s)) == s


def test_frame_5_strings_14_and_15():
    s = rand(glonass.AlmanacEven, m=14)
    string = glonass.encode(s)
    assert type(glonass.decode(string)) is glonass.AlmanacEven
    other = glonass.decode(string, frame=5)
    assert type(other) is glonass.Other and glonass.encode(other) == string


# --- AN0039 0xE1 example ----------------------------------------------------------------------

AN0039_E1 = "A0 A1 00 0C E1 52 0E B4 05 A9 C3 94 17 50 04 82 33 0D 0A"


def test_an0039_e1_example():
    # 0xE1 gives the string number and bits 80 to 9; the idle chip is 0 and the receiver
    # checked and dropped the Hamming code, which is computed again here.
    msg = skytraq.decode(skytraq.parse(bytes.fromhex(AN0039_E1.replace(" ", "")), 0))
    assert (msg.svid - 64, msg.string) == (18, 14)
    data = int.from_bytes(bytes(msg.data), "big")
    string = msg.string << 80 | data << 8
    s = glonass.decode(string | glonass.hamming(string))
    assert type(s) is glonass.AlmanacEven
    assert (s.m, s.cn, s.sat_type, s.na) == (14, 1, 1, 20)


# --- assembly and RTCM 1020 -------------------------------------------------------------------

def frame(slot: int, tb: int):
    return [rand(glonass.String1, m=1), rand(glonass.String2, m=2, tb=tb),
            rand(glonass.String3, m=3), rand(glonass.String4, m=4, n=slot),
            rand(glonass.String5, m=5)]


def test_assembler_needs_strings_1_to_5_in_a_row():
    asm = glonass.Assembler()
    strings = frame(9, 40)
    assert [asm.push("R09", s) for s in strings[:4]] == [None] * 4
    eph = asm.push("R09", strings[4])
    assert eph.satellite == 9 and eph.tb == 40 and eph.x == strings[0].x
    assert eph.bn_msb == strings[1].bn >> 2 and eph.bn == strings[1].bn
    # A gap breaks the run: string 3 missing.
    later = frame(9, 41)
    for s in (later[0], later[1], later[3], later[4]):
        assert asm.push("R09", s) is None
    # The same strings again give nothing new.
    for s in strings[:4]:
        asm.push("R09", s)
    assert asm.push("R09", strings[4]) is None


def test_rtcm_1020_fields():
    eph = glonass.ephemeris(*frame(3, 12))
    fields = glonass.rtcm_fields(eph, channel=7 + 2)
    msg = rtcm3.Msg1020(**fields)
    assert rtcm3.decode(rtcm3.parse(rtcm3.encode(msg), 0)) == msg
    assert (msg.channel, msg.almanac_health_available, msg.additional) == (9, 0, 1)
    msg2 = rtcm3.Msg1020(**glonass.rtcm_fields(eph, channel=9, almanac_health=1))
    assert (msg2.almanac_health, msg2.almanac_health_available) == (1, 1)
    # 1020 lacks Bn's two LSBs, which the strings have.
    names = {f.name for f in dataclasses.fields(rtcm3.Msg1020)}
    assert {f.name for f in dataclasses.fields(glonass.Ephemeris)} - names == {"bn"}
