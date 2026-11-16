"""CRCs against the catalogue check values, the standard library and bitwise division.

Check values are the CRC of b"123456789" from the CRC catalogue,
https://reveng.sourceforge.io/crc-catalogue/all.htm (retrieved 2026-11-13).
"""

import binascii
import zlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gnsswire import bits
from gnsswire.bits import Crc

CHECK = b"123456789"

NAMED = [bits.CRC24Q, bits.CRC4_SPARTN, bits.CRC8_SMBUS, bits.CRC16_XMODEM, bits.CRC24_LTE_A,
         bits.CRC32_BZIP2, bits.CRC16_IBM_3740, bits.CRC24_OPENPGP, bits.CRC32_ISO_HDLC]

# Further catalogue entries, chosen to cover each path of the implementation:
# widths below 8 reflected and not, refin != refout, width 64.
CATALOGUE = [
    Crc("CRC-3/GSM", 3, 0x3, 0x0, False, False, 0x7, 0x4),
    Crc("CRC-4/G-704", 4, 0x3, 0x0, True, True, 0x0, 0x7),
    Crc("CRC-4/INTERLAKEN", 4, 0x3, 0xF, False, False, 0xF, 0xB),
    Crc("CRC-5/USB", 5, 0x05, 0x1F, True, True, 0x1F, 0x19),
    Crc("CRC-7/MMC", 7, 0x09, 0x00, False, False, 0x00, 0x75),
    Crc("CRC-8/ROHC", 8, 0x07, 0xFF, True, True, 0x00, 0xD0),
    Crc("CRC-8/I-432-1", 8, 0x07, 0x00, False, False, 0x55, 0xA1),
    Crc("CRC-11/FLEXRAY", 11, 0x385, 0x01A, False, False, 0x000, 0x5A3),
    Crc("CRC-12/UMTS", 12, 0x80F, 0x000, False, True, 0x000, 0xDAF),
    Crc("CRC-16/KERMIT", 16, 0x1021, 0x0000, True, True, 0x0000, 0x2189),
    Crc("CRC-16/MODBUS", 16, 0x8005, 0xFFFF, True, True, 0x0000, 0x4B37),
    Crc("CRC-32/JAMCRC", 32, 0x04C11DB7, 0xFFFFFFFF, True, True, 0, 0x340BC6D9),
    Crc("CRC-32/MPEG-2", 32, 0x04C11DB7, 0xFFFFFFFF, False, False, 0, 0x0376E6E7),
    Crc("CRC-40/GSM", 40, 0x0004820009, 0, False, False, 0xFFFFFFFFFF, 0xD4164FC646),
    Crc("CRC-64/ECMA-182", 64, 0x42F0E1EBA9EA3693, 0, False, False, 0, 0x6C40DF5F0B497347),
    Crc("CRC-64/XZ", 64, 0x42F0E1EBA9EA3693, (1 << 64) - 1, True, True, (1 << 64) - 1,
        0x995DC9BBDF1939FA),
]


def bitwise(crc: Crc, data: bytes) -> int:
    """The direct, bit-at-a-time shift-register form of the catalogue model.

    Independent of the table-driven code under test: every message bit enters
    the register one at a time, LSB of each byte first when refin.
    """
    mask = (1 << crc.width) - 1
    reg = crc.init
    for byte in data:
        for i in range(8):
            bit = (byte >> i) & 1 if crc.refin else (byte >> (7 - i)) & 1
            top = (reg >> (crc.width - 1)) & 1
            reg = (reg << 1) & mask
            if top ^ bit:
                reg ^= crc.poly
    if crc.refout:
        reg = int(format(reg, f"0{crc.width}b")[::-1], 2)
    return reg ^ crc.xorout


@pytest.mark.parametrize("crc", [c for c in NAMED + CATALOGUE if c.check is not None],
                         ids=lambda c: c.name)
def test_catalogue_check_value(crc):
    assert crc(CHECK) == crc.check
    assert bitwise(crc, CHECK) == crc.check


def test_crc24q_is_rtcm_section_4_2():
    # Generator coefficients g_i = 1 for i = 0, 1, 3, 4, 5, 6, 7, 10, 11, 14, 17,
    # 18, 23, 24, seed 0, no reflection or final XOR.
    poly = sum(1 << i for i in (0, 1, 3, 4, 5, 6, 7, 10, 11, 14, 17, 18, 23))
    assert (bits.CRC24Q.poly, bits.CRC24Q.init, bits.CRC24Q.xorout) == (poly, 0, 0)
    assert not bits.CRC24Q.refin and not bits.CRC24Q.refout


def test_crc4_spartn_is_tf006():
    # SPARTN v2.0.3 Table 7.1, TF006: poly 0x09, initialised at zero, input and
    # output reflected, zero XOR on output. Not in the catalogue: checked by
    # bitwise division below, and against public frames in the spartn codec.
    c = bits.CRC4_SPARTN
    assert (c.width, c.poly, c.init, c.refin, c.refout, c.xorout) == (4, 0x9, 0, True, True, 0)
    assert c.check is None


@pytest.mark.parametrize("crc", NAMED + CATALOGUE, ids=lambda c: c.name)
@given(data=st.binary(max_size=64))
def test_table_matches_bitwise_division(crc, data):
    assert crc(data) == bitwise(crc, data)


@given(st.binary(max_size=256))
def test_standard_library_oracles(data):
    assert bits.CRC32_ISO_HDLC(data) == zlib.crc32(data)
    assert bits.CRC16_XMODEM(data) == binascii.crc_hqx(data, 0)


@given(st.binary(max_size=256))
def test_crc24q_residue_is_zero(data):
    # RTCM 10403.3 section 4.2: the 24 parity bits are the remainder of m(X)X^24
    # divided by g(X), so the message followed by its parity divides exactly.
    parity = bits.CRC24Q(data)
    assert bits.CRC24Q(data + parity.to_bytes(3, "big")) == 0


@pytest.mark.parametrize("args", [
    dict(width=0, poly=1, init=0), dict(width=65, poly=1, init=0),
    dict(width=8, poly=0x100, init=0), dict(width=8, poly=7, init=-1),
])
def test_bad_parameters(args):
    with pytest.raises(ValueError):
        Crc("bad", args["width"], args["poly"], args["init"], False, False, 0, None)


SLICEABLE = [c for c in NAMED + CATALOGUE if not c.refin and not c.refout and c.width % 8 == 0]


@pytest.mark.parametrize("crc", SLICEABLE, ids=lambda c: c.name)
@given(data=st.binary(min_size=1, max_size=300),
       cuts=st.lists(st.tuples(st.integers(0, 300), st.integers(0, 300)), max_size=20),
       window=st.sampled_from([0, 7, 1 << 16]))
def test_slices_match_the_crc_of_the_slice(crc, data, cuts, window):
    # Slices asked in any order, including backwards, which resets the base.
    slices = bits.CrcSlices(crc, data, window)
    for a, b in cuts:
        a, b = sorted((a % (len(data) + 1), b % (len(data) + 1)))
        assert slices(a, b) == crc(data[a:b])


def test_slices_refuse_what_they_cannot_do():
    assert {c.name for c in SLICEABLE} >= {"CRC-24Q", "CRC-8/SMBUS", "CRC-16/XMODEM",
                                           "CRC-24/LTE-A", "CRC-32/BZIP2"}
    for crc in (bits.CRC4_SPARTN, bits.CRC32_ISO_HDLC):
        with pytest.raises(ValueError):
            bits.CrcSlices(crc, b"")
    with pytest.raises(ValueError):
        bits.CrcSlices(bits.CRC24Q, b"abc")(1, 4)
