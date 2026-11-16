"""MSB-first bit reader and writer.

Bit order: the first bit on the wire is the most significant bit of the first
byte, and a field's most significant bit is sent first. RTCM 10403.3 section
3.5: "Multi-byte values are expressed with the most significant byte
transmitted first ... there is no reversal of bits within a byte". SPARTN
v2.0.3 is read the same way: Table 7.1 gives the preamble as binary 01110011
and hexadecimal 0x73, and section 6.4 numbers mask bits from the "leftmost"
(first sent) bit. The spec has no explicit bit-order statement beyond these.

Field representations:

- unsigned: RTCM 10403.3 Table 3.3-1 ``uint(n)`` and ``bit(n)``; every SPARTN
  field (SPARTN v2.0.3 section 6.3: values are sent as unsigned integers with
  a range offset).
- two's complement: RTCM 10403.3 Table 3.3-1 ``int(n)``.
- sign-magnitude: RTCM 10403.3 Table 3.3-1 ``intS(n)``, Note 1: the MSB is the
  sign (1 negative), the rest the magnitude, and "negative zero is not used".
  But the fields RTCM 1020 sends this way are defined by the GLONASS ICD
  (Table 3.5-22: "See GLONASS ICD"; ICD edition 5.1, section 4.4: "the MSB
  is the sign bit"), which does not exclude a negative zero, so a receiver
  that copies a navigation string's bits into the message may send one. A
  decoder must accept what an encoder may send: a negative zero decodes to
  :data:`NEGATIVE_ZERO`, an ``int`` equal to 0 that :class:`BitWriter`
  writes back with the sign bit set, so ``encode(decode(frame)) == frame``
  holds for it too. A plain ``0`` is written as positive zero.
- octets: RTCM ``char8(n)`` and ``utf8(n)``; kept as ``bytes``, never decoded
  to text.

Reads are atomic: a read that fails leaves the position unchanged.
"""

MAX_WIDTH = 64


class _NegativeZero(int):
    """The sign-magnitude value whose sign bit is set and whose magnitude is zero.

    Equal to 0 and an ``int`` in every arithmetic use; only
    :meth:`BitWriter.smag` tells it apart (``value is NEGATIVE_ZERO``).
    """

    __slots__ = ()

    def __new__(cls) -> "_NegativeZero":
        return super().__new__(cls, 0)

    def __repr__(self) -> str:
        return "NEGATIVE_ZERO"

    def __reduce__(self) -> str:
        return "NEGATIVE_ZERO"

    def __copy__(self) -> "_NegativeZero":
        return self

    def __deepcopy__(self, memo: object) -> "_NegativeZero":
        return self


NEGATIVE_ZERO = _NegativeZero()
"""A sign-magnitude negative zero, as decoded; equal to 0."""


class BitError(ValueError):
    """The bits do not hold a value of the requested form, or a value does not fit."""


class Truncated(BitError):
    """A read ran past the end of the data."""


def _check_width(n: int, low: int) -> None:
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError(f"width must be an int, not {type(n).__name__}")
    if not low <= n <= MAX_WIDTH:
        raise BitError(f"width {n} outside {low}..{MAX_WIDTH}")


