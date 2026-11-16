"""SPARTN v2 codec: bytes to integer fields and back.

Message fields are the standard's SF integers, unscaled.

The interface is the same in every gnsswire codec (tests/test_layout.py):

- ``parse(buf, offset)`` answers one question, "is there a valid frame at this
  offset", and never searches. Resynchronisation policy belongs to the caller.
- ``scan(buf, offset)`` is the plain policy most callers want: yield every
  valid frame, skipping one byte after anything invalid.
- ``decode(frame)`` and ``encode(message)`` map a frame to a frozen dataclass
  of raw fields and back, losslessly.

Framing is in ``_frame`` (SPARTN v2.0.3 section 7, Tables 7.1 and 7.2), the
message tables in ``_messages`` (section 6.5: OCB, HPAC, GAD and BPAC) and
the cipher in ``_aes`` (FIPS 197 and RFC 3686).

A decoded :class:`Message` is the frame's transport fields with the message
table in ``body``. Encrypted frames (EAF, TF004, set) are decrypted with a
caller-supplied key: ``decode(decrypt(frame, key))``; and encrypted again
for the wire with ``encode(encrypt(to_frame(message), key))``. Section
8.15.1 builds the initialisation vector from the 32-bit time tag, so a frame
that carries the 16-bit half-day tag needs the caller to supply the full
one (:func:`iv`). :func:`decode_ocb_header` reads the header block of an
OCB message of any subtype, end-of-set flag included (section 8.4 item 5).

``encode`` accepts a :class:`Message`, or a :class:`Frame` (returning its
bytes); :func:`encode_frame` frames a payload given as bytes.

Errors: every exception this codec raises for data it cannot decode or a
message it cannot encode is an :class:`Error` (a ``ValueError``):
:class:`Unsupported`, :class:`Encrypted`, :class:`FieldError` (also a
``gnsswire.bits.BitError``), :class:`TimeTagError` and :class:`NoFrame`.
"""

from dataclasses import dataclass, replace
from typing import Any

from gnsswire.bits import BitError, BitReader, BitWriter, pack, read, unpack

from ._aes import ctr
from ._frame import (
    AUTH_BITS,
    CRCS,
    MAX_PAYLOAD,
    PREAMBLE,
    Description,
    Error,
    Frame,
    Invalid,
    NeedMore,
    encode_frame,
    frame_crc,
    parse,
    scan,
)
from ._messages import (
    DNU_TABLE_6_2,
    DNU_TABLE_8_2,
    Bias,
    Bpac,
    BpacArea,
    BpacGridPoint,
    Clock,
    Gad,
    GadArea,
    Hpac,
    HpacArea,
    IonoLarge,
    IonoSatellite,
    IonoSmall,
    Ionosphere,
    Ocb,
    OcbHeader,
    OcbSatellite,
    Orbit,
    PhaseBias,
    Troposphere,
    TropoLarge,
    TropoSmall,
)

__all__ = [
    "AUTH_BITS", "CRCS", "DNU_TABLE_6_2", "DNU_TABLE_8_2", "HALF_DAY", "MAX_PAYLOAD", "MESSAGES",
    "PREAMBLE", "BitError", "Bias", "Bpac", "BpacArea", "BpacGridPoint", "Clock", "Description",
    "Encrypted", "Error", "FieldError", "Frame", "Gad", "GadArea", "Hpac", "HpacArea", "Invalid",
    "IonoLarge", "IonoSatellite", "IonoSmall", "Ionosphere", "Message", "NeedMore", "NoFrame",
    "Ocb", "OcbHeader", "OcbSatellite", "Orbit", "PhaseBias", "TimeTagError", "Troposphere",
    "TropoLarge", "TropoSmall", "Unsupported", "decode", "decode_ocb_header", "decrypt",
    "dnu_reading", "encode", "encode_frame", "encrypt", "frame_crc", "iv", "parse", "scan",
    "to_frame",
]

