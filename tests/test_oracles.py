"""Framing cross-check against independent open-source decoders (README.md, "Contribute").

pynmeagps, pyubx2, pyrtcm and pyspartn are dev-only dependencies, used here as oracles
through their public API and never imported by the packages
(tests/test_layout.py). The codecs were written from the specifications, not
from these libraries; this file only checks that both sides agree:

- the checksum in every frame our ``encode_frame`` builds is the one the
  oracle's checksum helper computes, and a damaged checksum is refused by
  both;
- frames the oracles build parse here to the payload the oracle holds;
- the oracles' stream readers, with parsing off, cut a stream into the same
  frames as our ``scan``.
"""

import io
import random
from pathlib import Path

import pynmeagps
import pyrtcm
import pyspartn
import pyubx2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import nmea, rtcm3, spartn, ubx

DATA = Path(__file__).resolve().parents[1] / "packages" / "rtcm3" / "tests" / "data"
FIELD_CHARS = "".join(chr(c) for c in range(0x20, 0x7F) if chr(c) not in "$*")
fast = settings(max_examples=100, derandomize=True, deadline=None)


def corpus_frames() -> list[bytes]:
    frames = []
    for path in sorted(DATA.glob("*.hex")):
        for line in path.read_text().splitlines():
            if line and not line.startswith("#"):
                frames.append(bytes.fromhex(line.partition("#")[0].strip()))
    return frames


CORPUS = corpus_frames()

nmea_frames = st.builds(
    lambda a, f: nmea.encode_frame((a + "".join("," + x for x in f)).encode()),
    st.from_regex(r"[A-Z]{2}[A-Z]{3}", fullmatch=True),
    st.lists(st.text(FIELD_CHARS, max_size=12), max_size=12))
ubx_frames = st.builds(ubx.encode_frame, st.integers(0, 255), st.integers(0, 255),
                       st.binary(max_size=300))
rtcm3_frames = st.builds(rtcm3.encode_frame, st.binary(max_size=1023))


# --- checksums ------------------------------------------------------------------

@fast
@given(nmea_frames)
def test_nmea_checksum_matches_pynmeagps(frame):
    star = frame.rindex(b"*")
    body = frame[1:star].decode("ascii")
    assert pynmeagps.calc_checksum(body) == frame[star + 1:star + 3].decode()


@fast
@given(ubx_frames)
def test_ubx_checksum_matches_pyubx2(frame):
    assert pyubx2.calc_checksum(frame[2:-2]) == frame[-2:]
    assert pyubx2.isvalid_checksum(frame)


@fast
@given(rtcm3_frames)
def test_rtcm3_crc_matches_pyrtcm(frame):
    assert pyrtcm.crc2bytes(frame[:-3]) == frame[-3:]
    assert pyrtcm.calc_crc24q(frame) == 0


