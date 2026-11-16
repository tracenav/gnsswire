"""NMEA 0183 codec: bytes to string fields and back.

Fields stay strings: this package never converts a number.

The interface is the same in every gnsswire codec (tests/test_layout.py):

- ``parse(buf, offset)`` answers one question, "is there a valid frame at this
  offset", and never searches. Resynchronisation policy belongs to the caller.
- ``scan(buf, offset)`` is the plain policy most callers want: yield every
  valid frame, skipping one byte after anything invalid.
- ``decode(frame)`` and ``encode(message)`` map a frame to a frozen dataclass
  of raw fields and back, losslessly.

Framing is in ``_frame`` (u-blox F9 HPG 1.51 Interface Description, section
2.1). The sentence tables are in ``_sentences``: GGA (section 2.7.5.1) and
ZDA (section 2.7.21.1), from any talker. :func:`decode` picks the table by
the address's sentence formatter.

``encode`` accepts a message dataclass, or a :class:`Frame` (returning its
bytes); :func:`encode_frame` frames a sentence body. Every function taking
bytes takes any bytes-like object.

Strictness: by default :func:`parse` and :func:`scan` accept lowercase
checksum digits and a bare LF line ending, and :func:`decode` a sentence
with fewer or more data fields than its table; ``strict=True`` accepts
only what the u-blox document prints (``_frame``, ``_sentences``). A frame
keeps its checksum case and line ending, so ``encode(frame)`` gives its
bytes back; ``encode(message)`` writes uppercase and CR LF.

Errors: every exception this codec raises for data it cannot decode or a
message it cannot encode is an :class:`Error` (a ``ValueError``):
:class:`Unsupported`, :class:`FieldError` and :class:`NoFrame`.
"""

from typing import Any

from ._frame import (
    CRLF,
    ENDINGS,
    MAX_LENGTH,
    Error,
    Frame,
    Invalid,
    NeedMore,
    encode_frame,
    parse,
    scan,
)
from ._sentences import SENTENCES, FieldError, Gga, Zda, is_talker, pack, spec_names, unpack

__all__ = ["CRLF", "ENDINGS", "MAX_LENGTH", "MESSAGES", "Error", "FieldError", "Frame", "Gga",
           "Invalid", "NeedMore", "NoFrame", "Unsupported", "Zda", "decode", "encode",
           "encode_frame", "parse", "scan", "spec_names"]

# Sentence formatter to its table.
MESSAGES: dict[str, type] = {cls.FORMATTER: cls for cls in SENTENCES}


class Unsupported(Error, LookupError):
    """The frame holds a sentence this codec has no table for."""


class NoFrame(Error, TypeError):
    """:func:`decode` was given something other than a :class:`Frame`, such as a
    :class:`NeedMore` or :class:`Invalid` from :func:`parse`."""


def decode(frame: Frame, *, strict: bool = False) -> Any:
    """The sentence in ``frame`` as its dataclass of strings.

    A sentence with fewer data fields than its table has the missing
    trailing fields ``None``; one with more keeps them in ``extra``
    (``_sentences``). With ``strict`` either raises :class:`FieldError`.

    Raises :class:`Unsupported` for an address that is not a two-letter
    talker ID followed by a formatter with a table (proprietary sentences
    such as ``PUBX`` included), :class:`FieldError` as above, and
    :class:`NoFrame` for anything but a :class:`Frame`.
    """
    if isinstance(frame, (NeedMore, Invalid)):
        raise NoFrame(f"decode needs a Frame; parse found none: {frame!r}")
    if not isinstance(frame, Frame):
        raise NoFrame(f"decode needs a Frame, not {type(frame).__qualname__}")
    # Framing admits printable ASCII only, so this cannot fail on a Frame.
    address, *values = frame.payload.decode("ascii").split(",")
    cls = MESSAGES.get(address[2:]) if len(address) == 5 else None
    if cls is None or not is_talker(address[:2]):
        raise Unsupported(f"no table for address {address!r}")
    return unpack(cls, address[:2], values, strict=strict)


def encode(message: Any) -> bytes:
    """``message`` as a complete sentence; a :class:`Frame` gives back its own bytes."""
    if isinstance(message, Frame):
        return encode_frame(message.payload, lower_hex=message.lower_hex,
                            ending=message.ending)
    cls = type(message)
    if MESSAGES.get(getattr(cls, "FORMATTER", None)) is not cls:
        raise TypeError(f"{cls.__qualname__} is not a sentence this codec encodes")
    try:
        return encode_frame(pack(message))
    except FieldError:
        raise
    except ValueError as e:   # longer than MAX_LENGTH
        raise FieldError(f"{cls.FORMATTER}: {e}") from None
