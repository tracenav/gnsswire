"""RTCM 10403.x codec: bytes to integer fields and back.

Message fields are the standard's DF integers, unscaled.

The interface is the same in every gnsswire codec (tests/test_layout.py):

- ``parse(buf, offset)`` answers one question, "is there a valid frame at this
  offset", and never searches. Resynchronisation policy belongs to the caller.
- ``scan(buf, offset)`` is the plain policy most callers want: yield every
  valid frame, skipping one byte after anything invalid.
- ``decode(frame)`` and ``encode(message)`` map a frame to a frozen dataclass
  of raw fields and back, losslessly.

Framing is in ``_frame`` (RTCM 10403.3 section 4, Table 4-1); the message
tables are in ``_station`` (1005, 1006, 1007, 1008, 1033, 1230),
``_ephemeris`` (1019, 1020, 1042, 1044, 1045, 1046) and ``_msm`` (MSM1 to
MSM7 of GPS, GLONASS, Galileo, SBAS, QZSS and BeiDou: 1071 to 1127). Every
message table of chapter 3 begins with the message number DF002, uint12
(Table 3.4-1), and :func:`decode` reads it to pick the table.

``_igs`` holds the IGS SSR messages, RTCM proprietary message 4076 of the
International GNSS Service (IGS SSR v1.00): one message number with a
sub-type, IDF002, after it, which picks the table (:data:`IGS_MESSAGES`).
:data:`MESSAGES` maps message numbers with one table each and does not list
4076; :func:`decode` and :func:`encode` handle both.

``encode`` accepts a message dataclass, or a :class:`Frame` (returning its
bytes); :func:`encode_frame` frames a data message given as bytes.

Errors: every exception this codec raises for data it cannot decode or a
message it cannot encode is an :class:`Error` (a ``ValueError``):
:class:`Unsupported`, :class:`FieldError` (also a
``gnsswire.bits.BitError``) and :class:`NoFrame`.
"""

from typing import Any

from gnsswire.bits import BitError, pack, unpack

from ._ephemeris import Msg1019, Msg1020, Msg1042, Msg1044, Msg1045, Msg1046
from ._frame import (
    MAX_PAYLOAD,
    PREAMBLE,
    Error,
    Frame,
    Invalid,
    NeedMore,
    encode_frame,
    parse,
    scan,
)
from ._igs import (
    IGM_TYPES,
    IGS_MESSAGES,
    IGS_SATELLITES,
    IGS_SIGNALS,
    IGS_SSR,
    IGS_SUBTYPES,
    IGS_SYSTEMS,
    IGS_UPDATE_INTERVALS,
    IgsClock,
    IgsClockSat,
    IgsCodeBias,
    IgsCodeBiasSat,
    IgsCodeBiasSignal,
    IgsCombined,
    IgsCombinedSat,
    IgsHighRateClock,
    IgsHighRateClockSat,
    IgsOrbit,
    IgsOrbitSat,
    IgsPhaseBias,
    IgsPhaseBiasSat,
    IgsPhaseBiasSignal,
    IgsUra,
    IgsUraSat,
    IgsVtec,
    IgsVtecLayer,
    igs_subtype,
    update_interval,
)
from ._msm import MSM_TYPES, Msm
from ._station import Msg1005, Msg1006, Msg1007, Msg1008, Msg1033, Msg1230

__all__ = ["MAX_PAYLOAD", "MESSAGES", "MSM_TYPES", "PREAMBLE", "BitError", "Error", "FieldError",
           "Frame", "Invalid", "Msg1005", "Msg1006", "Msg1007", "Msg1008", "Msg1019", "Msg1020",
           "Msg1033", "Msg1042", "Msg1044", "Msg1045", "Msg1046", "Msg1230", "Msm", "NeedMore",
           "NoFrame", "Unsupported", "decode", "encode", "encode_frame", "message_number", "parse",
           "scan", "IGM_TYPES", "IGS_MESSAGES", "IGS_SATELLITES", "IGS_SIGNALS", "IGS_SSR", "IGS_SUBTYPES",
           "IGS_SYSTEMS", "IGS_UPDATE_INTERVALS", "IgsClock", "IgsClockSat", "IgsCodeBias",
           "IgsCodeBiasSat", "IgsCodeBiasSignal", "IgsCombined", "IgsCombinedSat",
           "IgsHighRateClock", "IgsHighRateClockSat", "IgsOrbit", "IgsOrbitSat", "IgsPhaseBias",
           "IgsPhaseBiasSat", "IgsPhaseBiasSignal", "IgsUra", "IgsUraSat", "IgsVtec",
           "IgsVtecLayer", "igs_subtype", "update_interval"]