@fast
@given(st.data())
def test_damaged_checksum_is_refused_by_both(data):
    which = data.draw(st.sampled_from(["nmea", "ubx", "rtcm3"]))
    frame = data.draw({"nmea": nmea_frames, "ubx": ubx_frames, "rtcm3": rtcm3_frames}[which])
    if which == "nmea":
        # Replace one checksum digit with another uppercase hex digit.
        at = frame.rindex(b"*") + data.draw(st.sampled_from([1, 2]))
        digit = data.draw(st.sampled_from([c for c in b"0123456789ABCDEF" if c != frame[at]]))
        damaged = frame[:at] + bytes([digit]) + frame[at + 1:]
        star = damaged.rindex(b"*")
        assert pynmeagps.calc_checksum(damaged[1:star].decode()) != damaged[star + 1:star + 3].decode()
        assert isinstance(nmea.parse(damaged), nmea.Invalid)
        return
    width = 2 if which == "ubx" else 3
    bit = data.draw(st.integers(0, 8 * width - 1))
    damaged = bytearray(frame)
    damaged[len(frame) - width + bit // 8] ^= 0x80 >> (bit % 8)
    damaged = bytes(damaged)
    if which == "ubx":
        assert not pyubx2.isvalid_checksum(damaged)
        assert isinstance(ubx.parse(damaged), ubx.Invalid)
    else:
        assert pyrtcm.calc_crc24q(damaged) != 0
        assert isinstance(rtcm3.parse(damaged), rtcm3.Invalid)


# --- frames the oracles build ------------------------------------------------------

def test_pyubx2_frames_parse_here():
    messages = [
        pyubx2.UBXMessage("NAV", "NAV-PVT", 0, payload=bytes(range(92))),
        pyubx2.UBXMessage("NAV", "NAV-TIMELS", 0, payload=bytes(24)),
        pyubx2.UBXMessage(0x99, 0x42, 0, payload=b"\x01\x02\x03"),
        pyubx2.UBXMessage("CFG", "CFG-VALGET", 2, payload=bytes(8)),
    ]
    for m in messages:
        raw = m.serialize()
        frame = ubx.parse(raw)
        assert isinstance(frame, ubx.Frame), m
        assert (frame.msg_class, frame.msg_id, frame.payload) == (raw[2], raw[3], m.payload)
        assert ubx.encode(frame) == raw


def test_pynmeagps_frames_parse_here():
    messages = [
        pynmeagps.NMEAMessage("GP", "GGA", 0, time="092725.00", lat=47.285233, NS="N",
                              lon=8.565265, EW="E", quality=1, numSV=8, HDOP=1.01, alt=499.6,
                              altUnit="M", sep=48.0, sepUnit="M"),
        pynmeagps.NMEAMessage("GN", "ZDA", 0, payload=["082710.00", "16", "09", "2002", "00", "00"]),
        pynmeagps.NMEAMessage("GA", "GSV", 0, payload=["1", "1", "02", "07", "45", "120", "40"]),
    ]
    for m in messages:
        raw = m.serialize()
        frame = nmea.parse(raw)
        assert isinstance(frame, nmea.Frame), (raw, frame)
        assert nmea.encode(frame) == raw
        assert frame.payload.split(b",")[0] == (m.talker + m.msgID).encode()


def test_pyrtcm_frames_equal_ours():
    # RTCMMessage parses the payload, and pyrtcm 1.2.1 raises on MSM2 (an
    # error in its own MSM2 definition; packages/rtcm3/tests/test_messages.py).
    msm2 = {10 * system + 2 for system in range(107, 113)}
    for raw in CORPUS:
        if int.from_bytes(raw[3:5], "big") >> 4 in msm2:
            continue
        payload = raw[3:-3]
        assert pyrtcm.RTCMMessage(payload=payload).serialize() == rtcm3.encode_frame(payload)


# --- stream readers --------------------------------------------------------------

def _oracle_frames(reader) -> list[bytes]:
    return [raw for raw, _ in reader]


def test_pyrtcm_reader_cuts_the_corpus_like_scan():
    rng = random.Random(3)
    stream = b"".join(rng.randbytes(rng.randint(0, 20)).replace(b"\xd3", b"\x00") + f
                      for f in CORPUS)
    ours = [stream[f.offset:f.offset + f.length] for f in rtcm3.scan(stream)]
    theirs = _oracle_frames(pyrtcm.RTCMReader(io.BytesIO(stream), parsed=0, quitonerror=0))
    assert ours == theirs == CORPUS


@pytest.mark.parametrize("seed", range(3))
def test_pyspartn_reader_cuts_streams_like_scan(seed):
    # Frames of every CRC type, both time tag widths and, with EAF set,
    # embedded authentication data; frames only, as for pyubx2 below.
    # Values pyspartn 1.1.2 frames otherwise are left out:
    # embedded authentication lengths TF015 = 1 (96 bits) and 4 (512 bits)
    # of Table 7.1, and the TBD authentication indicators TF014 = 3 to 7,
    # after which it reads no TF017 where Table 7.1 says TF017 is present
    # "when TF014 is set greater than 1".
    rng = random.Random(seed)
    frames = []
    for _ in range(100):
        eaf, tt = rng.randrange(2), rng.randrange(2)
        indicator, length = (rng.randrange(3), rng.choice([0, 2, 3])) if eaf else (None, None)
        d = spartn.Description(rng.randrange(16), tt, rng.randrange(1 << (16 + 16 * tt)),
                               rng.randrange(128), rng.randrange(16),
                               rng.randrange(16) if eaf else None,
                               rng.randrange(64) if eaf else None, indicator, length)
        auth = rng.randbytes((64, 96, 128, 256, 512)[length] // 8) if eaf and indicator > 1 else b""
        frames.append(spartn.encode_frame(rng.randrange(128), eaf, rng.randrange(4), d,
                                          rng.randbytes(rng.randint(1, 200)), auth))
    stream = b"".join(frames)
    ours = [stream[f.offset:f.offset + f.length] for f in spartn.scan(stream)]
    theirs = _oracle_frames(pyspartn.SPARTNReader(io.BytesIO(stream), decode=False,
                                                  quitonerror=0))
    assert ours == theirs == frames


@pytest.mark.parametrize("seed", range(5))
def test_pyubx2_reader_cuts_mixed_streams_like_scan(seed):
    # UBXReader frames NMEA, UBX and RTCM 3 in one stream; with parsing off
    # it returns each frame's bytes. Frames only, no garbage: the readers'
    # resynchronisation policies differ, and agreeing on them is not the point.
    rng = random.Random(seed)
    pieces = []
    for _ in range(150):
        kind = rng.choice(["nmea", "ubx", "rtcm3"])
        if kind == "nmea":
            fields = ["".join(rng.choices(FIELD_CHARS, k=rng.randint(0, 10)))
                      for _ in range(rng.randint(0, 12))]
            address = "G" + "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=4))
            pieces.append(("nmea", nmea.encode_frame((address + "".join("," + f for f in fields)).encode())))
        elif kind == "ubx":
            pieces.append(("ubx", ubx.encode_frame(rng.randrange(256), rng.randrange(256),
                                                   rng.randbytes(rng.randint(0, 200)))))
        else:
            pieces.append(("rtcm3", rng.choice(CORPUS)))
    stream = b"".join(p for _, p in pieces)
    ours = sorted((f.offset, stream[f.offset:f.offset + f.length])
                  for module in (nmea, ubx, rtcm3) for f in module.scan(stream))
    theirs = _oracle_frames(pyubx2.UBXReader(io.BytesIO(stream), protfilter=7, parsing=0,
                                             quitonerror=0, validate=1))
    assert [raw for _, raw in ours] == theirs == [p for _, p in pieces]
