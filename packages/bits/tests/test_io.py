"""BitReader and BitWriter against a string-of-bits model of the wire."""

import copy
import pickle

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gnsswire.bits import NEGATIVE_ZERO, BitError, BitReader, BitWriter, Truncated

LOW = {"uint": 0, "sint": 1, "smag": 2}


def bounds(kind: str, n: int) -> tuple[int, int]:
    """Inclusive value range of a field."""
    if kind == "uint":
        return 0, (1 << n) - 1
    half = 1 << (n - 1)
    return (-half, half - 1) if kind == "sint" else (-(half - 1), half - 1)


def model(kind: str, value: int, n: int) -> str:
    """The field's bits as a '0'/'1' string, built from the definitions, not from _io.

    sint: RTCM 10403.3 Table 3.3-1, n-bit two's complement.
    smag: Table 3.3-1 Note 1, sign bit then n-1 magnitude bits.
    """
    if n == 0:
        return ""
    if kind == "uint":
        return format(value, f"0{n}b")
    if kind == "sint":
        return format(value + (1 << n) if value < 0 else value, f"0{n}b")
    return ("1" if value < 0 else "0") + format(abs(value), f"0{n - 1}b")


def to_bytes(bits: str) -> bytes:
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big") if bits else b""


def edge_values(kind: str, n: int) -> list[int]:
    lo, hi = bounds(kind, n)
    alternating = int(("10" * 32)[:n] or "0", 2)
    candidates = {lo, hi, 0, lo + 1, hi - 1, alternating, (hi + lo) // 2}
    return sorted(v for v in candidates if lo <= v <= hi)


# --- every width at every alignment -------------------------------------------

@pytest.mark.parametrize("kind", ["uint", "sint", "smag"])
@pytest.mark.parametrize("align", range(8))
def test_every_width_at_every_alignment(kind, align):
    # Ones before and after the field catch bits leaking across its edges.
    for n in range(LOW[kind], 65):
        for value in edge_values(kind, n):
            w = BitWriter()
            w.uint((1 << align) - 1, align)
            getattr(w, kind)(value, n)
            w.uint(0b111, 3)
            expected = "1" * align + model(kind, value, n) + "111"
            assert w.pos == len(expected)
            data = w.to_bytes()
            assert data == to_bytes(expected), (kind, n, align, value)

            r = BitReader(data)
            assert r.uint(align) == (1 << align) - 1
            assert getattr(r, kind)(n) == value
            assert r.pos == align + n
            assert r.uint(3) == 0b111


fields = st.sampled_from(["uint", "sint", "smag"]).flatmap(
    lambda kind: st.integers(LOW[kind], 64).flatmap(
        lambda n: st.tuples(st.just(kind), st.just(n),
                            st.integers(*bounds(kind, n)) if n else st.just(0))))


@given(st.lists(fields, max_size=40))
def test_field_sequences_round_trip(seq):
    w = BitWriter()
    bits = ""
    for kind, n, value in seq:
        getattr(w, kind)(value, n)
        bits += model(kind, value, n)
    assert w.pos == len(bits)
    data = w.to_bytes()
    assert data == to_bytes(bits)

    r = BitReader(data)
    assert [getattr(r, kind)(n) for kind, n, _ in seq] == [v for _, _, v in seq]
    assert r.remaining == -len(bits) % 8


@given(st.integers(0, 7), st.binary(max_size=40), st.integers(0, 7))
def test_octets_at_any_alignment(align, payload, tail):
    w = BitWriter()
    w.uint(0, align)
    w.octets(payload)
    w.uint((1 << tail) - 1, tail)
    data = w.to_bytes()
    assert data == to_bytes("0" * align + "".join(format(b, "08b") for b in payload) + "1" * tail)
    r = BitReader(data)
    r.skip(align)
    assert r.octets(len(payload)) == payload
    assert r.uint(tail) == (1 << tail) - 1


# --- spec examples --------------------------------------------------------------

def test_sign_magnitude_examples_from_rtcm_table_3_3_1_note_1():
    # "for 8-bit words, the representations of the numbers -5 and +5 in a binary
    # form are 10000101 and 00000101, respectively."
    for value, byte in [(-5, 0b10000101), (5, 0b00000101)]:
        w = BitWriter()
        w.smag(value, 8)
        assert w.to_bytes() == bytes([byte])
        assert BitReader(bytes([byte])).smag(8) == value


def test_negative_zero_is_read_and_written_back():
    # Table 3.3-1 Note 1 says "Negative zero is not used", but the GLONASS
    # fields of 1020 follow the GLONASS ICD, which does not exclude it: it
    # decodes, equal to 0, and is written back with its sign bit.
    for n in (2, 5, 27, 64):
        raw = (1 << (n - 1)).to_bytes(8, "big")
        r = BitReader(raw, 64 - n)
        value = r.smag(n)
        assert value is NEGATIVE_ZERO and value == 0 and isinstance(value, int)
        assert r.remaining == 0
        w = BitWriter()
        w.uint(0, 64 - n)
        w.smag(value, n)
        assert w.to_bytes() == raw
    assert -NEGATIVE_ZERO == 0 and NEGATIVE_ZERO + 1 == 1 and repr(NEGATIVE_ZERO) == "NEGATIVE_ZERO"
    assert copy.deepcopy(NEGATIVE_ZERO) is NEGATIVE_ZERO
    assert pickle.loads(pickle.dumps(NEGATIVE_ZERO)) is NEGATIVE_ZERO


def test_tail_reads_and_writes_any_width():
    data = bytes(range(1, 30))
    for start in (0, 3, 8, 77, 200, 232):
        r = BitReader(data, start)
        n, value = r.tail()
        assert n == len(data) * 8 - start and r.remaining == 0
        assert value == int.from_bytes(data, "big") & ((1 << n) - 1)
        w = BitWriter()
        w.tail(int.from_bytes(data, "big") >> n, start)
        w.tail(value, n)
        assert w.to_bytes() == data
    assert BitReader(b"\x01", 3, 5).tail() == (2, 0)
    with pytest.raises(BitError):
        BitWriter().tail(4, 2)


def test_zero_writes_as_positive_zero():
    w = BitWriter()
    w.smag(0, 8)
    assert w.to_bytes() == b"\x00"


def test_two_complement_examples():
    assert BitReader(b"\xff").sint(8) == -1
    assert BitReader(b"\x80").sint(8) == -128
    assert BitReader(b"\x7f").sint(8) == 127
    # int38 "not available" value of Table 3.3-1, -2^37, left-aligned in 5 bytes.
    data = (1 << 37 << 2).to_bytes(5, "big")
    assert BitReader(data).sint(38) == -(1 << 37)


# --- limits -----------------------------------------------------------------------

def test_truncated_read_raises_and_does_not_move():
    r = BitReader(b"\xab\xcd")
    r.uint(3)
    for read in (lambda: r.uint(14), lambda: r.sint(14), lambda: r.smag(14),
                 lambda: r.octets(2), lambda: r.skip(14)):
        with pytest.raises(Truncated):
            read()
        assert r.pos == 3
    assert r.uint(13) == 0xABCD & 0x1FFF
    assert r.remaining == 0
    assert r.uint(0) == 0


def test_reader_window():
    r = BitReader(b"\x0f\xf0", start=4, end=12)
    assert r.pos == 4 and r.remaining == 8
    assert r.uint(8) == 0xFF
    with pytest.raises(Truncated):
        r.uint(1)
    with pytest.raises(ValueError):
        BitReader(b"\x00", start=2, end=9)


@pytest.mark.parametrize("kind,value,n", [
    ("uint", -1, 8), ("uint", 256, 8), ("uint", 1, 0),
    ("sint", 128, 8), ("sint", -129, 8),
    ("smag", 128, 8), ("smag", -128, 8),
])
def test_values_that_do_not_fit_are_refused(kind, value, n):
    w = BitWriter()
    with pytest.raises(BitError):
        getattr(w, kind)(value, n)
    assert w.pos == 0


@pytest.mark.parametrize("kind,n", [("uint", 65), ("uint", -1), ("sint", 0), ("sint", 65),
                                    ("smag", 1), ("smag", 65)])
def test_widths_outside_the_range_are_refused(kind, n):
    with pytest.raises(BitError):
        getattr(BitReader(bytes(16)), kind)(n)
    with pytest.raises(BitError):
        getattr(BitWriter(), kind)(0, n)


def test_align():
    w = BitWriter()
    assert w.align() == 0
    w.uint(1, 3)
    assert w.align() == 5
    assert w.pos == 8
    w.uint(1, 1)
    assert w.to_bytes() == b"\x20\x80"

    r = BitReader(b"\x21\x80")
    assert r.align() == 0
    r.uint(3)
    assert r.align() == 1   # the padding bits are returned so callers can check them
    assert r.pos == 8
