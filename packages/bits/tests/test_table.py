"""The field-table interpreter on synthetic tables shaped like RTCM MSM and SPARTN OCB/HPAC.

The shapes, not the protocols, are under test here: masks that size repeated
rows (RTCM 10403.3 MSM satellite and cell masks), mask fields whose width is
picked by an earlier field (SPARTN v2.0.3 SF011 and friends), blocks present
by flag (SPARTN SF014), and widths chosen by a size indicator (SPARTN SF044).
"""

from dataclasses import dataclass, field
from typing import Annotated, ClassVar

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gnsswire.bits import (
    NEGATIVE_ZERO,
    SM,
    BitError,
    BitReader,
    BitWriter,
    Extension,
    F,
    Group,
    Octets,
    Rest,
    S,
    Truncated,
    U,
    layout,
    pack,
    popcount,
    read,
    unpack,
    write,
)


@dataclass(frozen=True, slots=True)
class Fixed:
    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    x: Annotated[int, S(38, "DF025")]
    tau: Annotated[int, SM(22, "DF124")]
    flag: Annotated[int, U(1)]


@dataclass(frozen=True, slots=True)
class Cell:
    fine: Annotated[int, S(7)]
    lock: Annotated[int, U(2)]
    # Refers outwards: a field of the enclosing message decides this one's presence.
    ext: Annotated[int | None, SM(5, when=F.extended == 1)]


@dataclass(frozen=True, slots=True)
class MsmLike:
    number: Annotated[int, U(12)]
    extended: Annotated[int, U(1)]
    sat_mask: Annotated[int, U(4)]
    sig_mask: Annotated[int, U(3)]
    cell_mask: Annotated[int, U(popcount(F.sat_mask) * popcount(F.sig_mask))]
    rough: Annotated[tuple[int, ...], U(5, count=popcount(F.sat_mask))]
    cells: Annotated[tuple[Cell, ...], Group(Cell, count=popcount(F.cell_mask))]


@dataclass(frozen=True, slots=True)
class Orbit:
    iode: Annotated[int, U(8)]
    radial: Annotated[int, U(F.width)]   # width taken from the enclosing message


@dataclass(frozen=True, slots=True)
class Sat:
    present: Annotated[int, U(2)]   # bit 1: orbit block, bit 0: bias block
    orbit: Annotated[Orbit | None, Group(Orbit, when=F.present >> 1)]
    bias_mask: Annotated[int | None, U(3, when=F.present & 1)]
    biases: Annotated[tuple[int, ...] | None,
                      U(4, count=popcount(F.bias_mask), when=F.present & 1)]


@dataclass(frozen=True, slots=True)
class OcbLike:
    width: Annotated[int, U(3)]
    mask_len: Annotated[int, U(2)]
    mask: Annotated[int, U(F.mask_len.map({0: 2, 1: 3, 2: 5}))]
    size: Annotated[int, U(1)]
    coeff: Annotated[int, U(4 + 3 * F.size)]
    big: Annotated[int | None, U(2, when=(F.size == 1) & (F.mask_len >= 1))]
    name_len: Annotated[int, U(3)]
    name: Annotated[bytes, Octets(F.name_len)]
    sats: Annotated[tuple[Sat, ...], Group(Sat, count=popcount(F.mask))]


def bitstring(*fields: tuple[int, int]) -> bytes:
    """Concatenate (value, width) pairs MSB-first, independently of BitWriter."""
    bits = "".join(format(v & ((1 << n) - 1), f"0{n}b") for v, n in fields if n)
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


# --- worked examples ------------------------------------------------------------------

def test_fixed_message_bits_and_length():
    msg = Fixed(number=1005, station=7, x=-(1 << 37), tau=-3, flag=1)
    assert layout(Fixed).fixed_bits == 12 + 12 + 38 + 22 + 1
    data = pack(msg)
    assert data == bitstring((1005, 12), (7, 12), (-(1 << 37), 38), ((1 << 21) | 3, 22), (1, 1))
    assert unpack(Fixed, data) == msg


def test_mask_sized_rows():
    msg = MsmLike(
        number=1074, extended=1, sat_mask=0b1010, sig_mask=0b011, cell_mask=0b1101,
        rough=(31, 2),
        cells=(Cell(-64, 3, -15), Cell(63, 0, 15), Cell(0, 1, 0)),
    )
    assert layout(MsmLike).fixed_bits is None
    data = pack(msg)
    assert data == bitstring(
        (1074, 12), (1, 1), (0b1010, 4), (0b011, 3), (0b1101, 4), (31, 5), (2, 5),
        (-64, 7), (3, 2), (0b11111, 5), (63, 7), (0, 2), (0b01111, 5), (0, 7), (1, 2), (0, 5))
    assert unpack(MsmLike, data) == msg


