"""Declarative SkyTraq message tables: a frozen dataclass whose annotations are the table.

Source: SkyTraq AN0039 version 1.4.42, sections "Data Byte Ordering" and
"Data Type Definition". Each field of a message dataclass is one row of the
message's field table, in order, from the byte after the message ID, with
the row's type in ``typing.Annotated`` metadata::

    @dataclass(frozen=True, slots=True)
    class Example:
        iod: Annotated[int, UINT8("IOD")]
        nmeas: Annotated[int, UINT8("NMEAS")]
        words: Annotated[tuple[int, ...], BYTES3("WORD", count=10)]
        meas: Annotated[tuple[Channel, ...], Group("Channel", Channel, count="nmeas")]

The string argument is the note's field name, kept for documentation.
Every multi-byte value is big-endian ("All payloads in binary protocol are
transferred in big-endian format"). Types, each kept as an integer:

``UINT8 UINT16 UINT32``, ``SINT8 SINT16 SINT32``
    unsigned and signed (two's complement) integers of 1, 2 and 4 bytes.
    The note does not say how signed values are coded; two's complement is
    assumed, and only CN0 of 0xDE (not implemented) is signed.
``SPFP DPFP``
    IEEE 754 single and double precision ("32 bit single precision floating
    point number"), kept as the unsigned integer of their bits, so that every
    bit pattern round-trips; ``struct.unpack(">d", value.to_bytes(8,
    "big"))[0]`` gives the number.
``BYTES3 BYTES4``
    the note's "3-bytes" and "4-bytes" navigation words, kept as unsigned
    integers.
``UNTYPED(name, size)``
    a field the note prints with type "-" (indicators, reserved fields):
    ``size`` bytes, kept as an unsigned integer. A bitfield is kept whole;
    its bits are the caller's to pick out.

``count=n`` repeats a row a constant number of times, ``count="field"`` as
many times as an earlier field says; the value is a tuple. ``Group(name,
cls, count=...)`` repeats a group of rows (a channel's measurement), each a
``cls``, itself a fixed-size table of this kind.

Values are not checked against the note's ranges, only against their type.
"""

from __future__ import annotations

import dataclasses
import typing
from typing import Any, TypeVar

from ._frame import Error

T = TypeVar("T")


class FieldError(Error):
    """A message body does not fit its table, or a message does not fit its types."""


class Kind:
    """One row's type: ``size`` bytes, signed or not, repeated ``count`` times."""

    __slots__ = ("name", "count")
    size: int
    signed: bool

    def __init__(self, name: str, *, count: int | str | None = None) -> None:
        if isinstance(count, int) and (isinstance(count, bool) or count < 0):
            raise TypeError(f"{name}: count must be a non-negative int or a field name")
        self.name = name
        self.count = count

    @property
    def lo(self) -> int:
        return -(1 << (8 * self.size - 1)) if self.signed else 0

    @property
    def hi(self) -> int:
        return (1 << (8 * self.size - self.signed)) - 1

    @property
    def type_name(self) -> str:
        return type(self).__name__

    def __repr__(self) -> str:
        extra = "" if self.count is None else f", count={self.count!r}"
        return f"{self.type_name}({self.name!r}{extra})"


def _kind(type_name: str, size: int, signed: bool, doc: str) -> type[Kind]:
    return type(type_name, (Kind,), {"__slots__": (), "size": size, "signed": signed,
                                      "__doc__": doc})


UINT8 = _kind("UINT8", 1, False, "8 bit unsigned integer")
UINT16 = _kind("UINT16", 2, False, "16 bit unsigned integer, big-endian")
UINT32 = _kind("UINT32", 4, False, "32 bit unsigned integer, big-endian")
SINT8 = _kind("SINT8", 1, True, "8 bit signed integer, two's complement")
SINT16 = _kind("SINT16", 2, True, "16 bit signed integer, two's complement, big-endian")
SINT32 = _kind("SINT32", 4, True, "32 bit signed integer, two's complement, big-endian")
SPFP = _kind("SPFP", 4, False, "single precision float, kept as the integer of its bits")
DPFP = _kind("DPFP", 8, False, "double precision float, kept as the integer of its bits")
BYTES3 = _kind("BYTES3", 3, False, "a '3-bytes' word, kept as an unsigned integer")
BYTES4 = _kind("BYTES4", 4, False, "a '4-bytes' word, kept as an unsigned integer")


class UNTYPED(Kind):
    """A field of type "-": ``size`` bytes, kept as an unsigned big-endian integer."""

    __slots__ = ("size",)
    signed = False

    def __init__(self, name: str, size: int, *, count: int | str | None = None) -> None:
        super().__init__(name, count=count)
        self.size = size

    @property
    def type_name(self) -> str:
        return f"-{self.size}"


class Group:
    """A repeated group of rows; each repetition is a ``cls``."""

    __slots__ = ("name", "cls", "count")

    def __init__(self, name: str, cls: type, *, count: int | str) -> None:
        if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
            raise TypeError(f"{name}: Group needs a dataclass, not {cls!r}")
        self.name = name
        self.cls = cls
        self.count = count

    @property
    def size(self) -> int:
        """Bytes of one repetition."""
        size = layout(self.cls).fixed_size
        assert size is not None   # layout() refuses a group that is not of fixed size
        return size

    def __repr__(self) -> str:
        return f"Group({self.name!r}, {self.cls.__qualname__}, count={self.count!r})"


