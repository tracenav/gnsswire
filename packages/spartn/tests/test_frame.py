"""SPARTN framing against SPARTN v2.0.3 section 7, Tables 7.1 and 7.2.

The document prints no example frame, so frames here are assembled bit by
bit from Table 7.1 in this file (``build``), independently of the codec's
own writer, with CRCs from the catalogue parameters. The properties shared
with the other codecs (truncation, bit flips, scan through garbage) are in
tests/test_framing.py.

Local recordings (build/private/, never committed), when present, check
the readings the tables leave open (test_private_*): the frame CRC is the
reflected CRC-4 of Table 7.1, and each message CRC is the literal reading of
Table 7.2 over TF002 to TF017 and not the other one.
"""

import itertools
from pathlib import Path

import pytest

from gnsswire import spartn
from gnsswire.bits import (
    CRC8_SMBUS,
    CRC16_IBM_3740,
    CRC16_XMODEM,
    CRC24_LTE_A,
    CRC24_OPENPGP,
    CRC32_BZIP2,
    CRC32_ISO_HDLC,
    BitWriter,
    Crc,
)
from gnsswire.spartn import Description, Frame, Invalid, NeedMore

LITERAL = {0: CRC8_SMBUS, 1: CRC16_XMODEM, 2: CRC24_LTE_A, 3: CRC32_BZIP2}


def crc4_bitwise(data: bytes) -> int:
    """Table 7.1's CRC-4 done bit by bit: poly x^4 + x^3 + 1 reflected (0x9 -> 0b1001 read LSB first)."""
    reg = 0
    for byte in data:
        for i in range(8):                       # input reflected: LSB of each byte first
            bit = (byte >> i) & 1
            top = (reg ^ bit) & 1
            reg >>= 1
            if top:
                reg ^= 0b1001                    # reflection of 0x9 in four bits is 0x9
    return reg                                   # output reflected: the register as held