# (message type TF002, subtype TF007) to its table.
MESSAGES: dict[tuple[int, int], type] = {
    (cls.MESSAGE_TYPE, subtype): cls for cls in (Ocb, Hpac, Gad, Bpac) for subtype in cls.SUBTYPES
}

# Seconds in the half day of the 16-bit time tag (TF009: 0 to 43,199).
HALF_DAY = 43_200



class Unsupported(Error, LookupError):
    """The frame holds a message this codec has no table for."""


class Encrypted(Error):
    """The operation needs the plain text of an encrypted frame, or the reverse."""


class FieldError(Error, BitError):
    """The payload does not fit its table (too short, or a value that does not fit)."""


class TimeTagError(Error):
    """A 32-bit time tag is missing, out of range, or contradicts the frame's own tag."""


class NoFrame(Error, TypeError):
    """A function that needs a :class:`Frame` was given what :func:`parse` returns without one."""


@dataclass(frozen=True, slots=True)
class Message:
    """A decoded frame: its transport fields and the message table in ``body``.

    ``body`` is an :class:`Ocb`, :class:`Hpac`, :class:`Gad` or
    :class:`Bpac`, the payload TF016 in plain text. ``auth`` is TF017, kept
    as bytes. With ``eaf`` 1 the message came from a decrypted frame and
    must be encrypted again to go on the wire (:func:`encrypt`).
    """

    message_type: int          # TF002
    eaf: int                   # TF004
    crc_type: int              # TF005
    description: Description   # TF007 to TF015
    body: Any                  # TF016, decoded
    auth: bytes = b""          # TF017


def _frame(frame: Any) -> Frame:
    if isinstance(frame, (NeedMore, Invalid)):
        raise NoFrame(f"a Frame is needed; parse found none: {frame!r}")
    if not isinstance(frame, Frame):
        raise NoFrame(f"a Frame is needed, not {type(frame).__qualname__}")
    return frame


def dnu_reading(body: Any) -> int:
    """The layout of a do-not-use satellite that an :class:`Ocb` was read or is written with.

    :data:`DNU_TABLE_8_2` if a satellite with DNU set has its SF014 and
    SF015 (``present`` is not ``None``), else :data:`DNU_TABLE_6_2`
    (``_messages.OcbSatellite``).
    """
    if isinstance(body, Ocb) and any(s.dnu and s.present is not None for s in body.satellites):
        return DNU_TABLE_8_2
    return DNU_TABLE_6_2


def _params(cls: type, subtype: int, body: Any = None) -> dict[str, int]:
    params = {"subtype": subtype} if "subtype" in cls.PARAMS else {}
    if "dnu_reading" in cls.PARAMS:
        params["dnu_reading"] = dnu_reading(body)
    return params


def _plain(frame: Any) -> Frame:
    frame = _frame(frame)
    if frame.eaf and not frame.decrypted:
        raise Encrypted("the payload is encrypted: decrypt(frame, key) first")
    return frame


def decode(frame: Frame, *, strict: bool = False) -> Message:
    """The message in ``frame``.

    Data after the message's table is kept in the body's ``extension``
    (``None`` when there is nothing but zero fill bits), as section 8.4
    item 4 asks ("decoder implementations should not use payload length to
    indicate where they stop decoding"); ``encode`` writes it back. With
    ``strict`` such a payload raises :class:`FieldError` instead.

    An OCB payload is read with the DNU layout of Table 6.2
    (``_messages.OcbSatellite``). If that reading fails or leaves data over,
    and the reading of Table 8.2 fits the payload exactly with at least one
    DNU satellite, that reading is returned instead (unless ``strict``): its
    DNU satellites carry ``present`` and ``continuity``, and
    :func:`dnu_reading` reports it.

    Raises :class:`Encrypted` for an encrypted frame that has not been
    through :func:`decrypt`, :class:`Unsupported` for a type and subtype
    without a table, :class:`FieldError` when the payload is shorter than
    its table, and :class:`NoFrame` for a :class:`NeedMore` or
    :class:`Invalid`.
    """
    frame = _plain(frame)
    subtype = frame.description.subtype
    cls = MESSAGES.get((frame.message_type, subtype))
    if cls is None:
        raise Unsupported(f"no table for SM {frame.message_type}-{subtype}")
    params = _params(cls, subtype)
    try:
        body, error = unpack(cls, frame.payload, strict=strict, **params), None
    except BitError as exc:
        body, error = None, exc
    if cls is Ocb and not strict and (body is None or body.extension is not None):
        params["dnu_reading"] = DNU_TABLE_8_2
        try:
            other = unpack(cls, frame.payload, strict=True, **params)
        except BitError:
            other = None
        if other is not None and any(s.dnu for s in other.satellites):
            body, error = other, None
    if error is not None:
        raise FieldError(*error.args) from None
    return Message(frame.message_type, frame.eaf, frame.crc_type, frame.description, body,
                   frame.auth)