@dataclasses.dataclass(frozen=True, slots=True)
class Row:
    field: str            # the dataclass field
    kind: Kind | Group


class Layout:
    """The compiled table of one message dataclass. Get it with :func:`layout`."""

    __slots__ = ("cls", "rows", "offsets", "fixed_size")

    def __init__(self, cls: type, rows: tuple[Row, ...]) -> None:
        self.cls = cls
        self.rows = rows
        # Byte offset in the body of every row up to the first variable-length one.
        self.offsets: dict[str, int] = {}
        at: int | None = 0
        for row in rows:
            if at is None:
                break
            self.offsets[row.field] = at
            size = _const_size(row.kind)
            at = None if size is None else at + size
        self.fixed_size = at   # the body length of a fixed-size message, else None

    def __repr__(self) -> str:
        return f"<Layout {self.cls.__qualname__}: {len(self.rows)} rows>"

    def unpack(self, body: bytes) -> Any:
        values: dict[str, Any] = {}
        at = 0
        for row in self.rows:
            kind = row.kind
            where = f"{self.cls.__qualname__}.{row.field}"
            n = 1 if kind.count is None else _resolve(kind.count, values)
            end = at + n * kind.size
            if end > len(body):
                raise FieldError(f"{where}: needs {end} bytes, body has {len(body)}")
            if isinstance(kind, Group):
                sub = layout(kind.cls)
                values[row.field] = tuple(
                    sub.unpack(body[at + i * kind.size:at + (i + 1) * kind.size])
                    for i in range(n))
            else:
                items = tuple(int.from_bytes(body[at + i * kind.size:at + (i + 1) * kind.size],
                                             "big", signed=kind.signed) for i in range(n))
                values[row.field] = items[0] if kind.count is None else items
            at = end
        if at != len(body):
            raise FieldError(f"{self.cls.__qualname__}: {len(body) - at} bytes left over")
        return self.cls(**values)

    def pack(self, message: Any) -> bytes:
        if type(message) is not self.cls:
            raise TypeError(f"expected {self.cls.__qualname__}, got {type(message).__qualname__}")
        out = bytearray()
        values: dict[str, Any] = {}
        for row in self.rows:
            kind = row.kind
            value = getattr(message, row.field)
            where = f"{self.cls.__qualname__}.{row.field}"
            if kind.count is None:
                items = (value,)
            else:
                n = _resolve(kind.count, values)
                if not isinstance(value, tuple) or len(value) != n:
                    raise FieldError(f"{where}: needs a tuple of {n} items, got {value!r}")
                items = value
            for i, item in enumerate(items):
                here = where if kind.count is None else f"{where}[{i}]"
                if isinstance(kind, Group):
                    if type(item) is not kind.cls:
                        raise FieldError(f"{here}: needs a {kind.cls.__qualname__}, "
                                         f"got {item!r}")
                    out += layout(kind.cls).pack(item)
                else:
                    _check(here, kind, item)
                    out += item.to_bytes(kind.size, "big", signed=kind.signed)
            values[row.field] = value
        return bytes(out)


def _const_size(kind: Kind | Group) -> int | None:
    if kind.count is None:
        return kind.size
    return kind.count * kind.size if isinstance(kind.count, int) else None


def _resolve(n: int | str, values: dict[str, Any]) -> int:
    return n if isinstance(n, int) else values[n]


def _check(where: str, kind: Kind, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FieldError(f"{where}: needs an int, got {value!r}")
    if not kind.lo <= value <= kind.hi:
        raise FieldError(f"{where}: {value} does not fit {kind.type_name}")


_LAYOUTS: dict[type, Layout] = {}


def layout(cls: type) -> Layout:
    """The compiled, checked table of a message dataclass (cached per class)."""
    if cls in _LAYOUTS:
        return _LAYOUTS[cls]
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise TypeError(f"{cls!r} is not a dataclass")
    hints = typing.get_type_hints(cls, include_extras=True)
    rows: list[Row] = []
    for f in dataclasses.fields(cls):
        meta = [m for m in getattr(hints[f.name], "__metadata__", ())
                if isinstance(m, (Kind, Group))]
        if len(meta) != 1:
            raise TypeError(f"{cls.__qualname__}.{f.name}: needs exactly one SkyTraq type "
                            f"in Annotated[...], found {len(meta)}")
        kind = meta[0]
        if isinstance(kind, Group) and layout(kind.cls).fixed_size is None:
            raise TypeError(f"{cls.__qualname__}.{f.name}: group {kind.cls.__qualname__} "
                            f"is not of fixed size")
        if isinstance(kind.count, str):
            earlier = {r.field: r.kind for r in rows}
            ref = earlier.get(kind.count)
            if not (isinstance(ref, Kind) and ref.count is None):
                raise TypeError(f"{cls.__qualname__}.{f.name}: counted by {kind.count}, "
                                f"which is not a single integer field before it")
        rows.append(Row(f.name, kind))
    compiled = Layout(cls, tuple(rows))
    _LAYOUTS[cls] = compiled
    return compiled


def unpack(cls: type[T], body: bytes) -> T:
    """The ``cls`` that fills ``body`` exactly."""
    return layout(cls).unpack(body)  # type: ignore[no-any-return]


def pack(message: Any) -> bytes:
    """``message`` as its body bytes (without the message ID)."""
    return layout(type(message)).pack(message)
