"""Broadcast navigation messages as integer fields, and their ephemerides.

One module per system, each written from its interface control document:

- :mod:`gnsswire.nav.gps`: GPS LNAV subframes (IS-GPS-200N with IRN-IS-200N-003
  and IRN-IS-200N-004, 20.3);
- :mod:`gnsswire.nav.galileo`: Galileo I/NAV pages and words, F/NAV pages
  (Galileo OS SIS ICD issue 2.2, 4.2, 4.3 and 5.1);
- :mod:`gnsswire.nav.beidou`: BeiDou D1 and D2 subframes (BDS-SIS-ICD-B1I-3.0,
  5.1 to 5.3);
- :mod:`gnsswire.nav.glonass`: GLONASS strings (GLONASS ICD edition 5.1,
  4.3 to 4.5 and 4.7);

and :mod:`gnsswire.nav.carriers`, which takes these units out of
UBX-RXM-SFRBX and the SkyTraq subframe messages and puts them back.

A decoded unit is a frozen dataclass of the integers on the wire; parity,
BCH, Hamming and CRC codes are checked as each ICD defines them, and
encoding a decoded unit gives back its bits. Each system's ``Assembler``
yields an ``Ephemeris`` once every piece of one issue of data is present and
consistent; its fields carry the names and integer scales of the RTCM 3
ephemeris message of that system, and ``rtcm_fields`` gives the keyword
arguments of that message (``gnsswire.rtcm3``), with what the RTCM message
has that the broadcast message lacks filled as documented there.

Errors: every exception raised for data that cannot be decoded or a message
that cannot be encoded is an :class:`Error` (a ``ValueError``):
:class:`ParityError`, :class:`FieldError` and :class:`Unsupported`.
"""

from . import beidou, carriers, galileo, glonass, gps
from ._common import Error, FieldError, ParityError, Unsupported
from .carriers import Assembler, Received, from_sfrbx, from_skytraq

__all__ = [
    "Assembler",
    "Error",
    "FieldError",
    "ParityError",
    "Received",
    "Unsupported",
    "beidou",
    "carriers",
    "from_sfrbx",
    "from_skytraq",
    "galileo",
    "glonass",
    "gps",
]
