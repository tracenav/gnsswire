"""UBX framing against the u-blox F9 HPG 1.51 Interface Description, sections 3.2 and 3.4.

The document prints no complete frame with its checksum, so the vectors here
are worked by hand from section 3.4's pseudo-code, and the implementation's
checksum is checked against a literal transcription of that pseudo-code. The
properties shared with the other codecs (truncation, bit flips, scan through
garbage) are in tests/test_framing.py.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gnsswire import ubx
from gnsswire.ubx import Frame, Invalid, NeedMore


def pseudo_code(buffer: bytes) -> tuple[int, int]:
    """Section 3.4, line by line, masking with 0xFF "after both operations in the loop"."""
    ck_a = ck_b = 0
    for i in range(len(buffer)):
        ck_a = (ck_a + buffer[i]) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


@given(st.binary(max_size=2000))
def test_checksum_is_the_section_3_4_algorithm(data):
    assert tuple(ubx.checksum(data)) == pseudo_code(data)


# UBX-ACK-ACK (class 0x05, ID 0x01, length 2; section 3.9.1) acknowledging
# class 0x06, ID 0x00. Over 05 01 02 00 06 00:
#   CK_A: 05 06 08 08 0E 0E -> 0x0E
#   CK_B: 05 0B 13 1B 29 37 -> 0x37
ACK_ACK = bytes.fromhex("b562 0501 0200 0600 0e37")
# A poll has no payload (section 3.5.2): class 0x06, ID 0x00 alone.
#   CK_A: 06 06 06 06 -> 0x06;  CK_B: 06 0C 12 18 -> 0x18
POLL = bytes.fromhex("b562 0600 0000 0618")


def test_hand_worked_frames():
    assert ubx.parse(ACK_ACK) == Frame(0, 10, 0x05, 0x01, b"\x06\x00")
    assert ubx.encode_frame(0x05, 0x01, b"\x06\x00") == ACK_ACK
    assert ubx.parse(POLL) == Frame(0, 8, 0x06, 0x00, b"")
    assert ubx.encode(ubx.parse(POLL)) == POLL


def test_length_is_little_endian_and_payload_only():
    payload = bytes(range(256)) * 2 + b"\x01"   # 513 = 0x0201 bytes
    frame = ubx.encode_frame(0x02, 0x13, payload)
    assert frame[4:6] == b"\x01\x02"
    assert len(frame) == 8 + 513
    assert ubx.parse(frame).payload == payload


def test_largest_payload():
    payload = bytes(range(256)) * 255 + bytes(range(255))
    assert len(payload) == ubx.MAX_PAYLOAD
    frame = ubx.encode_frame(0xFF, 0xFF, payload)
    assert ubx.parse(frame) == Frame(0, len(frame), 0xFF, 0xFF, payload)
    with pytest.raises(ValueError):
        ubx.encode_frame(0, 0, payload + b"\0")


@pytest.mark.parametrize("args", [(256, 0), (0, 256), (-1, 0)])
def test_class_and_id_are_bytes(args):
    with pytest.raises(ValueError):
        ubx.encode_frame(*args, b"")


@pytest.mark.parametrize("bit", range(32, 48))
@pytest.mark.parametrize("frame", [ACK_ACK, POLL])
def test_flipped_length_bit_is_invalid(frame, bit):
    damaged = bytearray(frame)
    damaged[bit // 8] ^= 0x80 >> (bit % 8)
    total = 8 + int.from_bytes(damaged[4:6], "little")
    if total > len(frame):
        assert ubx.parse(bytes(damaged)) == NeedMore(total)
    # Whatever follows the frame, the checksum no longer holds.
    for fill in (0x00, 0xFF, 0x55):
        result = ubx.parse(bytes(damaged) + bytes([fill]) * 0x10000)
        assert result == Invalid("checksum mismatch"), (fill, result)


@pytest.mark.parametrize(("data", "result"), [
    (b"", NeedMore(0)),
    (b"\xb5", NeedMore(0)),
    (b"\xb5\x62\x05\x01\x02", NeedMore(0)),
    (b"\xb5\x62\x05\x01\x02\x00", NeedMore(10)),
    (ACK_ACK[:-1], NeedMore(10)),
    (b"\x62", Invalid("no 0xB5 0x62 preamble")),
    (b"\xb5\xb5", Invalid("no 0xB5 0x62 preamble")),
    (ACK_ACK[:-1] + b"\x38", Invalid("checksum mismatch")),
    (ACK_ACK[:-2] + b"\x37\x0e", Invalid("checksum mismatch")),
])
def test_parse_cases(data, result):
    assert ubx.parse(data) == result


def test_scan_skips_a_false_sync_inside_a_frame():
    # B5 62 inside a payload is data, not a new frame.
    inner = ubx.encode_frame(0x01, 0x02, b"")
    outer = ubx.encode_frame(0x02, 0x15, inner)
    assert [(f.offset, f.msg_class) for f in ubx.scan(b"\xb5" + outer + inner)] == [
        (1, 0x02), (1 + len(outer), 0x01)]