def decode_ocb_header(frame: Frame) -> OcbHeader:
    """The header block of an OCB message (SM 0-x) of any subtype, without its satellites.

    Section 8.4 item 5 asks decoders to read SF010, the end-of-set flag, in
    every SM 0 message, "even though they may not understand the data";
    :class:`OcbHeader` says which rows a subtype without a table has.
    Raises :class:`Unsupported` for a message type other than 0,
    :class:`Encrypted` for a payload still encrypted and :class:`FieldError`
    for a payload shorter than the header.
    """
    frame = _plain(frame)
    if frame.message_type != Ocb.MESSAGE_TYPE:
        raise Unsupported(f"SM {frame.message_type}-{frame.description.subtype} is not an OCB "
                          f"message (type 0)")
    try:
        return read(OcbHeader, BitReader(frame.payload), subtype=frame.description.subtype)
    except BitError as exc:
        raise FieldError(*exc.args) from None


def to_frame(message: Message) -> Frame:
    """The frame of ``message``, payload in plain text (``decrypted`` when ``eaf`` is 1)."""
    cls = type(message.body)
    subtype = message.description.subtype
    if MESSAGES.get((message.message_type, subtype)) is not cls:
        raise TypeError(f"{cls.__qualname__} is not the table of SM "
                        f"{message.message_type}-{subtype}")
    try:
        payload = pack(message.body, **_params(cls, subtype, message.body))
    except BitError as exc:
        raise FieldError(*exc.args) from None
    if len(payload) > MAX_PAYLOAD:
        raise FieldError(f"payload of {len(payload)} bytes exceeds the 10-bit TF003")
    frame = Frame(0, 0, message.message_type, message.eaf, message.crc_type, message.description,
                  payload, message.auth, decrypted=bool(message.eaf))
    try:
        raw = encode_frame(frame.message_type, frame.eaf, frame.crc_type, frame.description,
                           frame.payload, frame.auth)
    except ValueError as exc:
        raise FieldError(*exc.args) from None
    return replace(frame, length=len(raw))


def encode(message: Message | Frame) -> bytes:
    """``message`` as a complete frame; a :class:`Frame` gives back its own bytes.

    A message or frame whose payload is plain text but whose EAF is set
    raises :class:`Encrypted`: pass it through :func:`encrypt` first.
    """
    frame = to_frame(message) if isinstance(message, Message) else message
    if not isinstance(frame, Frame):
        raise TypeError(f"{type(message).__qualname__} is not a message this codec encodes")
    if frame.decrypted:
        raise Encrypted("the payload is plain text but EAF is set: encrypt(frame, key) first")
    return encode_frame(frame.message_type, frame.eaf, frame.crc_type, frame.description,
                        frame.payload, frame.auth)


