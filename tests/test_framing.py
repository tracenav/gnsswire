"""Framing properties shared by nmea, ubx, rtcm3, spartn and skytraq.

Each codec's own tests check its spec vectors and rules; this file checks the
behaviour every framer must have (README.md, "Use") on frames generated from
the spec:

- ``encode`` of a parsed frame returns the frame's bytes, at any offset;
- every proper prefix of a frame is ``NeedMore``, and a known ``needed`` is
  the frame's length;
- a single flipped bit is ``Invalid`` (bits of the length fields are covered
  on fixed frames in the codec tests: a changed length can move the checksum
  onto other bytes, which a checksum catches only with high probability);
- ``scan`` recovers every intact frame from a stream with garbage between
  frames, truncated frames and frames with garbage spliced into them.
"""

import random
from dataclasses import dataclass
from typing import Any, Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gnsswire import nmea, rtcm3, skytraq, spartn, ubx

# Printable ASCII other than '$' and '*' (nmea/_frame.py).
FIELD_CHARS = "".join(chr(c) for c in range(0x20, 0x7F) if chr(c) not in "$*")


@dataclass(frozen=True)
class Codec:
    module: Any
    frames: st.SearchStrategy[bytes]   # complete frames built with encode_frame
    random_frame: Callable[[random.Random], bytes]
    length_bits: Callable[[bytes], range]   # bit positions of the length field
    preambles: tuple[bytes, ...]       # byte strings that start or end frames


def _nmea_payload(address: str, fields: list[str]) -> bytes:
    return (address + "".join("," + f for f in fields)).encode()


nmea_frames = st.builds(
    lambda a, f: nmea.encode_frame(_nmea_payload(a, f)),
    st.from_regex(r"[0-9A-Z]{1,8}", fullmatch=True),
    st.lists(st.text(FIELD_CHARS, max_size=12), max_size=12),
)
ubx_frames = st.builds(ubx.encode_frame, st.integers(0, 255), st.integers(0, 255),
                       st.binary(max_size=300))
rtcm3_frames = st.builds(rtcm3.encode_frame, st.binary(max_size=1023),
                         st.one_of(st.just(0), st.integers(0, 63)))
skytraq_frames = st.builds(skytraq.encode_frame, st.integers(1, 255), st.binary(max_size=600))


@st.composite
def _spartn_description(draw, eaf: int) -> spartn.Description:
    tt = draw(st.integers(0, 1))
    extra = ((draw(st.integers(0, 15)), draw(st.integers(0, 63)), draw(st.integers(0, 7)),
              draw(st.integers(0, 4))) if eaf else (None,) * 4)
    return spartn.Description(draw(st.integers(0, 15)), tt, draw(st.integers(0, (1 << (16 + 16 * tt)) - 1)),
                              draw(st.integers(0, 127)), draw(st.integers(0, 15)), *extra)


@st.composite
def _spartn_frame(draw) -> bytes:
    eaf = draw(st.integers(0, 1))
    d = draw(_spartn_description(eaf))
    auth = bytes((64, 96, 128, 256, 512)[d.auth_length] // 8) if eaf and d.auth_indicator > 1 else b""
    return spartn.encode_frame(draw(st.integers(0, 127)), eaf, draw(st.integers(0, 3)), d,
                               draw(st.binary(max_size=300)), auth)


spartn_frames = _spartn_frame()


def _spartn_length_bits(frame: bytes) -> range:
    # A SPARTN frame's length depends on TF003, and also on TF008 (the time
    # tag width) and, with EAF set, on TF014 and TF015 (the authentication
    # data). TF003 is covered by TF006; TF008 and TF014/TF015 are not.
    eaf = frame[3] >> 6 & 1
    head = 32 + (48 if frame[4] & 0x08 else 32)
    bits = set(range(36, 37))                       # TF008
    if eaf:
        bits |= set(range(head + 10, head + 16))    # TF014, TF015
    return sorted(bits)  # type: ignore[return-value]


def _random_spartn(rng: random.Random) -> bytes:
    eaf = rng.randrange(2)
    tt = rng.randrange(2)
    indicator = rng.randrange(8) if eaf else None
    length = rng.randrange(5) if eaf else None
    d = spartn.Description(rng.randrange(16), tt, rng.randrange(1 << (16 + 16 * tt)),
                           rng.randrange(128), rng.randrange(16),
                           rng.randrange(16) if eaf else None, rng.randrange(64) if eaf else None,
                           indicator, length)
    auth = (rng.randbytes((64, 96, 128, 256, 512)[length] // 8)
            if eaf and indicator > 1 else b"")
    return spartn.encode_frame(rng.randrange(128), eaf, rng.randrange(4), d,
                               rng.randbytes(rng.choice([0, 1, rng.randint(0, 600)])), auth)


def _random_nmea(rng: random.Random) -> bytes:
    address = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=rng.randint(1, 6)))
    fields = ["".join(rng.choices(FIELD_CHARS, k=rng.randint(0, 10)))
              for _ in range(rng.randint(0, 15))]
    return nmea.encode_frame(_nmea_payload(address, fields))