class BitReader:
    """Reads fields MSB-first from ``data[start_bit:end_bit]`` (bit positions)."""

    __slots__ = ("_data", "_pos", "_end")

    def __init__(self, data: bytes, start: int = 0, end: int | None = None) -> None:
        data = bytes(data)
        total = len(data) * 8
        end = total if end is None else end
        if not 0 <= start <= end <= total:
            raise ValueError(f"bit range {start}..{end} outside 0..{total}")
        self._data = data
        self._pos = start
        self._end = end

    @property
    def pos(self) -> int:
        """Bit position of the next read, counted from the start of ``data``."""
        return self._pos

    @property
    def remaining(self) -> int:
        """Bits left before the end."""
        return self._end - self._pos

    def _take(self, n: int) -> int:
        if n > self._end - self._pos:
            raise Truncated(f"need {n} bits at bit {self._pos}, {self._end - self._pos} left")
        if n == 0:
            return 0
        first = self._pos >> 3
        last = (self._pos + n + 7) >> 3
        chunk = int.from_bytes(self._data[first:last], "big")
        value = (chunk >> ((last << 3) - self._pos - n)) & ((1 << n) - 1)
        self._pos += n
        return value

    def uint(self, n: int) -> int:
        """Unsigned field of ``n`` bits, 0 to 64 (0 reads nothing and returns 0)."""
        _check_width(n, 0)
        return self._take(n)

    def sint(self, n: int) -> int:
        """Two's-complement field of ``n`` bits, 1 to 64."""
        _check_width(n, 1)
        v = self._take(n)
        return v - (1 << n) if v >> (n - 1) else v

    def smag(self, n: int) -> int:
        """Sign-magnitude field of ``n`` bits, 2 to 64; a negative zero is :data:`NEGATIVE_ZERO`."""
        _check_width(n, 2)
        v = self._take(n)
        magnitude = v & ((1 << (n - 1)) - 1)
        if v >> (n - 1):
            return -magnitude if magnitude else NEGATIVE_ZERO
        return magnitude

    def octets(self, count: int) -> bytes:
        """``count`` whole bytes, at any bit alignment."""
        if count < 0:
            raise BitError(f"negative octet count {count}")
        n = count * 8
        if n > self.remaining:
            raise Truncated(f"need {n} bits at bit {self._pos}, {self.remaining} left")
        if self._pos & 7 == 0:
            out = self._data[self._pos >> 3:(self._pos >> 3) + count]
            self._pos += n
            return out
        return self._take(n).to_bytes(count, "big")

    def mask(self, n: int) -> int:
        """Unsigned field of any ``n`` bits from 0, for bit masks wider than 64 bits."""
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise BitError(f"bit count {n!r} is not a non-negative int")
        return self._take(n)

    def tail(self) -> tuple[int, int]:
        """Every bit left, as ``(count, value)``: ``count`` bits, MSB first, as one unsigned int."""
        n = self.remaining
        if n == 0:
            return 0, 0
        first = self._pos >> 3
        last = (self._end + 7) >> 3
        chunk = int.from_bytes(self._data[first:last], "big")
        value = (chunk >> ((last << 3) - self._end)) & ((1 << n) - 1)
        self._pos = self._end
        return n, value

    def skip(self, n: int) -> None:
        """Advance ``n`` bits without interpreting them."""
        if n < 0:
            raise ValueError(f"cannot skip {n} bits")
        if n > self.remaining:
            raise Truncated(f"need {n} bits at bit {self._pos}, {self.remaining} left")
        self._pos += n

    def align(self) -> int:
        """Advance to the next byte boundary; return the padding value read (0 if aligned)."""
        return self.uint(-self._pos & 7)


class BitWriter:
    """Appends fields MSB-first; :meth:`to_bytes` zero-fills the last byte."""

    __slots__ = ("_out", "_acc", "_n")

    def __init__(self) -> None:
        self._out = bytearray()
        self._acc = 0   # pending bits not yet in _out
        self._n = 0     # number of pending bits, < 72 between calls

    @property
    def pos(self) -> int:
        """Bits written so far."""
        return len(self._out) * 8 + self._n

    def _put(self, value: int, n: int) -> None:
        self._acc = (self._acc << n) | value
        self._n += n
        if self._n >= 64:
            whole = self._n >> 3
            rest = self._n & 7
            self._out += (self._acc >> rest).to_bytes(whole, "big")
            self._acc &= (1 << rest) - 1
            self._n = rest

    def uint(self, value: int, n: int) -> None:
        """Unsigned ``value`` in ``n`` bits, 0 to 64."""
        _check_width(n, 0)
        if not 0 <= value < (1 << n):
            raise BitError(f"{value} does not fit {n}-bit unsigned")
        self._put(value, n)

    def sint(self, value: int, n: int) -> None:
        """Two's-complement ``value`` in ``n`` bits, 1 to 64."""
        _check_width(n, 1)
        half = 1 << (n - 1)
        if not -half <= value < half:
            raise BitError(f"{value} does not fit {n}-bit two's complement")
        self._put(value & ((1 << n) - 1), n)

    def smag(self, value: int, n: int) -> None:
        """Sign-magnitude ``value`` in ``n`` bits, 2 to 64.

        Zero is written positive, :data:`NEGATIVE_ZERO` with the sign bit set.
        """
        _check_width(n, 2)
        half = 1 << (n - 1)
        if not -half < value < half:
            raise BitError(f"{value} does not fit {n}-bit sign-magnitude")
        if value is NEGATIVE_ZERO:
            self._put(half, n)
        else:
            self._put(half | -value if value < 0 else value, n)

    def mask(self, value: int, n: int) -> None:
        """Unsigned ``value`` in ``n`` bits, any ``n`` from 0 (BitReader.mask, BitReader.tail)."""
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise BitError(f"bit count {n!r} is not a non-negative int")
        if not isinstance(value, int) or not 0 <= value < (1 << n):
            raise BitError(f"{value!r} does not fit {n} bits")
        self._put(value, n)

    tail = mask

    def octets(self, data: bytes) -> None:
        """Whole bytes, at any bit alignment."""
        data = bytes(data)
        if self._n == 0:
            self._out += data
        elif data:
            self._put(int.from_bytes(data, "big"), len(data) * 8)

    def align(self) -> int:
        """Write zero bits up to the next byte boundary; return how many."""
        pad = -self.pos & 7
        self._put(0, pad)
        return pad

    def to_bytes(self) -> bytes:
        """Everything written, the last byte filled with zero bits."""
        pad = -self._n & 7
        tail = (self._acc << pad).to_bytes((self._n + pad) >> 3, "big")
        return bytes(self._out) + tail