def test_flags_lookups_and_octets():
    msg = OcbLike(
        width=6, mask_len=2, mask=0b10001, size=1, coeff=0x7F, big=3, name_len=2, name=b"ab",
        sats=(Sat(0b11, Orbit(200, 63), 0b101, (1, 15)), Sat(0b00, None, None, None)),
    )
    data = pack(msg)
    assert data == bitstring(
        (6, 3), (2, 2), (0b10001, 5), (1, 1), (0x7F, 7), (3, 2), (2, 3), (ord("a"), 8),
        (ord("b"), 8), (0b11, 2), (200, 8), (63, 6), (0b101, 3), (1, 4), (15, 4), (0, 2))
    assert unpack(OcbLike, data) == msg


def test_zero_counts():
    msg = MsmLike(1074, 0, 0, 0b111, 0, (), ())
    assert unpack(MsmLike, pack(msg)) == msg


# --- round trips ----------------------------------------------------------------------

@pytest.mark.parametrize("cls", [Fixed, MsmLike, OcbLike])
@given(data=st.binary(min_size=1, max_size=40))
def test_any_bytes_that_decode_reencode_to_the_same_bits(cls, data):
    # Decode arbitrary bytes; whenever that succeeds, writing the message back
    # reproduces exactly the bits that were consumed.
    r = BitReader(data)
    try:
        msg = read(cls, r)
    except BitError:
        return
    w = BitWriter()
    layout(cls).write(msg, w)
    assert w.pos == r.pos
    consumed = BitReader(data).uint(r.pos) if r.pos <= 64 else None
    if consumed is not None:
        assert BitReader(w.to_bytes()).uint(r.pos) == consumed
    else:
        k = r.pos
        a, b = BitReader(data), BitReader(w.to_bytes())
        while k:
            n = min(k, 64)
            assert a.uint(n) == b.uint(n)
            k -= n
    assert read(cls, BitReader(w.to_bytes())) == msg


cells = st.builds(Cell, st.integers(-64, 63), st.integers(0, 3), st.integers(-15, 15))


@st.composite
def msm_messages(draw):
    extended = draw(st.integers(0, 1))
    sat_mask, sig_mask = draw(st.integers(0, 15)), draw(st.integers(0, 7))
    ncell = sat_mask.bit_count() * sig_mask.bit_count()
    cell_mask = draw(st.integers(0, (1 << ncell) - 1))
    rough = tuple(draw(st.lists(st.integers(0, 31), min_size=sat_mask.bit_count(),
                                max_size=sat_mask.bit_count())))
    cs = tuple(c if extended else Cell(c.fine, c.lock, None)
               for c in draw(st.lists(cells, min_size=cell_mask.bit_count(),
                                      max_size=cell_mask.bit_count())))
    return MsmLike(draw(st.integers(0, 4095)), extended, sat_mask, sig_mask, cell_mask, rough, cs)


@given(msm_messages())
def test_generated_messages_round_trip(msg):
    assert unpack(MsmLike, pack(msg)) == msg


# --- errors ---------------------------------------------------------------------------

def test_decode_errors_name_the_row():
    data = bitstring((6, 3), (3, 2))   # mask_len 3 is not in the lookup
    with pytest.raises(BitError, match=r"^OcbLike\.mask: mask_len = 3 is not one of"):
        unpack(OcbLike, data)
    data = bitstring((1074, 12), (0, 1), (0b1, 4), (0b1, 3), (1, 1), (0, 5))   # cells missing
    with pytest.raises(Truncated, match=r"^MsmLike\.cells\[0\]\.fine: "):
        unpack(MsmLike, data)


def test_encode_checks_counts_presence_and_widths():
    good = MsmLike(1074, 0, 0b1, 0b1, 0b1, (0,), (Cell(0, 0, None),))
    pack(good)
    bad = {
        "rough": (0, 0),                       # count is popcount(sat_mask) = 1
        "cells": (Cell(0, 0, 5),),             # ext present although extended == 0
        "number": 4096,                        # does not fit 12 bits
        "sat_mask": True,                      # not an int
    }
    for name, value in bad.items():
        fields = {f: getattr(good, f) for f in good.__slots__}
        fields[name] = value
        with pytest.raises(BitError, match=rf"^MsmLike\.{name}"):
            pack(MsmLike(**fields))


