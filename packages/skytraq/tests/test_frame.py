"""SkyTraq framing against AN0039 version 1.4.42, "Binary Message Structure".

Every example frame the note prints for the messages of this codec is
checked here as a frame; their fields are checked in test_messages.py. The
properties shared with the other codecs (truncation, bit flips, scan through
garbage) are in tests/test_framing.py.
"""

from functools import reduce

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gnsswire import skytraq
from gnsswire.skytraq import Frame, Invalid, NeedMore

# The example frames of AN0039 version 1.4.42, as printed, by message ID.
EXAMPLES = {
    0xDC: "A0A1000ADC3D06ED0B0CBC4003E81A0D0A",
    0xDD: (
        "A0A1015CDD3D0F022B417442DB7655FA29C0E2E402215A00004420800007092941778CF0A9E70C43C0F972542EEB8000"
        "44E3A000070A284175CA9691A9E92341047DB1E9A98000C531200007052B41749EBEEE178C6A40D371D480CF0000C3AE"
        "0000071A2E41750283E5ECD765C1046D73BDE6200045333000070C284177C1E01DA72EC140FF794CC9148000C50D8000"
        "0711284177E7B0E8159AA8410C87990CFAA000C580D800070F274177939677032B0AC106BF2C49056000454FB0000704"
        "2C4175BA4EB0682B4340FB25C7A3B6C000C4FE60000707264178487F72DFC581C0D089C8BF96000043A78000070D1D00"
        "000000000000004105F9A2D60D4000C566000016082741786AD7A4712A50C0EF02442E09800044A2800007192341787E"
        "E48B0C9E2640E6AD042B858000C498200007421F417527EAE2167D104106D60A576B0000C553100007521E0000000000"
        "000000C0FE83495DA700004516C00006AA0D0A"),
    0xE0: "A0A10021E002058B0BB43F22B54F31CF4EFD81FD4D00A10C9879E70908D5C5F8ED03EBFFF4040D0A",
    0xE1: "A0A1000CE1520EB405A9C39417500482330D0A",
    0xE2: "A0A1001FE2CF01E240473758000DA0E100AC03878E315B53B412B2C0025B046007AB81B10D0A",
    0xE3: "A0A1001FE3CB01E240473795A514C8CAEACFA500155555555555555555555555555555480D0A",
    0xE5: (
        "A0A1021DE5010D077C06AC408003E8000011000DE03241B333998962C9BA41B37F98FDADE00045794000000000400700"
        "000002E03141B3223EEDEAFBD641B3B3B83AEBA00044F14000000000400700000006E03041B331EE4F2D2CD941B3E377"
        "47152000C3390000000000400700000004E03341B321A6729C9E8D41B3973F772B6000452EF000000000400700000005"
        "E03141B32452846C890E41B3C4EF07A8E000447CC00000000040070000000CE02941B355D6AE0764C541B3F59AF1B5E0"
        "00C47C0000000000C00700000014E02941B353251698940341B399D7199B600045406000000000800700000013E02C41"
        "B348024B63BFD041B415801AC76000C516D0000000004007000004C1E03041B43D6815865B8741B3D237DB1A2000443D"
        "0000000000400700000180C02D41B4266A74EBC09741B3CC0C4553A00044710000000000400700000181C02B41B419E0"
        "D3AB6BBA41B3CCACC2C42000446FC000000000400700000206E33141B315160223161C41B40A579761200044BAA00000"
        "0000400700000205E82D41B321D878415F3541B45E187C73A000C4E30000000000400700000214E92D41B30B5279C494"
        "0841B40FE810A16000449E4000000000400700000213EA2C41B33072528C680F41B4686E04CFE000C50F900000000040"
        "0700000215EB2F41B32A46FD31683941B3D08EE512E000458DA800000000400700000207EC2C41B345AB043961D641B3"
        "E552581020004572B00000000080070000CA0D0A"),
    0xE6: "A0A10025E601031E0806FFFFFFFF00000012783589E24D800086EE80000000002AAAAA664E753F4000ED0D0A",
}
FRAMES = {msg_id: bytes.fromhex(h) for msg_id, h in EXAMPLES.items()}
# The PL each example prints (the 348 and 541 under the long ones included).
PL = {0xDC: 10, 0xDD: 348, 0xE0: 33, 0xE1: 12, 0xE2: 31, 0xE3: 31, 0xE5: 541, 0xE6: 37}