def _random_ubx(rng: random.Random) -> bytes:
    return ubx.encode_frame(rng.randrange(256), rng.randrange(256),
                            rng.randbytes(rng.choice([0, 1, 2, rng.randint(0, 600)])))


def _random_skytraq(rng: random.Random) -> bytes:
    return skytraq.encode_frame(rng.randint(1, 255),
                                rng.randbytes(rng.choice([0, 1, rng.randint(0, 600)])))


def _random_rtcm3(rng: random.Random) -> bytes:
    return rtcm3.encode_frame(rng.randbytes(rng.choice([0, 1, rng.randint(0, 1023)])),
                              rng.choice([0, 0, 0, rng.randrange(64)]))


CODECS = {
    # NMEA has no length field: the '*' position is found, not read.
    "nmea": Codec(nmea, nmea_frames, _random_nmea, lambda f: range(0),
                  (b"$", b"*", b"\r\n", b"$GP")),
    "ubx": Codec(ubx, ubx_frames, _random_ubx, lambda f: range(32, 48),
                 (b"\xb5", b"\xb5\x62", b"\xb5\x62\x02\x15")),
    "rtcm3": Codec(rtcm3, rtcm3_frames, _random_rtcm3, lambda f: range(14, 24),
                   (b"\xd3", b"\xd3\x00", b"\xd3\x00\x13")),
    "skytraq": Codec(skytraq, skytraq_frames, _random_skytraq, lambda f: range(16, 32),
                     (b"\xa0", b"\xa0\xa1", b"\xa0\xa1\x00")),
    "spartn": Codec(spartn, spartn_frames, _random_spartn, _spartn_length_bits,
                    (b"\x73", b"\x73\x00", b"\x73\x00\x09")),
}

params = pytest.mark.parametrize("name", sorted(CODECS))
fast = settings(max_examples=60, derandomize=True, deadline=None,
                suppress_health_check=[HealthCheck.too_slow])


@params
@fast
@given(data=st.data())
def test_round_trip_at_any_offset(name, data):
    codec = CODECS[name]
    frame = data.draw(codec.frames)
    prefix = data.draw(st.binary(max_size=4))
    suffix = data.draw(st.binary(max_size=4))
    result = codec.module.parse(prefix + frame + suffix, len(prefix))
    assert isinstance(result, codec.module.Frame), result
    assert (result.offset, result.length) == (len(prefix), len(frame))
    assert codec.module.encode(result) == frame


@params
@fast
@given(data=st.data())
def test_truncation_needs_more(name, data):
    codec = CODECS[name]
    frame = data.draw(codec.frames)
    # NMEA, lenient, may also need one byte less: a bare LF would end it.
    lengths = (0, len(frame), len(frame) - 1) if name == "nmea" else (0, len(frame))
    for cut in range(len(frame)):
        result = codec.module.parse(frame[:cut])
        assert isinstance(result, codec.module.NeedMore), (cut, result)
        assert result.needed in lengths, (cut, result)