# Message number (DF002) to its table; 4076 (IGS SSR) is looked up by
# sub-type in IGS_MESSAGES instead.
MESSAGES: dict[int, type] = {
    1005: Msg1005, 1006: Msg1006, 1007: Msg1007, 1008: Msg1008, 1019: Msg1019, 1020: Msg1020,
    1033: Msg1033, 1042: Msg1042, 1044: Msg1044, 1045: Msg1045, 1046: Msg1046, 1230: Msg1230,
    **{number: Msm for number in MSM_TYPES},
}


class Unsupported(Error, LookupError):
    """The frame holds a message this codec has no table for."""


class FieldError(Error, BitError):
    """The message does not fit its table (too short, or a value that does not fit)."""


class NoFrame(Error, TypeError):
    """:func:`decode` was given something other than a :class:`Frame`, such as a
    :class:`NeedMore` or :class:`Invalid` from :func:`parse`."""


def _frame(frame: Any) -> Frame:
    if isinstance(frame, (NeedMore, Invalid)):
        raise NoFrame(f"decode needs a Frame; parse found none: {frame!r}")
    if not isinstance(frame, Frame):
        raise NoFrame(f"decode needs a Frame, not {type(frame).__qualname__}")
    return frame


def message_number(frame: Frame) -> int | None:
    """DF002 of the frame's message, or ``None`` for a message shorter than 12 bits."""
    frame = _frame(frame)
    if len(frame.payload) < 2:
        return None
    return int.from_bytes(frame.payload[:2], "big") >> 4


def decode(frame: Frame, *, strict: bool = False) -> Any:
    """The message in ``frame`` as its dataclass.

    Data after the message's table is kept in its ``extension`` field
    (``None`` when there is nothing but zero fill bits), as RTCM 10403.3
    section 3.5.16.3.4 asks of a decoder ("shall skip ... shall be
    considered as normal"); ``encode`` writes it back. With ``strict`` such
    a message raises :class:`FieldError` instead.

    A message 4076 (IGS SSR) is decoded by the table of its sub-type,
    IDF002 (:data:`IGS_MESSAGES`).

    Raises :class:`Unsupported` for a message number (or IGS SSR sub-type)
    without a table, :class:`FieldError` when the message is shorter than
    its table, and :class:`NoFrame` for a :class:`NeedMore` or
    :class:`Invalid`.
    """
    number = message_number(frame)
    if number == IGS_SSR:
        subtype = igs_subtype(frame.payload)
        if subtype is None:
            raise FieldError(f"message {IGS_SSR} ends before its sub-type (IDF002)")
        cls = IGS_MESSAGES.get(subtype)
        if cls is None:
            raise Unsupported(f"no table for IGS SSR sub-type {subtype}")
    else:
        cls = MESSAGES.get(number) if number is not None else None
    if cls is None:
        raise Unsupported(f"no table for message {number}")
    try:
        return unpack(cls, frame.payload, strict=strict)
    except BitError as exc:
        raise FieldError(*exc.args) from None


def encode(message: Any) -> bytes:
    """``message`` as a complete frame; a :class:`Frame` gives back its own bytes.

    A message is framed with the reserved header bits at zero (``_frame``).
    """
    if isinstance(message, Frame):
        return encode_frame(message.payload, message.reserved)
    number = getattr(message, "number", None)
    if number == IGS_SSR:
        cls = IGS_MESSAGES.get(getattr(message, "subtype", None))
    else:
        cls = MESSAGES.get(number)
    if cls is not type(message):
        raise TypeError(f"{type(message).__qualname__} with number {number!r} "
                        f"is not a message this codec encodes")
    try:
        payload = pack(message)
    except BitError as exc:
        raise FieldError(*exc.args) from None
    if len(payload) > MAX_PAYLOAD:
        raise FieldError(f"message of {len(payload)} bytes exceeds the 10-bit length field")
    return encode_frame(payload)