def test_unpack_is_strict_about_what_follows():
    data = pack(Fixed(1, 2, 3, 4, 0))
    with pytest.raises(BitError, match="left over"):
        unpack(Fixed, data + b"\x00")
    with pytest.raises(BitError, match="fill bits"):
        unpack(Fixed, data[:-1] + bytes([data[-1] | 1]))
    # A byte-aligned message followed by exactly one byte.
    assert unpack(Word, b"\x12\x34") == Word(0x1234)
    with pytest.raises(BitError, match="1 bytes left over"):
        unpack(Word, b"\x12\x34\x00")


@dataclass(frozen=True, slots=True)
class Word:
    value: Annotated[int, U(16)]


def test_negative_zero_round_trips():
    data = bitstring((1, 12), (2, 12), (0, 38), (1 << 21, 22), (0, 1))
    message = unpack(Fixed, data)
    assert message.tau is NEGATIVE_ZERO and message == Fixed(1, 2, 0, 0, 0)
    assert pack(message) == data
    assert pack(Fixed(1, 2, 0, 0, 0)) != data       # a plain 0 is positive zero


@dataclass(frozen=True, slots=True)
class Open:
    """A table that later versions may extend: a Rest row keeps what follows it."""

    number: Annotated[int, U(12)]
    flag: Annotated[int, U(1)]
    extension: Annotated[Extension | None, Rest()] = None


def test_rest_keeps_what_follows_and_round_trips():
    plain = pack(Open(5, 1))
    assert plain == bytes.fromhex("0058") and unpack(Open, plain) == Open(5, 1)
    cases = {
        plain + b"\xab": Extension(11, 0xAB),                     # a byte after the fill
        plain[:-1] + b"\x5b": Extension(3, 0b011),                # fill bits set
        plain + b"\x00\x00": Extension(19, 0),                    # zero bytes are kept too
    }
    for data, extension in cases.items():
        message = unpack(Open, data)
        assert message == Open(5, 1, extension)
        assert extension.fill == extension.value >> (8 * extension.whole_bytes)
        assert pack(message) == data
        with pytest.raises(BitError, match="left over" if extension.whole_bytes else "fill bits"):
            unpack(Open, data, strict=True)
    assert unpack(Open, plain, strict=True) == Open(5, 1)
    assert layout(Open).fixed_bits == 13 and layout(Open).rest == "extension"


def test_rest_is_written_only_when_it_ends_on_a_byte():
    # The table is 13 bits, so an extension must be 3, 11, 19... bits long.
    assert pack(Open(5, 1, Extension(11, 0))) == bytes.fromhex("005800")
    assert pack(Open(5, 1, Extension(3, 5))) == bytes.fromhex("005d")
    with pytest.raises(BitError, match="byte boundary"):
        pack(Open(5, 1, Extension(4, 1)))
    with pytest.raises(BitError, match="plain fill"):
        pack(Open(5, 1, Extension(3, 0)))       # would decode as None
    with pytest.raises(BitError, match="Extension or None"):
        pack(Open(5, 1, b"\x00"))
    with pytest.raises(ValueError):
        Extension(3, 8)


def test_rest_must_close_the_outermost_table():
    @dataclass(frozen=True, slots=True)
    class Early:
        extension: Annotated[Extension | None, Rest()]
        number: Annotated[int, U(12)]

    @dataclass(frozen=True, slots=True)
    class Outer:
        inner: Annotated[Open, Group(Open)]

    for cls in (Early, Outer):
        with pytest.raises(TypeError, match="Rest must be the last row"):
            layout(cls)


# --- table definitions ------------------------------------------------------------------

def test_forward_reference_is_refused():
    @dataclass(frozen=True)
    class Bad:
        a: Annotated[int, U(F.b)]
        b: Annotated[int, U(3)]

    with pytest.raises(TypeError, match="refers to b"):
        layout(Bad)


def test_every_field_needs_one_kind():
    @dataclass(frozen=True)
    class NoKind:
        a: int

    @dataclass(frozen=True)
    class TwoKinds:
        a: Annotated[int, U(3), U(4)]

    @dataclass(frozen=True)
    class NotInit:
        a: Annotated[int, U(3)] = field(init=False, default=0)

    for cls in (NoKind, TwoKinds, NotInit):
        with pytest.raises(TypeError):
            layout(cls)