@params
@fast
@given(data=st.data())
def test_flipped_bit_is_invalid(name, data):
    codec = CODECS[name]
    frame = data.draw(codec.frames)
    excluded = set(codec.length_bits(frame))
    bit = data.draw(st.integers(0, 8 * len(frame) - 1).filter(lambda b: b not in excluded))
    damaged = bytearray(frame)
    damaged[bit // 8] ^= 0x80 >> (bit % 8)
    result = codec.module.parse(bytes(damaged))
    assert isinstance(result, codec.module.Invalid), (bit, result)


def _stream(pieces: list[tuple[bytes, str, bytes, int]]):
    """Assemble frames and garbage; return the stream and the intact frames' spans."""
    stream = bytearray()
    intact = []
    for frame, damage, garbage, cut in pieces:
        stream += garbage
        if damage == "intact":
            intact.append((len(stream), frame))
            stream += frame
        elif damage == "truncated":
            stream += frame[:cut % len(frame)]
        else:   # garbage spliced inside the frame
            at = 1 + cut % (len(frame) - 1)
            spliced = frame[:at] + (garbage[:1] or b"\0") + frame[at:]
            # Splicing frame[0] in after frame[0] only prepends a byte.
            if (k := spliced.find(frame)) >= 0:
                intact.append((len(stream) + k, frame))
            stream += spliced
    return bytes(stream), intact


@params
@fast
@given(data=st.data())
def test_scan_recovers_frames_from_garbage(name, data):
    codec = CODECS[name]
    garbage = st.lists(st.one_of(st.binary(max_size=6), st.sampled_from(codec.preambles)),
                       max_size=4).map(b"".join)
    pieces = data.draw(st.lists(st.tuples(
        codec.frames, st.sampled_from(["intact", "intact", "truncated", "spliced"]),
        garbage, st.integers(0, 2000)), max_size=6))
    stream, intact = _stream(pieces)
    got = list(codec.module.scan(stream))
    spans = {(f.offset, f.length) for f in got}
    stray = [f for f in got if (f.offset, f.length) not in {(o, len(b)) for o, b in intact}]
    for offset, frame in intact:
        if (offset, len(frame)) in spans:
            continue
        # Garbage can itself form a valid frame (B5 62 and six zero bytes is
        # one) and swallow an intact frame that starts inside it. Allow that,
        # and only that.
        assert any(f.offset < offset < f.offset + f.length for f in stray), (offset, got)
    for f in got:
        assert codec.module.encode(f) == stream[f.offset:f.offset + f.length]


@params
@pytest.mark.parametrize("seed", range(5))
def test_scan_recovers_exactly_the_intact_frames(name, seed):
    # Random garbage, not shrunk towards zeros: a false frame in it would need
    # a checksum to match by chance, so the recovered list must be exact.
    # Garbage that ends a frame ("*", CR LF) is left out here: it can complete
    # a truncated sentence into a genuinely valid one.
    codec = CODECS[name]
    starts = [p for p in codec.preambles if p[0] == codec.preambles[0][0]]
    rng = random.Random(seed)
    pieces = []
    for _ in range(200):
        garbage = b"".join(rng.choice([rng.randbytes(rng.randint(0, 40)), rng.choice(starts)])
                           for _ in range(rng.randint(0, 3)))
        pieces.append((codec.random_frame(rng),
                       rng.choice(["intact", "intact", "intact", "truncated", "spliced"]),
                       garbage, rng.randrange(1 << 16)))
    stream, intact = _stream(pieces)
    got = [(f.offset, codec.module.encode(f)) for f in codec.module.scan(stream)]
    assert got == intact
    assert len(intact) > 100


@params
def test_scan_starts_at_offset(name):
    codec = CODECS[name]
    rng = random.Random(7)
    a, b = codec.random_frame(rng), codec.random_frame(rng)
    stream = a + b
    assert [f.offset for f in codec.module.scan(stream)] == [0, len(a)]
    assert [f.offset for f in codec.module.scan(stream, 1)] == [len(a)]
    assert list(codec.module.scan(stream, len(stream))) == []


@params
def test_offset_outside_buffer(name):
    module = CODECS[name].module
    assert module.parse(b"", 0) == module.NeedMore(0)
    for bad in (-1, 1):
        with pytest.raises(module.Error):
            module.parse(b"", bad)
        with pytest.raises(module.Error):
            list(module.scan(b"", bad))


def _buffers(data: bytes) -> list:
    # Every bytes-like form a caller may hold: a slice of a larger memoryview,
    # an array of another item size, a read-only view.
    import array
    padded = memoryview(b"\x00" + data + b"\x00")[1:-1]
    return [bytearray(data), memoryview(data), padded, memoryview(bytearray(data)).toreadonly(),
            array.array("B", data)]


@params
def test_any_bytes_like_input(name):
    codec = CODECS[name]
    rng = random.Random(11)
    frames = [codec.random_frame(rng) for _ in range(5)]
    stream = b"\x00garbage" + b"".join(frames)
    want = [(f.offset, f.length) for f in codec.module.scan(stream)]
    assert len(want) == 5
    for buf in _buffers(stream):
        assert [(f.offset, f.length) for f in codec.module.scan(buf)] == want, type(buf)
        first = codec.module.parse(buf, 8)
        assert isinstance(first, codec.module.Frame) and codec.module.encode(first) == frames[0]
        assert isinstance(first.offset, int)
    for buf in _buffers(frames[0]):
        assert codec.module.encode(codec.module.parse(buf)) == frames[0]


@params
def test_frame_fields_are_bytes_whatever_the_input(name):
    # A frame parsed from a view must not hold the view (which would pin the
    # caller's buffer and compare unlike bytes).
    codec = CODECS[name]
    frame = codec.module.parse(memoryview(bytearray(codec.random_frame(random.Random(3)))))
    for value in vars(frame).values() if hasattr(frame, "__dict__") else (
            getattr(frame, s) for s in type(frame).__slots__):
        assert not isinstance(value, (memoryview, bytearray)), value


# --- false starts -------------------------------------------------------------------------
#
# A byte that looks like the start of a frame, with a length field claiming
# the most a frame may hold, must cost scan about as much as any other byte:
# otherwise a stream of such bytes (crafted, or a long run of noise) takes
# time quadratic in its length. Each input below repeats a header that
# passes every check made before the checksum, so a framer that computed
# the checksum over the claimed length afresh at every false start would
# spend about 1000 to 65000 byte operations per start.

def _crafted_spartn() -> bytes:
    # TF001 to TF006 of a frame with TF003 = 1023 and a valid CRC-4, repeated:
    # every fourth byte starts a header that passes TF006.
    d = spartn.Description(0, 1, 0, 0, 0, None, None, None, None)
    head = spartn.encode_frame(0, 0, 3, d, bytes(1023))[:4]
    return head


CRAFTED = {
    "rtcm3": b"\xd3",                          # length 0x3D3 = 979 bytes, every byte
    "ubx": b"\xb5\x62\x00\x00\xff\xff",        # 65535-byte payload, every sixth byte
    # PL = 0xFFF7 puts the end sequence and the checksum byte (0xF7) on this
    # pattern again; the payload's XOR is 0xF9, so every start fails only there.
    "skytraq": b"\xa0\xa1\xff\xf7\x0d\x0a\x00\x00",
    "spartn": _crafted_spartn(),
    "nmea": b"$" + b"A" * (nmea.MAX_LENGTH - 6),   # no '*': the longest search per '$'
}


def _cost(module, data: bytes, rounds: int = 3) -> float:
    """CPU seconds per byte of ``scan`` over ``data``, best of ``rounds``."""
    import time
    best = float("inf")
    for _ in range(rounds):
        start = time.process_time()
        for _ in module.scan(data):
            pass
        best = min(best, time.process_time() - start)
    return best / len(data)


@params
def test_false_starts_cost_about_what_ordinary_bytes_cost(name):
    codec = CODECS[name]
    rng = random.Random(5)
    ordinary = bytearray()
    while len(ordinary) < 400_000:
        ordinary += rng.randbytes(rng.randint(0, 40)) + codec.random_frame(rng)
    crafted = CRAFTED[name] * (200_000 // len(CRAFTED[name]))
    first = codec.module.parse(crafted, 0)
    assert isinstance(first, codec.module.Invalid) and first.reason != "no 0x0D 0x0A end sequence"
    assert not list(codec.module.scan(crafted))
    ratio = _cost(codec.module, crafted) / _cost(codec.module, bytes(ordinary))
    # A false start at every byte (rtcm3) is a Python-level parse per byte,
    # against whole frames skipped at a time in ordinary input; it measured
    # about 25 times the cost per byte, the others under 5. Recomputing the
    # checksum over the claimed length at each false start, as scan did in
    # 0.1.0, measured 300 to 1000 times.
    assert ratio < 100, ratio
