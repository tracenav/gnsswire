"""Bit-level I/O, CRCs and declarative field tables shared by the bit-packed codecs.

- :class:`BitReader` and :class:`BitWriter`: MSB-first unsigned, two's
  complement and sign-magnitude fields of up to 64 bits, and whole bytes at
  any alignment (``_io``); :data:`NEGATIVE_ZERO`, a sign-magnitude negative
  zero as read.
- :class:`Crc` and the CRCs RTCM 3 and SPARTN use, with their catalogue check
  values, and :class:`CrcSlices` for the CRCs of many slices of one buffer
  (``_crc``).
- Field tables: a frozen dataclass annotated with ``U``, ``S``, ``SM``,
  ``Mask``, ``Octets``, ``Group`` and ``Rest`` rows, read and written by :func:`read`,
  :func:`write`, :func:`pack` and :func:`unpack` (``_table``); a ``Rest``
  row keeps what follows a table as an :class:`Extension`.

Integers only; no protocol knowledge beyond the CRC parameters.
"""

from ._crc import (
    CRC4_SPARTN,
    CRC8_SMBUS,
    CRC16_IBM_3740,
    CRC16_XMODEM,
    CRC24_LTE_A,
    CRC24_OPENPGP,
    CRC24Q,
    CRC32_BZIP2,
    CRC32_ISO_HDLC,
    Crc,
    CrcSlices,
)
from ._io import MAX_WIDTH, NEGATIVE_ZERO, BitError, BitReader, BitWriter, Truncated
from ._table import (
    SM,
    Expr,
    Extension,
    F,
    Group,
    Kind,
    Layout,
    Mask,
    Octets,
    Rest,
    Row,
    S,
    U,
    layout,
    pack,
    popcount,
    read,
    unpack,
    write,
)

__all__ = [
    "CRC4_SPARTN", "CRC8_SMBUS", "CRC16_IBM_3740", "CRC16_XMODEM", "CRC24_LTE_A",
    "CRC24_OPENPGP", "CRC24Q", "CRC32_BZIP2", "CRC32_ISO_HDLC", "Crc", "CrcSlices",
    "MAX_WIDTH", "NEGATIVE_ZERO", "BitError", "BitReader", "BitWriter", "Truncated",
    "SM", "Expr", "Extension", "F", "Group", "Kind", "Layout", "Mask", "Octets", "Rest", "Row", "S",
    "U", "layout", "pack", "popcount", "read", "unpack", "write",
]
