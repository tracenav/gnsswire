"""Frame layer: :func:`parse`, :func:`scan` and :func:`encode_frame`.

Source: u-blox F9 HPG 1.51 Interface Description (UBXDOC-963802114-13124
R01, protocol version 27.50), section 3.2 "UBX frame structure" and
section 3.4 "UBX checksum". The
u-blox X20 HPG 2.11 Interface Description (UBXDOC-304424225-21617 R01, protocol version 50.11)
prints the same two sections, under the same numbers, word for word:

====== ======= ===========================================================
offset size    field
====== ======= ===========================================================
0      2       preamble, the synchronisation characters 0xB5 0x62
2      1       message class
3      1       message ID
4      2       length of the payload only, unsigned little-endian (U2)
6      length  payload
6+len  2       CK_A, CK_B
====== ======= ===========================================================

The checksum is the 8-bit Fletcher algorithm of section 3.4 over the bytes
from the class field up to, but excluding, the checksum fields: CK_A and CK_B
start at zero, and for each byte CK_A += byte, CK_B += CK_A, both modulo 256.
(The section cites "RFC 1145" for it; the Fletcher checksum options are in
RFC 1146. The pseudo-code is what this follows.)

Nothing in section 3 bounds the length below the 65535 that U2 can hold, and
no class or ID is excluded, so any class, ID and length frame here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import accumulate
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Buffer   # Python 3.12; annotations only

SYNC = b"\xb5\x62"
HEADER = 6    # sync, class, ID, length
OVERHEAD = 8  # header and checksum
MAX_PAYLOAD = 0xFFFF


class Error(ValueError):
    """Base of every exception this codec raises for data, frames or messages."""


@dataclass(frozen=True, slots=True)
class Frame:
    """One ``B5 62`` frame with a valid Fletcher checksum."""

    offset: int      # where the frame starts in the buffer that was parsed
    length: int      # bytes the frame occupies, framing included
    msg_class: int   # message class, byte 2
    msg_id: int      # message ID, byte 3
    payload: bytes   # the payload alone, without header or checksum


@dataclass(frozen=True, slots=True)
class NeedMore:
    """The bytes at the offset could start a frame, but it is not all here yet."""

    needed: int   # total bytes required from the offset to decide; 0 if not yet known


@dataclass(frozen=True, slots=True)
class Invalid:
    """No valid frame starts at the offset."""

    reason: str


def checksum(data: Buffer) -> bytes:
    """CK_A and CK_B of section 3.4 over ``data`` (class field to end of payload)."""
    # CK_A is the running sum; CK_B the sum of every running sum.
    data = _view(data)
    return bytes((sum(data) & 0xFF, sum(accumulate(data)) & 0xFF))


def _view(buf: Buffer) -> bytes | bytearray | memoryview:
    """``buf`` as a sequence of byte values, without copying it."""
    if isinstance(buf, (bytes, bytearray)):
        return buf
    return memoryview(buf).cast("B")


def _check_offset(buf: Buffer, offset: int) -> None:
    if not 0 <= offset <= len(buf):
        raise Error(f"offset {offset} outside buffer of {len(buf)} bytes")


class _Sums:
    """Section 3.4's checksum of any slice of one buffer, in constant time.

    With S[i] the sum of the first i bytes and T[i] = S[1] + ... + S[i],
    the running sums over ``buf[a:b]`` are S[k] - S[a] for k = a+1 .. b,
    so CK_A = S[b] - S[a] and CK_B = T[b] - T[a] - (b - a)·S[a], modulo
    256. The prefix sums are kept for a window that moves with the scan,
    so each byte is summed a bounded number of times however many false
    starts claim it.
    """

    def __init__(self, buf: bytes | bytearray, window: int = 1 << 16) -> None:
        self._buf, self._window = buf, window
        self._base, self._s, self._t = 0, [0], [0]

    def __call__(self, start: int, end: int) -> tuple[int, int]:
        if start < self._base or start - self._base > self._window:
            self._base, self._s, self._t = start, [0], [0]
        need = end - self._base
        s, t = self._s, self._t
        if len(s) <= need:
            more = self._buf[self._base + len(s) - 1:self._base + need]
            new = list(accumulate(more, initial=s[-1]))[1:]
            t.extend(list(accumulate(new, initial=t[-1]))[1:])
            s.extend(new)
        i, j = start - self._base, end - self._base
        return (s[j] - s[i]) & 0xFF, (t[j] - t[i] - (j - i) * s[i]) & 0xFF


def _whole(buf: bytes | bytearray | memoryview, start: int, end: int) -> tuple[int, int]:
    ck = checksum(buf[start:end])
    return ck[0], ck[1]


def parse(buf: Buffer, offset: int = 0) -> Frame | NeedMore | Invalid:
    """Is there a valid UBX frame starting exactly at ``offset``? Never searches.

    ``buf`` is any bytes-like object (``bytes``, ``bytearray``, ``memoryview``...).
    """
    view = _view(buf)
    return _parse(view, offset, lambda start, end: _whole(view, start, end))


def _parse(buf: bytes | bytearray | memoryview, offset: int,
           sums: Callable[[int, int], tuple[int, int]]) -> Frame | NeedMore | Invalid:
    _check_offset(buf, offset)
    have = len(buf) - offset
    for i in range(min(have, 2)):
        if buf[offset + i] != SYNC[i]:
            return Invalid("no 0xB5 0x62 preamble")
    if have < HEADER:
        return NeedMore(0)
    total = OVERHEAD + (buf[offset + 4] | buf[offset + 5] << 8)
    if have < total:
        return NeedMore(total)
    end = offset + total - 2
    if sums(offset + 2, end) != (buf[end], buf[end + 1]):
        return Invalid("checksum mismatch")
    return Frame(offset, total, buf[offset + 2], buf[offset + 3], bytes(buf[offset + HEADER:end]))


def scan(buf: Buffer, offset: int = 0) -> Iterator[Frame]:
    """Every valid frame from ``offset`` on, skipping one byte after anything else.

    The buffer is taken as complete: a frame cut off at its end is skipped
    like any other invalid bytes. A false frame start costs the same small
    amount whatever length it claims: the checksums come from prefix sums
    (``_Sums``), which pass over each byte a bounded number of times.
    """
    data = buf if isinstance(buf, (bytes, bytearray)) else bytes(memoryview(buf))
    _check_offset(data, offset)
    sums = _Sums(data)
    pos = offset
    while (pos := data.find(SYNC[:1], pos)) >= 0:
        result = _parse(data, pos, sums)
        if isinstance(result, Frame):
            yield result
            pos += result.length
        else:
            pos += 1


def encode_frame(msg_class: int, msg_id: int, payload: Buffer) -> bytes:
    """Frame a payload under a class and message ID."""
    payload = bytes(payload)
    if not (0 <= msg_class <= 0xFF and 0 <= msg_id <= 0xFF):
        raise Error("class and ID are one byte each")
    if len(payload) > MAX_PAYLOAD:
        raise Error(f"payload of {len(payload)} bytes exceeds the U2 length field")
    body = bytes((msg_class, msg_id)) + len(payload).to_bytes(2, "little") + payload
    return SYNC + body + checksum(body)
