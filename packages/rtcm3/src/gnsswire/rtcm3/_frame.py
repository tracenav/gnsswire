"""Transport layer: :func:`parse`, :func:`scan` and :func:`encode_frame`.

Source: RTCM 10403.3, section 4.1, Table 4-1 "Version 3 Frame Structure":

=========== ======== ===================================================
field       bits     content
=========== ======== ===================================================
preamble    8        11010011 (0xD3)
reserved    6        "Not defined - set to 000000"
length      10       message length in bytes, 0 to 1023
message     8·length the data message of chapter 3
CRC         24       CRC-24Q over preamble, reserved, length and message
=========== ======== ===================================================

- Reserved bits: "should be set to zero by the Transport Layer Control ...
  The mobile user receiver should ignore these bits and not assume they will
  always be set to zero." So :func:`parse` accepts any value, and
  :class:`Frame` keeps it so that a frame re-encodes to its own bytes.
  :func:`encode_frame` writes zero unless told otherwise. A decoded message
  does not hold them (they belong to the transport layer, not to the
  message of chapter 3), so ``encode(message)`` writes zero, as the
  standard asks of a transmitter, and ``encode(decode(frame))`` is the
  frame's bytes only when its reserved bits are zero, as they are in every
  conforming frame. ``encode(frame)`` keeps them in every case.
- Length zero is the 48-bit "filler" message, a valid frame with an empty
  message.
- CRC: "the QualComm CRC algorithm" with "a seed of 0", over "the sequence
  of bits beginning with the preamble, through to the end of the Variable
  Length Message Field", parity bit p1 sent first. That is
  :data:`gnsswire.bits.CRC24Q`, transmitted most significant byte first.
  Section 4.2's example frame (a message 1005) is a test case.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gnsswire.bits import CRC24Q, CrcSlices

if TYPE_CHECKING:
    from collections.abc import Buffer   # Python 3.12; annotations only

PREAMBLE = 0xD3
HEADER = 3        # preamble, reserved, length
OVERHEAD = 6      # header and CRC
MAX_PAYLOAD = 1023


class Error(ValueError):
    """Base of every exception this codec raises for data, frames or messages."""


@dataclass(frozen=True, slots=True)
class Frame:
    """One ``D3`` frame with a valid CRC-24Q."""

    offset: int        # where the frame starts in the buffer that was parsed
    length: int        # bytes the frame occupies, framing included
    payload: bytes     # the variable-length data message
    reserved: int = 0  # the six reserved header bits, as received


@dataclass(frozen=True, slots=True)
class NeedMore:
    """The bytes at the offset could start a frame, but it is not all here yet."""

    needed: int   # total bytes required from the offset to decide; 0 if not yet known


@dataclass(frozen=True, slots=True)
class Invalid:
    """No valid frame starts at the offset."""

    reason: str


def _view(buf: Buffer) -> bytes | bytearray | memoryview:
    """``buf`` as a sequence of byte values, without copying it."""
    if isinstance(buf, (bytes, bytearray)):
        return buf
    return memoryview(buf).cast("B")


def _check_offset(buf: Buffer, offset: int) -> None:
    if not 0 <= offset <= len(buf):
        raise Error(f"offset {offset} outside buffer of {len(buf)} bytes")


def parse(buf: Buffer, offset: int = 0) -> Frame | NeedMore | Invalid:
    """Is there a valid RTCM 3 frame starting exactly at ``offset``? Never searches.

    ``buf`` is any bytes-like object (``bytes``, ``bytearray``, ``memoryview``...).
    """
    view = _view(buf)
    return _parse(view, offset, lambda start, end: CRC24Q(view[start:end]))


def _parse(buf: bytes | bytearray | memoryview, offset: int,
           crc: Callable[[int, int], int]) -> Frame | NeedMore | Invalid:
    _check_offset(buf, offset)
    have = len(buf) - offset
    if have and buf[offset] != PREAMBLE:
        return Invalid("no 0xD3 preamble")
    if have < HEADER:
        return NeedMore(0)
    word = int.from_bytes(buf[offset + 1:offset + 3], "big")
    total = OVERHEAD + (word & 0x3FF)
    if have < total:
        return NeedMore(total)
    end = offset + total - 3
    if crc(offset, end) != int.from_bytes(buf[end:end + 3], "big"):
        return Invalid("CRC-24Q mismatch")
    return Frame(offset, total, bytes(buf[offset + HEADER:end]), word >> 10)


def scan(buf: Buffer, offset: int = 0) -> Iterator[Frame]:
    """Every valid frame from ``offset`` on, skipping one byte after anything else.

    The buffer is taken as complete: a frame cut off at its end is skipped
    like any other invalid bytes. A false frame start costs the same small
    amount whatever length it claims: the CRCs come from
    :class:`gnsswire.bits.CrcSlices`, which passes over each byte once.
    """
    data = buf if isinstance(buf, (bytes, bytearray)) else bytes(memoryview(buf))
    _check_offset(data, offset)
    crc = CrcSlices(CRC24Q, data)
    pos = offset
    while (pos := data.find(PREAMBLE, pos)) >= 0:
        result = _parse(data, pos, crc)
        if isinstance(result, Frame):
            yield result
            pos += result.length
        else:
            pos += 1


def encode_frame(payload: bytes, reserved: int = 0) -> bytes:
    """Frame a data message; ``reserved`` is the six header bits the standard leaves at zero."""
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise Error(f"message of {len(payload)} bytes exceeds the 10-bit length field")
    if not 0 <= reserved <= 0x3F:
        raise Error("reserved is six bits")
    head = bytes((PREAMBLE,)) + ((reserved << 10) | len(payload)).to_bytes(2, "big")
    body = head + bytes(payload)
    return body + CRC24Q(body).to_bytes(3, "big")
