"""Declarative UBX payload tables: a frozen dataclass whose annotations are the table.

Source: u-blox F9 HPG 1.51 Interface Description (UBXDOC-963802114-13124
R01), section 3.3 "UBX payload definition rules", which the u-blox X20 HPG 2.11
Interface Description (UBXDOC-304424225-21617 R01) prints unchanged under
the same number. Each field of a message dataclass
is one row of the message's "Payload description" table, in byte-offset
order, with the row's type in ``typing.Annotated`` metadata::

    @dataclass(frozen=True, slots=True)
    class Example:
        version: Annotated[int, U1("version")]
        reserved0: Annotated[tuple[int, ...], U1("reserved0", count=3)]
        num_words: Annotated[int, U1("numWords")]
        dwrd: Annotated[tuple[int, ...], U4("dwrd", count="num_words")]
        data: Annotated[bytes, Bytes("userData", length="num_words")]

The string argument is the spec's field name, kept for documentation and for
cross-checks. Types are those of section 3.3.5: ``U1 I1 X1 U2 I2 X2 U4 I4
X4``, little-endian, two's complement for ``I``. A bitfield (``X``) is kept
whole, as the unsigned integer on the wire: its named bits are the caller's to
pick out (section 3.3.2: undescribed bits are reserved, and keeping them is
what makes a round trip exact).

``R4`` and ``R8`` (IEEE 754 single and double precision, section 3.3.5) are
kept as the unsigned integer of their 32 or 64 bits, not as a float: that is
the integer on the wire, and it keeps every bit pattern (negative zero, NaN
payloads) through a round trip. ``struct.unpack("<d", value.to_bytes(8,
"little"))[0]`` gives the number. ``CH`` is not provided because no message
here uses it.

Repetition (section 3.3.7):

``count=n``
    a field repeated a constant number of times (``U1[3]``); the value is a
    tuple.
``count="field"``
    a variable-by-field group of one field; the count is the value of an
    earlier field (section 3.3.8 places that field at a fixed offset before
    the group).
``Bytes(name, length=...)``
    a repeated ``U1`` that is opaque data (RXM-PMP's userData), kept as
    ``bytes``.
``Group(name, cls, count=...)``
    a repeated group of several fields ("Start of repeated group (numMeas
    times)"); each repetition is a ``cls``, itself a fixed-size table of this
    kind, and the value is a tuple of them. The spec prints no name for a
    group; ``name`` is the name of its first field.

Optional and variable-by-size groups are not provided because no message
here has them.

Values are not checked against the spec's ranges, only against their type.
"""

from __future__ import annotations

import dataclasses
import struct
import typing
from typing import Any, TypeVar

from ._frame import Error

T = TypeVar("T")


class FieldError(Error):
    """A payload does not fit its table, or a message does not fit its types."""


class Kind:
    """One row's type. ``name`` is the spec's field name; ``count`` the repetition."""

    __slots__ = ("name", "count")
    code: str   # struct format character
    size: int   # bytes, section 3.3.5

    def __init__(self, name: str, *, count: int | str | None = None) -> None:
        if isinstance(count, int) and (isinstance(count, bool) or count < 0):
            raise TypeError(f"{name}: count must be a non-negative int or a field name")
        self.name = name
        self.count = count

    @property
    def lo(self) -> int:
        return -(1 << (8 * self.size - 1)) if self.code.islower() else 0

    @property
    def hi(self) -> int:
        bits = 8 * self.size - (1 if self.code.islower() else 0)
        return (1 << bits) - 1

    def __repr__(self) -> str:
        extra = "" if self.count is None else f", count={self.count!r}"
        return f"{type(self).__name__}({self.name!r}{extra})"


def _kind(type_name: str, code: str, size: int, doc: str) -> type[Kind]:
    return type(type_name, (Kind,), {"__slots__": (), "code": code, "size": size, "__doc__": doc})


U1 = _kind("U1", "B", 1, "unsigned 8-bit integer")
I1 = _kind("I1", "b", 1, "signed 8-bit integer, two's complement")
X1 = _kind("X1", "B", 1, "8-bit bitfield, kept as an unsigned integer")
U2 = _kind("U2", "H", 2, "unsigned little-endian 16-bit integer")
I2 = _kind("I2", "h", 2, "signed little-endian 16-bit integer, two's complement")
X2 = _kind("X2", "H", 2, "16-bit little-endian bitfield, kept as an unsigned integer")
U4 = _kind("U4", "I", 4, "unsigned little-endian 32-bit integer")
I4 = _kind("I4", "i", 4, "signed little-endian 32-bit integer, two's complement")
X4 = _kind("X4", "I", 4, "32-bit little-endian bitfield, kept as an unsigned integer")
R4 = _kind("R4", "I", 4, "IEEE 754 single precision, kept as the unsigned integer of its bits")
R8 = _kind("R8", "Q", 8, "IEEE 754 double precision, kept as the unsigned integer of its bits")


class Bytes:
    """Repeated ``U1`` kept as ``bytes``; ``length`` is a constant or an earlier field."""

    __slots__ = ("name", "length")

    def __init__(self, name: str, *, length: int | str) -> None:
        self.name = name
        self.length = length

    def __repr__(self) -> str:
        return f"Bytes({self.name!r}, length={self.length!r})"


class Group:
    """A repeated group of several fields; each repetition is a ``cls``."""

    __slots__ = ("name", "cls", "count")

    def __init__(self, name: str, cls: type, *, count: int | str) -> None:
        if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
            raise TypeError(f"{name}: Group needs a dataclass, not {cls!r}")
        if isinstance(count, int) and (isinstance(count, bool) or count < 0):
            raise TypeError(f"{name}: count must be a non-negative int or a field name")
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
    kind: Kind | Bytes | Group


