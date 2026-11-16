"""u-blox UBX codec: bytes to integer fields and back.

Message fields are integers exactly as they appear on the wire.

The interface is the same in every gnsswire codec (tests/test_layout.py):

- ``parse(buf, offset)`` answers one question, "is there a valid frame at this
  offset", and never searches. Resynchronisation policy belongs to the caller.
- ``scan(buf, offset)`` is the plain policy most callers want: yield every
  valid frame, skipping one byte after anything invalid.
- ``decode(frame)`` and ``encode(message)`` map a frame to a frozen dataclass
  of raw fields and back, losslessly.

Framing is in ``_frame`` (u-blox F9 HPG 1.51 Interface Description, sections
3.2 and 3.4; the u-blox X20 HPG 2.11 Interface Description prints the same). The payload table interpreter is in ``_table`` (section 3.3) and
the message tables in ``_messages``: RXM-PMP versions 0 (from the u-blox D9
PMP 1.04 description) and 1, RXM-RAWX version 1, RXM-SFRBX version 2 and
NAV-TIMELS version 0.
:func:`decode` picks the table by class, ID and version byte, and refuses a
version no table describes.

``encode`` accepts a message dataclass, or a :class:`Frame` (returning its
bytes); :func:`encode_frame` frames a payload given as bytes. Every function
taking bytes takes any bytes-like object.

Errors: every exception this codec raises for data it cannot decode or a
message it cannot encode is an :class:`Error` (a ``ValueError``):
:class:`Unsupported`, :class:`FieldError` and :class:`NoFrame`.
"""

from typing import Any

from ._frame import (
    MAX_PAYLOAD,
    SYNC,
    Error,
    Frame,
    Invalid,
    NeedMore,
    checksum,
    encode_frame,
    parse,
    scan,
)
from ._messages import NavTimels, RxmPmp, RxmPmpV0, RxmRawx, RxmRawxMeas, RxmSfrbx
from ._table import FieldError, layout, pack, unpack

__all__ = ["MAX_PAYLOAD", "MESSAGES", "SYNC", "Error", "FieldError", "Frame", "Invalid",
           "NavTimels", "NeedMore", "NoFrame", "RxmPmp", "RxmPmpV0", "RxmRawx", "RxmRawxMeas",
           "RxmSfrbx", "Unsupported", "checksum", "decode", "encode", "encode_frame", "layout",
           "parse", "scan"]

# (class, ID, version) to its table.
MESSAGES: dict[tuple[int, int, int], type] = {
    (cls.MSG_CLASS, cls.MSG_ID, cls.VERSION): cls
    for cls in (RxmPmp, RxmPmpV0, RxmRawx, RxmSfrbx, NavTimels)
}


class Unsupported(Error, LookupError):
    """The frame holds a message, or a message version, this codec has no table for."""


class NoFrame(Error, TypeError):
    """:func:`decode` was given something other than a :class:`Frame`, such as a
    :class:`NeedMore` or :class:`Invalid` from :func:`parse`."""


def decode(frame: Frame) -> Any:
    """The message in ``frame`` as its dataclass.

    Raises :class:`Unsupported` for a class and ID without a table, or a
    version byte no table has, :class:`FieldError` when the payload does
    not fit the table exactly, and :class:`NoFrame` for anything but a
    :class:`Frame`. All three are an :class:`Error` (a ``ValueError``).
    """
    if isinstance(frame, (NeedMore, Invalid)):
        raise NoFrame(f"decode needs a Frame; parse found none: {frame!r}")
    if not isinstance(frame, Frame):
        raise NoFrame(f"decode needs a Frame, not {type(frame).__qualname__}")
    key = (frame.msg_class, frame.msg_id)
    tables = {version: cls for (c, i, version), cls in MESSAGES.items() if (c, i) == key}
    if not tables:
        raise Unsupported(f"no table for class 0x{frame.msg_class:02x} ID 0x{frame.msg_id:02x}")
    # Every version of a message keeps its version byte at one offset.
    first = next(iter(tables.values()))
    at = layout(first).offsets["version"]
    if at >= len(frame.payload):
        return unpack(first, frame.payload)   # too short: FieldError
    cls = tables.get(frame.payload[at])
    if cls is None:
        raise Unsupported(f"{first.NAME} version {frame.payload[at]}: only version(s) "
                          f"{sorted(tables)} are in the specifications")
    return unpack(cls, frame.payload)


def encode(message: Any) -> bytes:
    """``message`` as a complete frame; a :class:`Frame` gives back its own bytes."""
    if isinstance(message, Frame):
        return encode_frame(message.msg_class, message.msg_id, message.payload)
    cls = type(message)
    key = (getattr(cls, "MSG_CLASS", None), getattr(cls, "MSG_ID", None),
           getattr(cls, "VERSION", None))
    if MESSAGES.get(key) is not cls:  # type: ignore[arg-type]
        raise TypeError(f"{cls.__qualname__} is not a message this codec encodes")
    if message.version != cls.VERSION:
        raise FieldError(f"{cls.NAME}: version {message.version!r}, the table is version "
                         f"{cls.VERSION}")
    return encode_frame(cls.MSG_CLASS, cls.MSG_ID, pack(message))