def build(message_type=0, eaf=0, crc_type=2, subtype=0, time_tag_type=1, time_tag=0x0123_4567,
          solution_id=1, processor_id=3, encryption_id=0, sequence=0, auth_indicator=0,
          auth_length=0, payload=b"\x55\xaa", auth=b"", crc=None, frame_crc=None) -> bytes:
    """A frame laid out field by field from Table 7.1."""
    w = BitWriter()
    w.uint(0x73, 8)                          # TF001
    w.uint(message_type, 7)                  # TF002
    w.uint(len(payload), 10)                 # TF003
    w.uint(eaf, 1)                           # TF004
    w.uint(crc_type, 2)                      # TF005
    start = w.to_bytes()                     # 25 bits written, padded with zeros
    tf006 = crc4_bitwise(start[1:4]) if frame_crc is None else frame_crc
    w.uint(tf006, 4)                         # TF006
    w.uint(subtype, 4)                       # TF007
    w.uint(time_tag_type, 1)                 # TF008
    w.uint(time_tag, 32 if time_tag_type else 16)   # TF009
    w.uint(solution_id, 7)                   # TF010
    w.uint(processor_id, 4)                  # TF011
    if eaf:
        w.uint(encryption_id, 4)             # TF012
        w.uint(sequence, 6)                  # TF013
        w.uint(auth_indicator, 3)            # TF014
        w.uint(auth_length, 3)               # TF015
    assert w.pos % 8 == 0
    w.octets(payload)                        # TF016
    w.octets(auth)                           # TF017
    body = w.to_bytes()
    c = LITERAL[crc_type]
    value = c(body[1:]) if crc is None else crc
    return body + value.to_bytes(c.width // 8, "big")   # TF018


def test_frame_crc_is_table_7_1_crc4():
    for data in itertools.product(range(0, 256, 17), repeat=3):
        nibble = bytes((data[0], data[1], data[2] & 0xF0))
        assert spartn.frame_crc(b"\x73" + nibble) == crc4_bitwise(nibble)


def test_crc_types_are_the_literal_reading_of_table_7_2():
    assert spartn.CRCS == LITERAL
    for c, width, poly, init, xorout in [(LITERAL[0], 8, 0x07, 0, 0), (LITERAL[1], 16, 0x1021, 0, 0),
                                         (LITERAL[2], 24, 0x864CFB, 0, 0),
                                         (LITERAL[3], 32, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF)]:
        assert (c.width, c.poly, c.init, c.xorout, c.refin, c.refout) == (
            width, poly, init, xorout, False, False)


# The CRC catalogue's entries (refs/crc-catalogue-all.htm; see refs/README.md)
# with Table 7.2's polynomial, initialisation and final XOR and no reflection,
# with their published check values (the CRC of b"123456789") and residues.
CATALOGUE = {
    0: ("CRC-8/SMBUS", "width=8  poly=0x07  init=0x00  refin=false  refout=false  xorout=0x00  "
        "check=0xf4  residue=0x00"),
    1: ("CRC-16/XMODEM", "width=16  poly=0x1021  init=0x0000  refin=false  refout=false  "
        "xorout=0x0000  check=0x31c3  residue=0x0000"),
    2: ("CRC-24/LTE-A", "width=24  poly=0x864cfb  init=0x000000  refin=false  refout=false  "
        "xorout=0x000000  check=0xcde703  residue=0x000000"),
    3: ("CRC-32/BZIP2", "width=32  poly=0x04c11db7  init=0xffffffff  refin=false  refout=false  "
        "xorout=0xffffffff  check=0xfc891918  residue=0xc704dd7b"),
}


@pytest.mark.parametrize("crc_type", range(4))
def test_crc_types_are_catalogue_entries_with_their_check_values(crc_type):
    # Table 7.2 gives polynomial, initialisation and final XOR, and states
    # reflection for none of the four, where Table 7.1 states it for the
    # CRC-4. The literal reading is each catalogue entry above; the
    # catalogue's check value and residue confirm the implementation. The
    # other reading of each (reflected, or OpenPGP's initialisation for
    # "Radix-64") has a different check value, so the two cannot be confused.
    name, line = CATALOGUE[crc_type]
    p = dict(item.split("=") for item in line.split())
    c = spartn.CRCS[crc_type]
    assert c.name == name
    assert (c.width, c.poly, c.init, c.xorout) == (int(p["width"]), int(p["poly"], 16),
                                                    int(p["init"], 16), int(p["xorout"], 16))
    assert (c.refin, c.refout) == (p["refin"] == "true", p["refout"] == "true")
    assert c(b"123456789") == c.check == int(p["check"], 16)
    # Residue: the register after a message and its CRC, before the final XOR.
    data = bytes(range(40))
    framed = data + c(data).to_bytes(c.width // 8, "big")
    assert c(framed) ^ c.xorout == int(p["residue"], 16)
    assert OTHER_READING[crc_type](b"123456789") != c.check
    # A frame of each type built bit by bit parses, and fails with the other CRC.
    raw = build(crc_type=crc_type, payload=bytes(range(50)))
    assert isinstance(spartn.parse(raw), Frame)
    n = c.width // 8
    other = OTHER_READING[crc_type](raw[1:-n])
    assert isinstance(spartn.parse(raw[:-n] + other.to_bytes(n, "big")), Invalid)


@pytest.mark.parametrize("crc_type", range(4))
@pytest.mark.parametrize("time_tag_type", [0, 1])
def test_hand_built_frames_parse(crc_type, time_tag_type):
    tag = 43_199 if time_tag_type == 0 else 0xFFFF_FFFF
    raw = build(message_type=1, crc_type=crc_type, subtype=2, time_tag_type=time_tag_type,
                time_tag=tag, solution_id=127, processor_id=15, payload=bytes(range(30)))
    frame = spartn.parse(b"junk" + raw, 4)
    assert frame == Frame(4, len(raw), 1, 0, crc_type,
                          Description(2, time_tag_type, tag, 127, 15, None, None, None, None),
                          bytes(range(30)))
    assert len(raw) == 4 + (6 if time_tag_type else 4) + 30 + (crc_type + 1)
    assert spartn.encode(frame) == raw


@pytest.mark.parametrize(("indicator", "length"), [
    (0, 0), (0, 7), (1, 3), (1, 6), (2, 0), (2, 1), (2, 2), (2, 3), (2, 4), (3, 2), (7, 4)])
def test_encrypted_frames_keep_their_fields_and_authentication(indicator, length):
    # TF017 follows the payload only when TF014 > 1, with the TF015 length;
    # otherwise TF015 is ignored, but kept.
    auth_bits = {0: 64, 1: 96, 2: 128, 3: 256, 4: 512}
    auth = bytes(range(auth_bits[length] // 8)) if indicator > 1 else b""
    raw = build(eaf=1, encryption_id=9, sequence=63, auth_indicator=indicator,
                auth_length=length, payload=b"\x01\x02\x03", auth=auth, time_tag_type=0,
                time_tag=12_345)
    frame = spartn.parse(raw)
    assert isinstance(frame, Frame), frame
    assert frame.description == Description(0, 0, 12_345, 1, 3, 9, 63, indicator, length)
    assert (frame.payload, frame.auth, frame.length) == (b"\x01\x02\x03", auth, len(raw))
    assert spartn.encode(frame) == raw


@pytest.mark.parametrize("length", [5, 6, 7])
def test_undefined_authentication_length_is_invalid(length):
    raw = build(eaf=1, auth_indicator=2, auth_length=length)
    result = spartn.parse(raw)
    assert isinstance(result, Invalid) and "TF015" in result.reason


def test_message_crc_excludes_the_preamble():
    good = build()
    assert isinstance(spartn.parse(good), Frame)
    body = good[:-3]
    with_preamble = body + CRC24_LTE_A(body).to_bytes(3, "big")
    assert spartn.parse(with_preamble) == Invalid("message CRC (TF018) mismatch")


def test_corruption_is_invalid():
    raw = build()
    assert spartn.parse(b"\x72" + raw[1:]) == Invalid("no 0x73 preamble")
    bad_start = build(frame_crc=crc4_bitwise(build()[1:4]) ^ 1)
    assert spartn.parse(bad_start) == Invalid("frame CRC (TF006) mismatch")
    bad_crc = raw[:-1] + bytes((raw[-1] ^ 0x01,))
    assert spartn.parse(bad_crc) == Invalid("message CRC (TF018) mismatch")


def test_truncation_needs_more():
    raw = build(eaf=1, auth_indicator=2, auth_length=1, auth=bytes(12), time_tag_type=0,
                time_tag=12_345)
    head = 4 + 4 + 2
    for cut in range(len(raw)):
        result = spartn.parse(raw[:cut])
        assert isinstance(result, NeedMore), cut
        # The total is known once the payload description is in.
        assert result.needed == (len(raw) if cut >= head else 0), cut
    assert spartn.parse(b"") == NeedMore(0)


def test_empty_payload_and_largest_payload():
    for payload in (b"", bytes(1023)):
        raw = build(payload=payload)
        frame = spartn.parse(raw)
        assert isinstance(frame, Frame) and frame.payload == payload


def test_encode_frame_matches_the_hand_built_frame():
    d = Description(5, 0, 40_000, 100, 7, 3, 2, 2, 0)
    raw = build(message_type=120, eaf=1, crc_type=3, subtype=5, time_tag_type=0, time_tag=40_000,
                solution_id=100, processor_id=7, encryption_id=3, sequence=2, auth_indicator=2,
                auth_length=0, payload=b"abc", auth=bytes(8))
    assert spartn.encode_frame(120, 1, 3, d, b"abc", bytes(8)) == raw


@pytest.mark.parametrize("args", [
    (128, 0, 2, Description(0, 1, 0, 0, 0, None, None, None, None), b""),
    (0, 2, 2, Description(0, 1, 0, 0, 0, None, None, None, None), b""),
    (0, 0, 4, Description(0, 1, 0, 0, 0, None, None, None, None), b""),
    (0, 0, 2, Description(0, 1, 0, 0, 0, None, None, None, None), bytes(1024)),
    (0, 0, 2, Description(16, 1, 0, 0, 0, None, None, None, None), b""),
    (0, 0, 2, Description(0, 0, 1 << 16, 0, 0, None, None, None, None), b""),
    (0, 1, 2, Description(0, 1, 0, 0, 0, None, None, None, None), b""),     # EAF needs TF012..15
    (0, 0, 2, Description(0, 1, 0, 0, 0, 1, 1, 0, 0), b""),                 # and only with EAF
    (0, 1, 2, Description(0, 1, 0, 0, 0, 0, 0, 2, 5), b""),                 # undefined TF015
])
def test_encode_frame_refuses(args):
    with pytest.raises(ValueError):
        spartn.encode_frame(*args)


def test_encode_frame_checks_the_authentication_length():
    d = Description(0, 1, 0, 0, 0, 0, 0, 2, 1)
    assert spartn.parse(spartn.encode_frame(0, 1, 2, d, b"", bytes(12))).auth == bytes(12)
    for wrong in (b"", bytes(8), bytes(13)):
        with pytest.raises(ValueError, match="authentication"):
            spartn.encode_frame(0, 1, 2, d, b"", wrong)
    plain = Description(0, 1, 0, 0, 0, 0, 0, 1, 1)
    with pytest.raises(ValueError, match="authentication"):
        spartn.encode_frame(0, 1, 2, plain, b"", bytes(12))


# --- private captures ------------------------------------------------------------------------
#
# build/private/ (gitignored, never committed) may hold unencrypted SPARTN
# streams (spartn_ip_*.bin) and UBX recordings of RXM-PMP frames whose user
# data is a SPARTN stream (pmp_*.bin). Nothing from these files is copied
# into the repository.

PRIVATE = Path(__file__).resolve().parents[3] / "build" / "private"
private = pytest.mark.skipif(not PRIVATE.is_dir(),
                             reason="private captures (build/private/) are absent")


def private_ip_streams() -> list[tuple[str, bytes]]:
    return [(p.name, p.read_bytes()) for p in sorted(PRIVATE.glob("spartn_ip_*.bin"))]


@private
def test_private_ip_streams_are_frames_end_to_end():
    for name, stream in private_ip_streams():
        frames = list(spartn.scan(stream))
        at = 0
        for f in frames:
            assert f.offset == at, (name, at)   # no byte between frames is skipped
            assert spartn.encode(f) == stream[f.offset:f.offset + f.length], (name, f.offset)
            at += f.length
        assert at == len(stream) and frames, name


# The other reading of each message CRC type that Table 7.2's names suggest.
OTHER_READING = {0: Crc("CRC-8/reflected", 8, 0x07, 0, True, True, 0, None),
                 1: CRC16_IBM_3740, 2: CRC24_OPENPGP, 3: CRC32_ISO_HDLC}


@private
def test_private_frames_check_the_crc_readings():
    # Table 7.1's CRC-4 is reflected, and an unreflected CRC-4 of the same
    # polynomial disagrees with most frames. Every frame's message CRC is
    # the literal reading of Table 7.2 over TF002 to TF017 (parse checks
    # it) and not the other reading of its type.
    plain4 = Crc("CRC-4/unreflected", 4, 0x9, 0, False, False, 0, None)
    frames = disagree4 = 0
    for name, stream in private_ip_streams():
        for f in spartn.scan(stream):
            raw = stream[f.offset:f.offset + f.length]
            start = bytes((raw[1], raw[2], raw[3] & 0xF0))
            assert crc4_bitwise(start) == raw[3] & 0xF
            disagree4 += plain4(start) != raw[3] & 0xF
            n = LITERAL[f.crc_type].width // 8
            assert OTHER_READING[f.crc_type](raw[1:-n]) != int.from_bytes(raw[-n:], "big"), \
                (name, f.offset)
            frames += 1
    assert disagree4 > frames // 2


@private
def test_private_lband_stream_frames():
    # RXM-PMP user data joined in order. Frames that cross a gap in the
    # recording are cut; scan skips those and recovers the frames that lie
    # whole inside the joined data.
    from gnsswire import ubx
    for path in sorted(PRIVATE.glob("pmp_*.bin")):
        stream = b"".join(ubx.decode(f).user_data for f in ubx.scan(path.read_bytes()))
        frames = list(spartn.scan(stream))
        assert frames, path.name
        for f in frames:
            assert spartn.encode(f) == stream[f.offset:f.offset + f.length], f.offset
            if f.eaf:
                assert f.description.auth_indicator is not None