def iv(frame: Frame, time_tag: int | None = None) -> bytes:
    """The 96 fixed bits of the AES-CTR counter block, section 8.15.1, as 12 bytes.

    From the left: TF002 (7 bits), TF003 (10), TF007 (4), the 32-bit time
    tag TF009, TF010 (7), TF011 (4), TF012 (4), TF013 (6), then zeros. The
    counter block is these bits followed by a 32-bit counter starting at one
    (RFC 3686 section 2.1).

    A frame with a 32-bit time tag uses its own, and ``time_tag``, if given,
    must equal it. A frame with the 16-bit half-day tag needs ``time_tag``:
    the full 32-bit tag, which the caller resolves from another frame or
    source (TF009: "The half-day must be resolved with the assistance of an
    unambiguous time tag"); section 8.15.1 says the 16-bit form "must be
    expanded to 32-bit form". The full tag counts seconds from 2010-01-01
    00:00:00 (TF009), a half-day boundary, and the 16-bit one the seconds
    of the half day (0 to 43,199), so a full tag whose remainder by
    :data:`HALF_DAY` is not the frame's tag contradicts it and raises
    :class:`TimeTagError`, as does a tag outside 32 bits. That check cannot
    catch a full tag off by whole half days.

    Tags are in the system time of the message's constellation (TF009:
    "GPS message time tags are in GPS system time, while GLONASS message
    time tags are in GLONASS system time"), so a GLONASS frame's tag must
    be expanded from a GLONASS full tag, not from a GPS one: the two differ
    by hours and leap seconds.
    """
    frame = _frame(frame)
    if not frame.eaf:
        raise Encrypted("the frame is not encrypted (EAF is 0)")
    d = frame.description
    if time_tag is not None and (not isinstance(time_tag, int) or isinstance(time_tag, bool)
                                 or not 0 <= time_tag < 1 << 32):
        raise TimeTagError(f"time_tag {time_tag!r} is not a 32-bit unsigned integer")
    if d.time_tag_type == 1:
        if time_tag is not None and time_tag != d.time_tag:
            raise TimeTagError(f"time_tag {time_tag} differs from the frame's 32-bit tag "
                               f"{d.time_tag}")
        time_tag = d.time_tag
    elif time_tag is None:
        raise TimeTagError("the frame carries a 16-bit time tag: supply the full 32-bit time_tag")
    elif time_tag % HALF_DAY != d.time_tag:
        raise TimeTagError(f"time_tag {time_tag} is {time_tag % HALF_DAY} s into its half day, "
                           f"but the frame's 16-bit tag is {d.time_tag}")
    w = BitWriter()
    try:
        for value, bits in ((frame.message_type, 7), (len(frame.payload), 10), (d.subtype, 4),
                            (time_tag, 32), (d.solution_id, 7), (d.processor_id, 4),
                            (d.encryption_id, 4), (d.sequence, 6)):
            w.uint(value, bits)
    except BitError as exc:
        raise FieldError(f"initialisation vector: {exc}") from None
    w.uint(0, 96 - 74)
    return w.to_bytes()


def _no_dynamic_key(frame: Frame) -> None:
    # Section 6.5.5: SM 4-0 sends its first 24 bits in plain text even when encrypted.
    if frame.message_type == 4 and frame.description.subtype == 0:
        raise Unsupported("SM 4-0 (dynamic key) is partly plain text; not supported")


def decrypt(frame: Frame, key: bytes, time_tag: int | None = None) -> Frame:
    """``frame`` with its payload decrypted by AES-128-CTR under ``key`` (section 8.15).

    ``time_tag`` is the full 32-bit time tag, needed when the frame carries
    the 16-bit one, and checked against it (:func:`iv`). The result has
    ``decrypted`` set; the CRC and embedded authentication data are those of
    the encrypted frame and are not rechecked.
    """
    frame = _frame(frame)
    if frame.decrypted:
        raise Encrypted("the frame is already decrypted")
    _no_dynamic_key(frame)
    plain = ctr(bytes(key), iv(frame, time_tag), frame.payload)
    return replace(frame, payload=plain, decrypted=True)


def encrypt(frame: Frame, key: bytes, time_tag: int | None = None) -> Frame:
    """The inverse of :func:`decrypt`: a frame whose payload is the cipher text again."""
    frame = _frame(frame)
    if not frame.decrypted:
        raise Encrypted("the frame's payload is not plain text")
    _no_dynamic_key(frame)
    cipher = ctr(bytes(key), iv(frame, time_tag), frame.payload)
    return replace(frame, payload=cipher, decrypted=False)