def test_expressions_have_no_truth_value():
    with pytest.raises(TypeError, match="truth value"):
        bool(F.a == 1)
    with pytest.raises(TypeError):
        _ = (F.a == 1) and (F.b == 2)


def test_layout_is_inspectable():
    rows = layout(MsmLike).rows
    assert [r.name for r in rows] == ["number", "extended", "sat_mask", "sig_mask",
                                      "cell_mask", "rough", "cells"]
    assert repr(rows[4].kind) == "U((popcount(sat_mask) * popcount(sig_mask)))"
    assert repr(rows[5].kind) == "U(5, count=popcount(sat_mask))"
    assert rows[6].group is not None and rows[6].group.cls is Cell
    assert repr(layout(Fixed).rows[0].kind) == "U(12, 'DF002')"
    assert repr(layout(OcbLike).rows[5].kind) == "U(2, when=((size == 1) & (mask_len >= 1)))"


# --- parameters ------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Inner:
    # A parameter is visible inside groups, like an enclosing field.
    value: Annotated[int, U(F.system.map({0: 3, 1: 5}))]


@dataclass(frozen=True, slots=True)
class Parameterised:
    PARAMS: ClassVar[tuple[str, ...]] = ("system",)

    size: Annotated[int, U(1)]
    mask: Annotated[int, U((F.system * 2 + F.size).map({0: 4, 1: 6, 2: 2, 3: 8}))]
    items: Annotated[tuple[Inner, ...], Group(Inner, count=popcount(F.mask))]


@dataclass(frozen=True, slots=True)
class Guarded:
    # SPARTN SF013: with the flag set the flags field is absent, and so is the block.
    dnu: Annotated[int, U(1)]
    flags: Annotated[int | None, U(3, when=F.dnu == 0)]
    block: Annotated[int | None, U(5, when=(F.dnu == 0) & (F.flags & 4 != 0))]


def test_and_does_not_evaluate_past_a_zero():
    for message, size in [(Guarded(1, None, None), 1), (Guarded(0, 3, None), 4),
                          (Guarded(0, 4, 17), 9)]:
        raw = pack(message)
        assert unpack(Guarded, raw) == message
        assert len(raw) == (size + 7) // 8
    with pytest.raises(BitError, match="not an integer"):
        # Without the guard, the absent field is still an error.
        (F.flags & 4).eval(lambda name: None)


def test_parameters_pick_widths():
    a = Parameterised(1, 0b100001, (Inner(5), Inner(1)))
    assert layout(Parameterised).params == ("system",)
    assert len(pack(a, system=0)) == 2              # 1 + 6 + 2·3 bits
    assert unpack(Parameterised, pack(a, system=0), system=0) == a
    b = Parameterised(1, 0b10000001, (Inner(31), Inner(0)))
    assert unpack(Parameterised, pack(b, system=1), system=1) == b
    w = BitWriter()
    write(b, w, system=1)
    assert read(Parameterised, BitReader(w.to_bytes()), system=1) == b
    with pytest.raises(BitError):
        pack(b, system=0)          # the 8-bit mask does not fit 6 bits
    with pytest.raises(BitError, match="system"):
        pack(a, system=2)          # not in the table


def test_parameters_are_required_and_checked():
    a = Parameterised(0, 0b0001, (Inner(1),))
    for bad in ({}, {"system": 0, "other": 1}, {"sys": 0}):
        with pytest.raises(TypeError, match="parameters"):
            pack(a, **bad)
        with pytest.raises(TypeError, match="parameters"):
            unpack(Parameterised, b"\0\0", **bad)
    with pytest.raises(TypeError, match="int"):
        pack(a, system="0")
    with pytest.raises(TypeError, match="parameters"):
        pack(Fixed(1, 2, 3, 4, 1), system=0)    # a table without PARAMS takes none


def test_parameters_must_be_names_and_not_fields():
    @dataclass(frozen=True)
    class Clash:
        PARAMS: ClassVar[tuple[str, ...]] = ("a",)
        a: Annotated[int, U(3)]

    @dataclass(frozen=True)
    class NotNames:
        PARAMS: ClassVar[object] = "a"
        b: Annotated[int, U(F.a)]

    @dataclass(frozen=True)
    class Undeclared:
        b: Annotated[int, U(F.a)]

    for cls in (Clash, NotNames, Undeclared):
        with pytest.raises(TypeError):
            layout(cls)
