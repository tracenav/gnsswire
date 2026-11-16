"""Sentence framing: :func:`parse`, :func:`scan` and :func:`encode_frame`.

Source: u-blox F9 HPG 1.51 Interface Description (UBXDOC-963802114-13124 R01), section
2.1 "NMEA frame structure" and its figure, which stands in for NMEA 0183
v4.11 (published by the NMEA for sale, not freely available, and not used
here). A sentence is::

    $ <address> [,<field>]... * <two hex characters> CR LF

- Start character "always '$'".
- Address field: "digits and uppercase letters, cannot be null" (talker and
  sentence formatter, or a proprietary mnemonic such as ``PUBX``).
- Data fields "separated by commas", "values can be null".
- Checksum field "starts with a '*', followed by two characters checksum in
  hex", computed over the range between ``$`` and ``*``, both excluded.
  The figure does not define the algorithm; it is the XOR of the bytes in that
  range, which every example sentence in chapter 2 with a correct checksum
  confirms (tests/test_frame.py lists them, and the ones the document prints
  with a wrong checksum).
- End sequence "always \\r\\n".

Choices where the u-blox document is silent (the NMEA standard defines these
but is not freely available), or where a receiver is better lenient:

- AMBIGUOUS: the case of the checksum's hex digits. The document says only
  "in hex" (and its field tables "hexadecimal"); every example is
  uppercase. :func:`parse` accepts two uppercase or two lowercase digits
  (``strict=True``: uppercase only). The case is kept in
  :attr:`Frame.lower_hex`, so ``encode(frame)`` gives the frame's bytes
  back; :func:`encode_frame` writes uppercase unless told otherwise.
- Line ending: "always \\r\\n". A bare LF, as left by tools that convert
  line endings, is accepted too unless ``strict=True``, and kept in
  :attr:`Frame.ending`. A bare CR is not: after a CR, a frame cannot be
  told complete until the next byte arrives, and a CR followed by anything
  but LF is no line ending the document or common practice uses.
- AMBIGUOUS: the characters allowed in data fields. Accepted: printable ASCII
  0x20 to 0x7E except ``$`` and ``*``, which delimit the frame. The TXT
  examples (section 2.7.18) have spaces and lowercase letters in a field.
- Maximum length. Section 2.2 makes the standard's 82-character limit an
  option (CFG-NMEA-LIMIT82, "strict limit to 82 characters maximum"); with it
  off, u-blox sentences are longer: the PUBX,00 example (section 2.9.2.2) is
  111 bytes and the PUBX,03 example (section 2.9.4.2) 200, a length that
  grows by six fields per tracked satellite. So 82 is not a validity rule here. :data:`MAX_LENGTH`
  is only a bound on how far :func:`parse` looks for the end of a sentence,
  set well above anything a receiver can emit.
- TAG blocks (``\\s:1*78\\`` before the ``$``, shown in the GGA and RMC
  examples, sections 2.8.1 and 2.8.5) are not part of this framing:
  :func:`parse` finds no sentence at a ``\\`` and :func:`scan` yields the
  sentence that follows the block.

  They stay outside the framing because the document uses them only
  for the secondary output (NMEA-NAV2-*, section 2.8, ``s:1``), whose
  sentences are byte-for-byte standard sentences, and GGA and ZDA decode the
  same either way. A caller that runs both outputs and must tell them apart
  can still see the block: it ends at ``frame.offset``, so
  ``buf[frame.offset - 1:frame.offset] == b"\\\\"`` marks a tagged sentence.
  ``!``-led encapsulation sentences (AIS and similar) are not in the
  document and not GNSS output; they are not framed either.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Buffer   # Python 3.12; annotations only

MAX_LENGTH = 4096
"""Longest sentence :func:`parse` accepts, ``$`` to LF inclusive."""

CRLF = b"\r\n"
ENDINGS = (CRLF, b"\n")
"""Line endings :func:`parse` accepts; ``strict=True`` accepts the first only."""

_START = 0x24   # '$'
_STAR = 0x2A    # '*'
_CR, _LF = 0x0D, 0x0A
_UPPER = b"0123456789ABCDEF"
_LOWER = b"0123456789abcdef"

# Longest prefix of a well-formed sentence body: address, then optional
# comma-led data fields of printable ASCII other than '$' and '*'.
_BODY = re.compile(rb"[0-9A-Z]*(?:,[\x20-\x23\x25-\x29\x2B-\x7E]*)?")


class Error(ValueError):
    """Base of every exception this codec raises for data, frames or messages."""


@dataclass(frozen=True, slots=True)
class Frame:
    """One sentence, from ``$`` to the line ending, with a valid checksum."""

    offset: int   # where the frame starts in the buffer that was parsed
    length: int   # bytes the frame occupies, framing included
    payload: bytes   # between '$' and '*', both excluded: address and fields
    lower_hex: bool = False   # the checksum's hex digits were lowercase
    ending: bytes = CRLF      # the line ending as received, CR LF or LF


@dataclass(frozen=True, slots=True)
class NeedMore:
    """The bytes at the offset could start a frame, but it is not all here yet."""

    needed: int   # total bytes required from the offset to decide; 0 if not yet known


@dataclass(frozen=True, slots=True)
class Invalid:
    """No valid frame starts at the offset."""

    reason: str


def _checksum(data: bytes) -> int:
    x = 0
    for b in data:
        x ^= b
    return x


def _view(buf: Buffer) -> bytes | bytearray:
    """``buf`` as bytes or a bytearray (``re`` and ``find`` need one of them)."""
    if isinstance(buf, (bytes, bytearray)):
        return buf
    return bytes(memoryview(buf))


def _check_offset(buf: Buffer, offset: int) -> None:
    if not 0 <= offset <= len(buf):
        raise Error(f"offset {offset} outside buffer of {len(buf)} bytes")


def parse(buf: Buffer, offset: int = 0, *, strict: bool = False) -> Frame | NeedMore | Invalid:
    """Is there a valid sentence starting exactly at ``offset``? Never searches.

    ``buf`` is any bytes-like object. Lowercase checksum digits and a bare
    LF ending are accepted unless ``strict`` (module docstring).
    """
    buf = _view(buf)
    _check_offset(buf, offset)
    n = len(buf)
    if offset == n:
        return NeedMore(0)
    if buf[offset] != _START:
        return Invalid("no '$' start character")
    # The '*' may sit at offset + MAX_LENGTH - 5 at the latest.
    limit = offset + MAX_LENGTH - 4
    star = _BODY.match(buf, offset + 1, min(n, limit)).end()
    if star >= limit:
        return Invalid(f"no '*' within {MAX_LENGTH} bytes")
    if star == n:
        return NeedMore(0)
    if buf[star] != _STAR:
        if buf.find(b",", offset + 1, star) < 0:
            return Invalid("address is not digits and uppercase letters")
        return Invalid(f"byte {buf[star]:#04x} not allowed in a field")
    if star == offset + 1 or buf[offset + 1] == 0x2C:
        return Invalid("empty address")
    digits = buf[star + 1:star + 3]
    allowed = (_UPPER,) if strict else (_UPPER, _LOWER)
    if not any(all(b in table for b in digits) for table in allowed):
        return Invalid("checksum is not two uppercase hex digits" if strict
                       else "checksum is not two hex digits of one case")
    end = star + 3   # first byte of the line ending
    crlf_total = end + 2 - offset
    if n <= end:
        return NeedMore(crlf_total if strict else crlf_total - 1)
    if buf[end] == _LF and not strict:
        ending = b"\n"
    elif buf[end] != _CR:
        return Invalid("no CR LF after the checksum" if strict
                       else "no CR LF or LF after the checksum")
    elif n <= end + 1:
        return NeedMore(crlf_total)
    elif buf[end + 1] != _LF:
        return Invalid("no CR LF after the checksum")
    else:
        ending = CRLF
    payload = bytes(buf[offset + 1:star])
    if int(digits, 16) != _checksum(payload):
        return Invalid("checksum mismatch")
    lower = any(b in b"abcdef" for b in digits)
    return Frame(offset, end + len(ending) - offset, payload, lower, ending)


def scan(buf: Buffer, offset: int = 0, *, strict: bool = False) -> Iterator[Frame]:
    """Every valid sentence from ``offset`` on, skipping one byte after anything else.

    The buffer is taken as complete: a sentence cut off at its end is skipped
    like any other invalid bytes. A false start costs at most
    :data:`MAX_LENGTH` bytes of matching, a constant.
    """
    buf = _view(buf)
    _check_offset(buf, offset)
    pos = offset
    while (pos := buf.find(b"$", pos)) >= 0:
        result = parse(buf, pos, strict=strict)
        if isinstance(result, Frame):
            yield result
            pos += result.length
        else:
            pos += 1


def encode_frame(payload: Buffer, *, lower_hex: bool = False, ending: bytes = CRLF) -> bytes:
    """Frame a sentence body (address and fields, no ``$`` or ``*``).

    The checksum is written in uppercase and the line ends in CR LF, as the
    document prints them, unless ``lower_hex`` or ``ending`` (one of
    :data:`ENDINGS`) says otherwise, which only re-encoding a received
    :class:`Frame` needs.
    """
    payload = bytes(payload)
    body = _BODY.fullmatch(payload)
    if body is None or not payload or payload[0] == 0x2C:
        raise Error("payload is not an address followed by comma-separated fields")
    if ending not in ENDINGS:
        raise Error(f"line ending {ending!r} is not one of {ENDINGS!r}")
    if len(payload) + 4 + len(ending) > MAX_LENGTH:
        raise Error(f"sentence longer than {MAX_LENGTH} bytes")
    digits = b"%02x" if lower_hex else b"%02X"
    return b"$" + payload + b"*" + digits % _checksum(payload) + bytes(ending)
