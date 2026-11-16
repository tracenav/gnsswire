"""SkyTraq binary protocol codec: bytes to integer fields and back.

Message fields are integers exactly as they appear on the wire.

The interface is the same in every gnsswire codec (tests/test_layout.py):

- ``parse(buf, offset)`` answers one question, "is there a valid frame at this
  offset", and never searches. Resynchronisation policy belongs to the caller.
- ``scan(buf, offset)`` is the plain policy most callers want: yield every
  valid frame, skipping one byte after anything invalid.
- ``decode(frame)`` and ``encode(message)`` map a frame to a frozen dataclass
  of raw fields and back, losslessly.

Framing is in ``_frame`` (SkyTraq AN0039 and AN0037, "Binary Message
Structure"), the table interpreter in ``_table`` and the message tables in
``_messages`` (AN0039): MEAS_TIME (0xDC), RAW_MEAS (0xDD), GPS SUBFRAME
(0xE0), GLONASS STRING (0xE1), BEIDOU2 D1 and D2 SUBFRAME (0xE2, 0xE3),
EXT_RAW_MEAS version 1 (0xE5) and GENERAL SUBFRAME version 1 (0xE6).
:func:`decode` picks the table by message ID, and for 0xE5 and 0xE6 refuses
a version no table describes.

``encode`` accepts a message dataclass, or a :class:`Frame` (returning its
bytes); :func:`encode_frame` frames a message body given as bytes. Every
function taking bytes takes any bytes-like object.

Errors: every exception this codec raises for data it cannot decode or a
message it cannot encode is an :class:`Error` (a ``ValueError``):
:class:`Unsupported`, :class:`FieldError` and :class:`NoFrame`.
"""

from typing import Any

from ._frame import (
    END,
    MAX_PAYLOAD,
    START,
    Error,
    Frame,
    Invalid,
    NeedMore,
    checksum,
    encode_frame,
    parse,
    scan,
)
from ._messages import (
    BeidouD1Subframe,
    BeidouD2Subframe,
    ExtRawMeas,
    ExtRawMeasChannel,
    GeneralSubframe,
    GlonassString,
    GpsSubframe,
    MeasTime,
    RawMeas,
    RawMeasChannel,
)
from ._table import FieldError, layout, pack, unpack

__all__ = ["END", "MAX_PAYLOAD", "MESSAGES", "START", "BeidouD1Subframe", "BeidouD2Subframe",
           "Error", "ExtRawMeas", "ExtRawMeasChannel", "FieldError", "Frame", "GeneralSubframe",
           "GlonassString", "GpsSubframe", "Invalid", "MeasTime", "NeedMore", "NoFrame", "RawMeas",
           "RawMeasChannel", "Unsupported", "checksum", "decode", "encode", "encode_frame",
           "layout", "parse", "scan"]

# Message ID to its table.
MESSAGES: dict[int, type] = {
    cls.MSG_ID: cls
    for cls in (MeasTime, RawMeas, GpsSubframe, GlonassString, BeidouD1Subframe,
                BeidouD2Subframe, ExtRawMeas, GeneralSubframe)
}


class Unsupported(Error, LookupError):
    """The frame holds a message, or a message version, this codec has no table for."""


class NoFrame(Error, TypeError):
    """:func:`decode` was given something other than a :class:`Frame`, such as a
    :class:`NeedMore` or :class:`Invalid` from :func:`parse`."""


def decode(frame: Frame) -> Any:
    """The message in ``frame`` as its dataclass.

    Raises :class:`Unsupported` for a message ID without a table, or a
    version byte no table has, :class:`FieldError` when the body does not
    fit the table exactly, and :class:`NoFrame` for anything but a
    :class:`Frame`. All three are an :class:`Error` (a ``ValueError``).
    """
    if isinstance(frame, (NeedMore, Invalid)):
        raise NoFrame(f"decode needs a Frame; parse found none: {frame!r}")
    if not isinstance(frame, Frame):
        raise NoFrame(f"decode needs a Frame, not {type(frame).__qualname__}")
    cls = MESSAGES.get(frame.msg_id)
    if cls is None:
        raise Unsupported(f"no table for message ID 0x{frame.msg_id:02x}")
    version = getattr(cls, "VERSION", None)
    if version is not None and frame.body[:1] and frame.body[0] != version:
        raise Unsupported(f"{cls.NAME} version {frame.body[0]}: only version {version} "
                          f"is in the application note")
    return unpack(cls, frame.body)


def encode(message: Any) -> bytes:
    """``message`` as a complete frame; a :class:`Frame` gives back its own bytes."""
    if isinstance(message, Frame):
        return encode_frame(message.msg_id, message.body)
    cls = type(message)
    if MESSAGES.get(getattr(cls, "MSG_ID", None)) is not cls:  # type: ignore[arg-type]
        raise TypeError(f"{cls.__qualname__} is not a message this codec encodes")
    version = getattr(cls, "VERSION", None)
    if version is not None and message.version != version:
        raise FieldError(f"{cls.NAME}: version {message.version!r}, the table is version "
                         f"{version}")
    return encode_frame(cls.MSG_ID, pack(message))
