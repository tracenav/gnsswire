"""What every system module shares: the errors, and field tables over a run of bits.

A navigation message unit (a GPS subframe's data bits, a Galileo word, a
GLONASS string) is held as a Python ``int`` of a known number of bits, the
first bit received the most significant. :func:`read_bits` reads a field
table (``gnsswire.bits``) from such an int and checks that the table spans
it exactly; :func:`write_bits` gives the int back.
"""

from __future__ import annotations

import dataclasses
from typing import Any, TypeVar

from gnsswire.bits import BitError, BitReader, BitWriter, layout, read, write

T = TypeVar("T")


class Error(ValueError):
    """Base of every exception this distribution raises for data it cannot take."""


class ParityError(Error):
    """A unit fails the integrity check its ICD defines (parity, BCH, Hamming code or CRC)."""


class FieldError(Error, BitError):
    """A value does not fit its table: wrong width, wrong type, or bits left over."""


class Unsupported(Error, LookupError):
    """A system, signal or carrier presentation that no staged document describes."""


_WIDTHS: dict[type, int] = {}


def _no_field(name: str) -> Any:
    raise KeyError(name)


def width(cls: type) -> int:
    """The number of bits ``cls``'s table spans (every table here is of fixed width).

    ``layout(cls).fixed_bits`` does not count rows with a ``count``, even a
    constant one; the tables here use only constant counts and widths.
    """
    if cls in _WIDTHS:
        return _WIDTHS[cls]
    total = 0
    for row in layout(cls).rows:
        kind = row.kind
        try:
            n = 1 if kind.count is None else kind.count.eval(_no_field)
            if kind.when is not None or row.group is not None:
                raise KeyError(row.name)
            total += n * kind.width.eval(_no_field)
        except (KeyError, AttributeError):
            raise TypeError(f"{cls.__qualname__} is not a fixed-width table") from None
    _WIDTHS[cls] = total
    return total


def read_bits(cls: type[T], value: int, nbits: int) -> T:
    """Read ``cls`` from the ``nbits`` bits of ``value`` (the first bit the most significant)."""
    if width(cls) != nbits:
        raise FieldError(f"{cls.__qualname__} spans {width(cls)} bits, not {nbits}")
    if not 0 <= value < 1 << nbits:
        raise FieldError(f"{value!r} is not a {nbits}-bit unit")
    pad = -nbits % 8
    try:
        return read(cls, BitReader((value << pad).to_bytes((nbits + pad) // 8, "big")))
    except BitError as exc:   # pragma: no cover - a fixed-width table always fits
        raise FieldError(str(exc)) from None


def write_bits(message: Any) -> int:
    """``message`` as the int of its table's bits."""
    w = BitWriter()
    try:
        write(message, w)
    except BitError as exc:
        raise FieldError(str(exc)) from None
    except TypeError as exc:
        raise FieldError(str(exc)) from None
    n = w.pos
    data = w.to_bytes()
    return int.from_bytes(data, "big") >> (len(data) * 8 - n)


def bits_of(value: int, start: int, count: int, total: int) -> int:
    """``count`` bits of a ``total``-bit int from bit ``start`` (1 = the first, most significant)."""
    return (value >> (total - start - count + 1)) & ((1 << count) - 1)


def replace(message: T, **changes: Any) -> T:
    return dataclasses.replace(message, **changes)  # type: ignore[type-var]
