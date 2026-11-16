"""Frame layer: :func:`parse`, :func:`scan` and :func:`encode_frame`.

Source: SkyTraq application note AN0039, "Binary Messages Raw Measurement
Data Extension of SkyTraq Phoenix GNSS Receiver", version 1.4.42
(2022-07-22), section "Binary Message Structure"; AN0037 ("Binary Messages
of SkyTraq Phoenix GNSS Receiver", version 1.4.69, 2025-03-26) prints the
same section word for word:

======== ======== ======================================================
bytes    field    content
======== ======== ======================================================
2        start    0xA0, 0xA1
2        PL       payload length, 16 bits, big-endian ("All payloads ...
                  are transferred in big-endian format")
PL       payload  message ID (one byte, "0x01~0xFF"), then the message body
1        CS       checksum
2        end      0x0D, 0x0A
======== ======== ======================================================

- Checksum: "the 8-bit exclusive OR of only the payload bytes which start
  from Message ID until the last byte prior to the checksum byte". AMBIGUOUS:
  the pseudo-code under it loops "For n = 0 to N" with N = PL, which read
  literally takes PL + 1 bytes. The prose is followed (PL bytes, from the
  message ID); every example frame of AN0039 that is checked in the tests
  (0xDC, 0xDD, 0xE0 to 0xE3, 0xE5, 0xE6) satisfies it.
- A payload holds at least the message ID, so PL = 0 is refused, and so is
  message ID 0, which is outside the stated range 0x01 to 0xFF.
- The structure diagram says "Payload up to 65535 bytes", all a 16-bit PL
  can hold.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import reduce
from itertools import accumulate
from operator import xor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Buffer   # Python 3.12; annotations only

START = b"\xa0\xa1"
END = b"\x0d\x0a"
HEADER = 4        # start sequence and PL
OVERHEAD = 7      # header, checksum and end sequence
MAX_PAYLOAD = 0xFFFF


class Error(ValueError):
    """Base of every exception this codec raises for data, frames or messages."""


@dataclass(frozen=True, slots=True)
class Frame:
    """One ``A0 A1`` frame with a valid checksum and end sequence."""

    offset: int      # where the frame starts in the buffer that was parsed
    length: int      # bytes the frame occupies, framing included
    msg_id: int      # the message ID, first byte of the payload
    body: bytes      # the message body: the payload after the message ID


@dataclass(frozen=True, slots=True)
class NeedMore:
    """The bytes at the offset could start a frame, but it is not all here yet."""

    needed: int   # total bytes required from the offset to decide; 0 if not yet known


@dataclass(frozen=True, slots=True)
class Invalid:
    """No valid frame starts at the offset."""

    reason: str


def checksum(payload: Buffer) -> int:
    """CS: the exclusive OR of the payload bytes (message ID and body)."""
    return reduce(xor, _view(payload), 0)


def _view(buf: Buffer) -> bytes | bytearray | memoryview:
    """``buf`` as a sequence of byte values, without copying it."""
    if isinstance(buf, (bytes, bytearray)):
        return buf
    return memoryview(buf).cast("B")


def _check_offset(buf: Buffer, offset: int) -> None:
    if not 0 <= offset <= len(buf):
        raise Error(f"offset {offset} outside buffer of {len(buf)} bytes")


class _Xors:
    """The checksum of any slice of one buffer in constant time: X[b] ^ X[a].

    X[i] is the exclusive OR of the first i bytes, kept for a window that
    moves with the scan, so each byte is visited a bounded number of times
    however many false starts claim it.
    """

    def __init__(self, buf: bytes | bytearray, window: int = 1 << 16) -> None:
        self._buf, self._window = buf, window
        self._base, self._x = 0, [0]

    def __call__(self, start: int, end: int) -> int:
        if start < self._base or start - self._base > self._window:
            self._base, self._x = start, [0]
        x = self._x
        need = end - self._base
        if len(x) <= need:
            more = self._buf[self._base + len(x) - 1:self._base + need]
            x.extend(list(accumulate(more, xor, initial=x[-1]))[1:])
        return x[end - self._base] ^ x[start - self._base]


def parse(buf: Buffer, offset: int = 0) -> Frame | NeedMore | Invalid:
    """Is there a valid SkyTraq binary frame starting exactly at ``offset``? Never searches.

    ``buf`` is any bytes-like object (``bytes``, ``bytearray``, ``memoryview``...).
    """
    view = _view(buf)
    return _parse(view, offset, lambda start, end: checksum(view[start:end]))


def _parse(buf: bytes | bytearray | memoryview, offset: int,
           xors: Callable[[int, int], int]) -> Frame | NeedMore | Invalid:
    _check_offset(buf, offset)
    have = len(buf) - offset
    for i in range(min(have, 2)):
        if buf[offset + i] != START[i]:
            return Invalid("no 0xA0 0xA1 start sequence")
    if have < HEADER:
        return NeedMore(0)
    size = buf[offset + 2] << 8 | buf[offset + 3]
    if size == 0:
        return Invalid("payload length 0: no message ID")
    total = OVERHEAD + size
    if have < total:
        return NeedMore(total)
    # Constant-time checks first: a false start must not cost its claimed length.
    if (buf[offset + total - 2], buf[offset + total - 1]) != (END[0], END[1]):
        return Invalid("no 0x0D 0x0A end sequence")
    start = offset + HEADER
    if xors(start, start + size) != buf[start + size]:
        return Invalid("checksum mismatch")
    if buf[start] == 0:
        return Invalid("message ID 0 is outside 0x01 to 0xFF")
    return Frame(offset, total, buf[start], bytes(buf[start + 1:start + size]))


def scan(buf: Buffer, offset: int = 0) -> Iterator[Frame]:
    """Every valid frame from ``offset`` on, skipping one byte after anything else.

    The buffer is taken as complete: a frame cut off at its end is skipped
    like any other invalid bytes. A false frame start costs the same small
    amount whatever length it claims: the checksums come from prefix XORs
    (``_Xors``), which visit each byte a bounded number of times.
    """
    data = buf if isinstance(buf, (bytes, bytearray)) else bytes(memoryview(buf))
    _check_offset(data, offset)
    xors = _Xors(data)
    pos = offset
    while (pos := data.find(START[:1], pos)) >= 0:
        result = _parse(data, pos, xors)
        if isinstance(result, Frame):
            yield result
            pos += result.length
        else:
            pos += 1


def encode_frame(msg_id: int, body: Buffer) -> bytes:
    """Frame a message body under a message ID."""
    if not 1 <= msg_id <= 0xFF:
        raise Error("the message ID is one byte, 0x01 to 0xFF")
    payload = bytes((msg_id,)) + bytes(body)
    if len(payload) > MAX_PAYLOAD:
        raise Error(f"payload of {len(payload)} bytes exceeds the 16-bit PL field")
    return START + len(payload).to_bytes(2, "big") + payload + bytes((checksum(payload),)) + END
