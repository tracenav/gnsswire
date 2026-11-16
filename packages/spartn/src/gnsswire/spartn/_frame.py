"""Transport layer: :func:`parse`, :func:`scan` and :func:`encode_frame`.

Source: SPARTN v2.0.3, section 7, Figure 7.1 and Tables 7.1 and 7.2. A frame
is, in order:

=========== ======= ============ ===========================================
block       fields  bits         content
=========== ======= ============ ===========================================
frame start TF001   8            preamble 0x73
            TF002   7            message type (Table 6.1)
            TF003   10           payload length, in bytes
            TF004   1            encryption and authentication flag (EAF)
            TF005   2            message CRC type (Table 7.2)
            TF006   4            frame CRC
payload     TF007   4            message subtype
description TF008   1            time tag type: 0 for 16 bits, 1 for 32
            TF009   16 or 32     GNSS time tag
            TF010   7            solution ID
            TF011   4            solution processor ID
            TF012   4            encryption ID, only when TF004 = 1
            TF013   6            encryption sequence number, only when TF004 = 1
            TF014   3            authentication indicator, only when TF004 = 1
            TF015   3            embedded authentication length, only when TF004 = 1
payload     TF016   8·TF003      the message (encrypted when TF004 = 1)
embedded    TF017   TF015 table  only when TF014 > 1: 64, 96, 128, 256 or 512 bits
auth. data
message CRC TF018   8 to 32      over TF002 to TF017, type and size from TF005
=========== ======= ============ ===========================================

Every block is a whole number of bytes: the frame start is 32 bits, the
payload description 32 or 48 bits (plus 16 with TF004 = 1), and the payload
and authentication data whole bytes. The payload's own fill bits are the
message's business (TF016: "fill bits must be inserted to match the payload
length").

CRCs:

- TF006, Table 7.1: a CRC-4 over the 20 bits of TF002 to TF005 followed by
  four zero bits, with the parameters the table lists (poly 0x09,
  initialised at zero, input and output reflected, zero final XOR). That is
  :data:`gnsswire.bits.CRC4_SPARTN` over three bytes.
- TF018, Table 7.2: "computed using all bits from TF002 through TF017", so
  not the preamble. The table gives polynomial, initialisation and final XOR
  but not reflection (AMBIGUOUS; README, "Limitations"). This codec takes the literal
  reading, unreflected with the initialisation the table states: CRC-8/SMBUS,
  CRC-16/XMODEM, CRC-24/LTE-A and CRC-32/BZIP2 in catalogue terms, each
  tested against the catalogue's parameters, check value and residue. The
  other reading of each (reflected, or OpenPGP's initialisation for
  "Radix-64") has a different check value. Which reading senders use can
  only be settled by real frames; no public sample was found to commit.

Embedded authentication (TF017) is kept as bytes, not checked: the
algorithm (TF014 = 2, Ed25519) needs a key this codec does not handle.
TF015 "shall be ignored" when TF014 is 0 or 1, so its value is kept as sent
but no authentication data is read. With TF014 above 1 and a TF015 value the
table leaves TBD (5 to 7), the frame's length is unknown and it is
:class:`Invalid`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ClassVar

from gnsswire.bits import (
    CRC4_SPARTN,
    CRC8_SMBUS,
    CRC16_XMODEM,
    CRC24_LTE_A,
    CRC32_BZIP2,
    BitError,
    BitReader,
    Crc,
    CrcSlices,
    F,
    U,
    pack,
    read,
)

if TYPE_CHECKING:
    from collections.abc import Buffer   # Python 3.12; annotations only

PREAMBLE = 0x73
START = 4               # bytes of TF001 to TF006
MAX_PAYLOAD = 0x3FF     # TF003, 10 bits

# Table 7.2: TF005 to the CRC that TF018 holds.
CRCS: dict[int, Crc] = {0: CRC8_SMBUS, 1: CRC16_XMODEM, 2: CRC24_LTE_A, 3: CRC32_BZIP2}
# TF015 to the length of TF017 in bits; 5 to 7 are TBD.
AUTH_BITS: dict[int, int] = {0: 64, 1: 96, 2: 128, 3: 256, 4: 512}


class Error(ValueError):
    """Base of every exception this codec raises for data, frames or messages."""


@dataclass(frozen=True, slots=True)
class Description:
    """The payload description block, TF007 to TF015 (Table 7.1).

    TF012 to TF015 are present only when the frame's EAF (TF004) is 1, and
    are ``None`` otherwise. The time tag is kept as sent: 16 bits when
    ``time_tag_type`` is 0, 32 bits when it is 1.
    """

    PARAMS: ClassVar[tuple[str, ...]] = ("eaf",)

    subtype: Annotated[int, U(4, "TF007")]
    time_tag_type: Annotated[int, U(1, "TF008")]
    time_tag: Annotated[int, U(16 + 16 * F.time_tag_type, "TF009")]
    solution_id: Annotated[int, U(7, "TF010")]
    processor_id: Annotated[int, U(4, "TF011")]
    encryption_id: Annotated[int | None, U(4, "TF012", when=F.eaf)]
    sequence: Annotated[int | None, U(6, "TF013", when=F.eaf)]
    auth_indicator: Annotated[int | None, U(3, "TF014", when=F.eaf)]
    auth_length: Annotated[int | None, U(3, "TF015", when=F.eaf)]


@dataclass(frozen=True, slots=True)
class Frame:
    """One ``73`` frame whose frame CRC (TF006) and message CRC (TF018) are valid.

    ``payload`` is TF016 as on the wire: cipher text when ``eaf`` is 1. A
    frame from :func:`gnsswire.spartn.decrypt` holds the plain text instead
    and has ``decrypted`` set; its CRC is that of the encrypted frame, so
    :func:`encode` refuses it until it is encrypted again.
    """

    offset: int                # where the frame starts in the buffer that was parsed
    length: int                # bytes the frame occupies, framing included
    message_type: int          # TF002
    eaf: int                   # TF004
    crc_type: int              # TF005
    description: Description   # TF007 to TF015
    payload: bytes             # TF016; its length is TF003
    auth: bytes = b""          # TF017, empty when absent
    decrypted: bool = False


@dataclass(frozen=True, slots=True)
class NeedMore:
    """The bytes at the offset could start a frame, but it is not all here yet."""

    needed: int   # total bytes required from the offset to decide; 0 if not yet known


@dataclass(frozen=True, slots=True)
class Invalid:
    """No valid frame starts at the offset."""

    reason: str


def frame_crc(start: bytes) -> int:
    """TF006 for the first three bytes of a frame (TF001 to TF006 less the last nibble)."""
    return CRC4_SPARTN(bytes((start[1], start[2], start[3] & 0xF0)))


def _description_bytes(byte4: int, eaf: int) -> int:
    # TF007 is the high nibble of byte 4, TF008 the bit after it.
    return (6 if byte4 & 0x08 else 4) + (2 if eaf else 0)


def _view(buf: Buffer) -> bytes | bytearray | memoryview:
    """``buf`` as a sequence of byte values, without copying it."""
    if isinstance(buf, (bytes, bytearray)):
        return buf
    return memoryview(buf).cast("B")


def _check_offset(buf: Buffer, offset: int) -> None:
    if not 0 <= offset <= len(buf):
        raise Error(f"offset {offset} outside buffer of {len(buf)} bytes")


def parse(buf: Buffer, offset: int = 0) -> Frame | NeedMore | Invalid:
    """Is there a valid SPARTN frame starting exactly at ``offset``? Never searches.

    ``buf`` is any bytes-like object (``bytes``, ``bytearray``, ``memoryview``...).
    """
    view = _view(buf)
    return _parse(view, offset, lambda crc_type, start, end: CRCS[crc_type](view[start:end]))


def _parse(buf: bytes | bytearray | memoryview, offset: int,
           crc_of: Callable[[int, int, int], int]) -> Frame | NeedMore | Invalid:
    _check_offset(buf, offset)
    have = len(buf) - offset
    if have and buf[offset] != PREAMBLE:
        return Invalid("no 0x73 preamble")
    if have < START:
        return NeedMore(0)
    word = int.from_bytes(buf[offset + 1:offset + 4], "big")
    if frame_crc(buf[offset:offset + 4]) != word & 0xF:
        return Invalid("frame CRC (TF006) mismatch")
    message_type, payload_length = word >> 17, (word >> 7) & 0x3FF
    eaf, crc_type = (word >> 6) & 1, (word >> 4) & 3
    if have < START + 1:
        return NeedMore(0)
    head = START + _description_bytes(buf[offset + START], eaf)
    if have < head:
        return NeedMore(0)
    auth = 0
    if eaf:
        # TF014 and TF015 are the last six bits of the description block.
        last = buf[offset + head - 1]
        auth_indicator, auth_length = last >> 3 & 7, last & 7
        if auth_indicator > 1:
            if auth_length not in AUTH_BITS:
                return Invalid(f"embedded authentication length TF015 = {auth_length} "
                               f"is not defined")
            auth = AUTH_BITS[auth_length] // 8
    crc_bytes = CRCS[crc_type].width // 8
    end = head + payload_length + auth
    total = end + crc_bytes
    if have < total:
        return NeedMore(total)
    if crc_of(crc_type, offset + 1, offset + end) \
            != int.from_bytes(buf[offset + end:offset + total], "big"):
        return Invalid("message CRC (TF018) mismatch")
    description = read(Description, BitReader(buf[offset + START:offset + head]), eaf=eaf)
    payload = bytes(buf[offset + head:offset + head + payload_length])
    return Frame(offset, total, message_type, eaf, crc_type, description, payload,
                 bytes(buf[offset + head + payload_length:offset + end]))


def scan(buf: Buffer, offset: int = 0) -> Iterator[Frame]:
    """Every valid frame from ``offset`` on, skipping one byte after anything else.

    The buffer is taken as complete: a frame cut off at its end is skipped
    like any other invalid bytes. A false frame start costs the same small
    amount whatever length it claims: the message CRCs come from
    :class:`gnsswire.bits.CrcSlices`, which passes over each byte once per
    CRC type, and the description block is read only for a frame whose CRCs
    hold.
    """
    data = buf if isinstance(buf, (bytes, bytearray)) else bytes(memoryview(buf))
    _check_offset(data, offset)
    slices: dict[int, CrcSlices] = {}

    def crc_of(crc_type: int, start: int, end: int) -> int:
        if crc_type not in slices:
            slices[crc_type] = CrcSlices(CRCS[crc_type], data)
        return slices[crc_type](start, end)

    pos = offset
    while (pos := data.find(PREAMBLE, pos)) >= 0:
        result = _parse(data, pos, crc_of)
        if isinstance(result, Frame):
            yield result
            pos += result.length
        else:
            pos += 1


def encode_frame(message_type: int, eaf: int, crc_type: int, description: Description,
                 payload: bytes, auth: bytes = b"") -> bytes:
    """Frame a payload: compute TF003, TF006 and TF018 around the given fields.

    ``payload`` goes on the wire as given, so with ``eaf`` 1 it must already
    be the cipher text. ``auth`` must have the length that TF014 and TF015
    call for (empty unless TF014 is above 1).
    """
    if not 0 <= message_type <= 0x7F:
        raise Error("message type TF002 is 7 bits")
    if eaf not in (0, 1):
        raise Error("EAF TF004 is one bit")
    if crc_type not in CRCS:
        raise Error("CRC type TF005 is 0 to 3")
    payload, auth = bytes(payload), bytes(auth)
    if len(payload) > MAX_PAYLOAD:
        raise Error(f"payload of {len(payload)} bytes exceeds the 10-bit TF003")
    try:
        head = pack(description, eaf=eaf)
    except BitError as exc:
        raise Error(f"payload description: {exc}") from None
    want = 0
    if eaf and description.auth_indicator > 1:
        if description.auth_length not in AUTH_BITS:
            raise Error(f"TF015 = {description.auth_length} has no defined length")
        want = AUTH_BITS[description.auth_length] // 8
    if len(auth) != want:
        raise Error(f"embedded authentication data must be {want} bytes, got {len(auth)}")
    word = (message_type << 17) | (len(payload) << 7) | (eaf << 6) | (crc_type << 4)
    start = bytes((PREAMBLE,)) + word.to_bytes(3, "big")
    start = start[:3] + bytes((start[3] | frame_crc(start),))
    body = start + head + payload + auth
    crc = CRCS[crc_type]
    return body + crc(body[1:]).to_bytes(crc.width // 8, "big")