def prose_checksum(payload: bytes) -> int:
    """"The 8-bit exclusive OR of only the payload bytes which start from Message ID"."""
    return reduce(lambda a, b: a ^ b, payload, 0)


@given(st.binary(max_size=2000))
def test_checksum_is_the_xor_of_the_payload(data):
    assert skytraq.checksum(data) == prose_checksum(data)


@pytest.mark.parametrize("msg_id", sorted(FRAMES))
def test_example_frames(msg_id):
    raw = FRAMES[msg_id]
    assert raw[2:4] == PL[msg_id].to_bytes(2, "big")
    frame = skytraq.parse(raw)
    assert frame == Frame(0, 7 + PL[msg_id], msg_id, raw[5:-3])
    assert raw[-3] == prose_checksum(raw[4:-3])
    assert skytraq.encode(frame) == raw
    assert skytraq.encode_frame(msg_id, frame.body) == raw


@pytest.mark.parametrize("msg_id", sorted(FRAMES))
def test_pseudo_code_read_literally_is_circular(msg_id):
    # The checksum pseudo-code loops "For n = 0 to N", N = PL. Over PL + 1
    # bytes from the message ID it takes in the checksum byte itself, and
    # the XOR is then 0 for every frame, so it cannot be what is meant.
    raw = FRAMES[msg_id]
    assert prose_checksum(raw[4:4 + PL[msg_id] + 1]) == 0


def test_pl_is_big_endian_and_counts_the_message_id():
    body = bytes(range(256)) * 2   # payload 513 = 0x0201 bytes
    raw = skytraq.encode_frame(0x7F, body)
    assert raw[:4] == b"\xa0\xa1\x02\x01"
    assert len(raw) == 7 + 513 and raw[4] == 0x7F and raw[-2:] == b"\r\n"
    assert skytraq.parse(raw) == Frame(0, 520, 0x7F, body)


def test_largest_payload():
    body = bytes(skytraq.MAX_PAYLOAD - 1)
    raw = skytraq.encode_frame(0xFF, body)
    assert raw[2:4] == b"\xff\xff"
    assert skytraq.parse(raw).body == body
    with pytest.raises(ValueError):
        skytraq.encode_frame(0xFF, body + b"\0")


@pytest.mark.parametrize("msg_id", [0, 256, -1])
def test_message_id_is_1_to_255(msg_id):
    with pytest.raises(ValueError):
        skytraq.encode_frame(msg_id, b"")


def test_message_id_alone():
    raw = skytraq.encode_frame(0x01, b"")
    assert raw == bytes.fromhex("a0a1 0001 01 01 0d0a")
    assert skytraq.parse(raw) == Frame(0, 8, 0x01, b"")


def test_refusals():
    good = FRAMES[0xDC]
    assert skytraq.parse(b"\xa0") == NeedMore(0)
    assert skytraq.parse(b"\xa0\xa1\x00") == NeedMore(0)
    assert skytraq.parse(good[:5]) == NeedMore(len(good))
    assert isinstance(skytraq.parse(b"\xa1\xa0" + good[2:]), Invalid)
    assert isinstance(skytraq.parse(b"\xa0\xa2"), Invalid)
    assert skytraq.parse(bytes.fromhex("a0a1 0000 00 0d0a")) == Invalid(
        "payload length 0: no message ID")
    # Message ID 0 with a valid checksum and end sequence.
    assert skytraq.parse(bytes.fromhex("a0a1 0001 00 00 0d0a")) == Invalid(
        "message ID 0 is outside 0x01 to 0xFF")
    for end in (b"\r\r", b"\n\n", b"\n\r"):
        assert isinstance(skytraq.parse(good[:-2] + end), Invalid)
    assert isinstance(skytraq.parse(good[:-3] + bytes([good[-3] ^ 1]) + good[-2:]), Invalid)


def test_a_wrong_pl_is_refused():
    # A PL one short or one long moves the checksum and end sequence.
    good = FRAMES[0xE1]
    for pl in (PL[0xE1] - 1, PL[0xE1] + 1):
        damaged = good[:2] + pl.to_bytes(2, "big") + good[4:] + b"\0"
        assert isinstance(skytraq.parse(damaged), Invalid)


def test_scan_through_the_examples():
    stream = b"\xa0\xa1\x00" + b"".join(b"\xa0" + raw for raw in FRAMES.values())
    got = list(skytraq.scan(stream))
    assert [f.msg_id for f in got] == list(FRAMES)
    assert all(skytraq.encode(f) == stream[f.offset:f.offset + f.length] for f in got)