class Layout:
    """The compiled table of one message dataclass. Get it with :func:`layout`."""

    __slots__ = ("cls", "rows", "offsets", "fixed_size")

    def __init__(self, cls: type, rows: tuple[Row, ...]) -> None:
        self.cls = cls
        self.rows = rows
        # Byte offset of every row up to the first variable-length one.
        self.offsets: dict[str, int] = {}
        at: int | None = 0
        for row in rows:
            if at is None:
                break
            self.offsets[row.field] = at
            at = _const_size(row.kind)
            at = None if at is None else self.offsets[row.field] + at
        self.fixed_size = at   # the payload length of a fixed-size message, else None

    def __repr__(self) -> str:
        return f"<Layout {self.cls.__qualname__}: {len(self.rows)} rows>"

    def unpack(self, payload: bytes) -> Any:
        values: dict[str, Any] = {}
        at = 0
        for row in self.rows:
            kind = row.kind
            where = f"{self.cls.__qualname__}.{row.field}"
            if isinstance(kind, Bytes):
                n = _resolve(kind.length, values)
                if at + n > len(payload):
                    raise FieldError(f"{where}: needs {n} bytes at offset {at}, "
                                     f"payload has {len(payload)}")
                values[row.field] = bytes(payload[at:at + n])
                at += n
                continue
            if isinstance(kind, Group):
                n, size = _resolve(kind.count, values), kind.size
                if at + n * size > len(payload):
                    raise FieldError(f"{where}: needs {n} groups of {size} bytes at offset "
                                     f"{at}, payload has {len(payload)}")
                sub = layout(kind.cls)
                values[row.field] = tuple(sub.unpack(payload[at + i * size:at + (i + 1) * size])
                                          for i in range(n))
                at += n * size
                continue
            n = 1 if kind.count is None else _resolve(kind.count, values)
            end = at + n * kind.size
            if end > len(payload):
                raise FieldError(f"{where}: needs {end} bytes, payload has {len(payload)}")
            items = struct.unpack_from(f"<{n}{kind.code}", payload, at)
            values[row.field] = items[0] if kind.count is None else items
            at = end
        if at != len(payload):
            raise FieldError(f"{self.cls.__qualname__}: {len(payload) - at} bytes left over")
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
            if isinstance(kind, Bytes):
                n = _resolve(kind.length, values)
                if not isinstance(value, bytes) or len(value) != n:
                    raise FieldError(f"{where}: needs {n} bytes, got {value!r}")
                out += value
            elif isinstance(kind, Group):
                n = _resolve(kind.count, values)
                if not isinstance(value, tuple) or len(value) != n:
                    raise FieldError(f"{where}: needs a tuple of {n} groups, got {value!r}")
                for i, item in enumerate(value):
                    if type(item) is not kind.cls:
                        raise FieldError(f"{where}[{i}]: needs a {kind.cls.__qualname__}, "
                                         f"got {item!r}")
                    out += layout(kind.cls).pack(item)
            elif kind.count is None:
                _check(where, kind, value)
                out += struct.pack(f"<{kind.code}", value)
            else:
                n = _resolve(kind.count, values)
                if not isinstance(value, tuple) or len(value) != n:
                    raise FieldError(f"{where}: needs a tuple of {n} items, got {value!r}")
                for i, item in enumerate(value):
                    _check(f"{where}[{i}]", kind, item)
                out += struct.pack(f"<{n}{kind.code}", *value)
            values[row.field] = value
        return bytes(out)


def _const_size(kind: Kind | Bytes | Group) -> int | None:
    if isinstance(kind, Bytes):
        return kind.length if isinstance(kind.length, int) else None
    if isinstance(kind, Group):
        return kind.count * kind.size if isinstance(kind.count, int) else None
    if kind.count is None:
        return kind.size
    return kind.count * kind.size if isinstance(kind.count, int) else None


def _resolve(n: int | str, values: dict[str, Any]) -> int:
    return n if isinstance(n, int) else values[n]


def _check(where: str, kind: Kind, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FieldError(f"{where}: needs an int, got {value!r}")
    if not kind.lo <= value <= kind.hi:
        raise FieldError(f"{where}: {value} does not fit {type(kind).__name__}")


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
                if isinstance(m, (Kind, Bytes, Group))]
        if len(meta) != 1:
            raise TypeError(f"{cls.__qualname__}.{f.name}: needs exactly one UBX type "
                            f"in Annotated[...], found {len(meta)}")
        kind = meta[0]
        if isinstance(kind, Group) and layout(kind.cls).fixed_size is None:
            raise TypeError(f"{cls.__qualname__}.{f.name}: group {kind.cls.__qualname__} "
                            f"is not of fixed size")
        ref = kind.length if isinstance(kind, Bytes) else kind.count
        if isinstance(ref, str):
            earlier = {r.field: r.kind for r in rows}
            if not (ref in earlier and isinstance(earlier[ref], Kind)
                    and earlier[ref].count is None):
                raise TypeError(f"{cls.__qualname__}.{f.name}: counted by {ref}, "
                                f"which is not a single integer field before it")
        rows.append(Row(f.name, kind))
    compiled = Layout(cls, tuple(rows))
    _LAYOUTS[cls] = compiled
    return compiled


def unpack(cls: type[T], payload: bytes) -> T:
    """The ``cls`` that fills ``payload`` exactly."""
    return layout(cls).unpack(payload)  # type: ignore[no-any-return]


def pack(message: Any) -> bytes:
    """``message`` as its payload bytes."""
    return layout(type(message)).pack(message)
