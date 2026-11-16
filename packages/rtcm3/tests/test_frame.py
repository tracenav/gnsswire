"""Transport-layer framing against RTCM 10403.3 section 4.

The CRC itself is checked against the CRC catalogue in packages/bits. The
properties shared with the other codecs (truncation, bit flips, scan through
garbage) are in tests/test_framing.py.
"""

import pytest

from gnsswire import rtcm3
from gnsswire.rtcm3 import Frame, Invalid, NeedMore

# Section 4.2: message type 1005, reference station 2003.
EXAMPLE = bytes.fromhex("D3 00 13 3E D7 D3 02 02 98 0E DE EF 34 B4 BD 62"
                        "AC 09 41 98 6F 33 36 0B 98")


def test_section_4_2_example():
    result = rtcm3.parse(EXAMPLE)
    assert result == Frame(0, 25, EXAMPLE[3:22], 0)
    assert len(result.payload) == 0x13
    # DF002 and DF003, the first 12 and next 12 bits: the example's message
    # type and station ID.
    head = int.from_bytes(result.payload[:3], "big")
    assert (head >> 12, head & 0xFFF) == (1005, 2003)
    assert rtcm3.encode(result) == EXAMPLE
    assert rtcm3.encode_frame(result.payload) == EXAMPLE


def test_filler_message():
    # Section 4.1: length zero gives a 48-bit filler frame.
    frame = rtcm3.encode_frame(b"")
    assert len(frame) == 6
    assert rtcm3.parse(frame) == Frame(0, 6, b"", 0)


@pytest.mark.parametrize("reserved", [1, 0x20, 0x3F])
def test_reserved_bits_are_ignored_and_kept(reserved):
    # Section 4.1: the receiver "should ignore these bits and not assume they
    # will always be set to zero".
    payload = EXAMPLE[3:22]
    frame = rtcm3.encode_frame(payload, reserved)
    assert frame[1] >> 2 == reserved
    assert frame[3:22] == payload and frame != EXAMPLE
    result = rtcm3.parse(frame)
    assert result == Frame(0, 25, payload, reserved)
    assert rtcm3.encode(result) == frame
    # The bits belong to the transport layer, not to the message: decoding
    # drops them, and the message is framed as a transmitter "should", with
    # zeros (the README's round trip covers conforming frames only).
    message = rtcm3.decode(result)
    assert message == rtcm3.decode(rtcm3.parse(EXAMPLE))
    assert rtcm3.encode(message) == EXAMPLE


def test_largest_message():
    payload = bytes(range(256)) * 3 + bytes(range(255))
    assert len(payload) == rtcm3.MAX_PAYLOAD
    frame = rtcm3.encode_frame(payload)
    assert frame[1:3] == b"\x03\xff"
    assert rtcm3.parse(frame) == Frame(0, 1029, payload, 0)
    with pytest.raises(ValueError):
        rtcm3.encode_frame(payload + b"\0")


@pytest.mark.parametrize("reserved", [-1, 64])
def test_reserved_is_six_bits(reserved):
    with pytest.raises(ValueError):
        rtcm3.encode_frame(b"", reserved)


@pytest.mark.parametrize("bit", range(14, 24))
def test_flipped_length_bit_is_invalid(bit):
    damaged = bytearray(EXAMPLE)
    damaged[bit // 8] ^= 0x80 >> (bit % 8)
    total = 6 + (int.from_bytes(damaged[1:3], "big") & 0x3FF)
    if total > len(EXAMPLE):
        assert rtcm3.parse(bytes(damaged)) == NeedMore(total)
    for fill in (0x00, 0xFF, 0xD3):
        result = rtcm3.parse(bytes(damaged) + bytes([fill]) * 1029)
        assert result == Invalid("CRC-24Q mismatch"), (fill, result)


@pytest.mark.parametrize(("data", "result"), [
    (b"", NeedMore(0)),
    (b"\xd3", NeedMore(0)),
    (b"\xd3\x00", NeedMore(0)),
    (EXAMPLE[:3], NeedMore(25)),
    (EXAMPLE[:-1], NeedMore(25)),
    (b"\xd2", Invalid("no 0xD3 preamble")),
    (EXAMPLE[:-1] + b"\x99", Invalid("CRC-24Q mismatch")),
])
def test_parse_cases(data, result):
    assert rtcm3.parse(data) == result


def test_scan_finds_the_example_after_false_preambles():
    # The example's own payload contains D3 (byte 5); a D3 in front with a
    # length that runs past the end of the buffer is skipped too.
    stream = b"\xd3\x03\xff" + b"\xd3" + EXAMPLE + EXAMPLE
    assert [f.offset for f in rtcm3.scan(stream)] == [4, 29]
