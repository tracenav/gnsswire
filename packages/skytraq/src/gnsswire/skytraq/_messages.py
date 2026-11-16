"""Message tables: raw measurements and navigation data bits.

Each class is the field table of SkyTraq AN0039 version 1.4.42 ("Binary
Messages Raw Measurement Data Extension of SkyTraq Phoenix GNSS Receiver")
cited in its docstring, row for row from field 2 (field 1 is the message
ID, which is :attr:`Frame.msg_id`); the string in each row is the note's
field name. Values are the raw integers: times in ms, ``SPFP`` and ``DPFP``
values as the bits of their IEEE 754 numbers (``_table``), navigation words
as the integers of their bytes.

Notes on the note:

- 0xDC prints the Receiver TOW as "4-8"; with the Receiver WN at 3-4 and
  TOW a UINT32 it is bytes 5-8, which the example frame confirms.
- 0xE2 and 0xE3 say the data bits are "the 26 higher bits of the word1 and
  the 22 higher bits of the word2 to word9", while the table goes on to word
  10; 28 bytes hold 26 + 9 · 22 = 224 bits, so word 10 is included. The 28
  bytes are kept as the table prints them, one UINT8 per row.
- 0xE6's example frame (valid checksum, PL 5 + 4 · 8) holds words
  06FFFFFF FF000000 12783589 E24D8000 86EE8000 0000002A AAAA664E 753F4000.
  The field table prints words 1 to 4 the same, then the frame's words 6 to
  8 as its words 5 to 7, and a word 8 (08D500C5) that is in no frame; the
  frame's word 5 (86EE8000) is not in the table. The layout, one 4-byte
  word per row, is the same in both readings; the tests take the frame.
  The frame is right: its eight words are a Galileo I/NAV page whose CRC
  checks, and the table's are not (gnsswire-nav, ``test_galileo.py``).
"""

from dataclasses import dataclass
from typing import Annotated, ClassVar

from ._table import BYTES3, BYTES4, DPFP, SPFP, UINT8, UINT16, UINT32, UNTYPED, Group


@dataclass(frozen=True, slots=True)
class MeasTime:
    """MEAS_TIME (0xDC), measurement time information. Payload length 10."""

    MSG_ID: ClassVar[int] = 0xDC
    NAME: ClassVar[str] = "MEAS_TIME"

    iod: Annotated[int, UINT8("IOD")]
    week: Annotated[int, UINT16("Receiver WN")]
    tow: Annotated[int, UINT32("Receiver TOW")]
    period: Annotated[int, UINT16("Measurement period")]


@dataclass(frozen=True, slots=True)
class RawMeasChannel:
    """One channel of RAW_MEAS (0xDD): fields 4 to 26, 23 bytes.

    ``svid`` is the PRN for GPS, slot + 64 for GLONASS, SVID + 200 for
    BeiDou and SVID + 240 for IRNSS. ``indicator`` bits 0 to 4: pseudorange,
    Doppler and carrier phase available, cycle slip possible, coherent
    integration of 10 ms or more.
    """

    svid: Annotated[int, UINT8("SVID")]
    cn0: Annotated[int, UINT8("CN0")]
    pseudorange: Annotated[int, DPFP("Pseudo-range")]
    carrier: Annotated[int, DPFP("Accumulated carrier cycle")]
    doppler: Annotated[int, SPFP("Doppler frequency")]
    indicator: Annotated[int, UINT8("Measurement Indicator")]


@dataclass(frozen=True, slots=True)
class RawMeas:
    """RAW_MEAS (0xDD), raw measurements from each channel. Payload length 3 + NMEAS · 23."""

    MSG_ID: ClassVar[int] = 0xDD
    NAME: ClassVar[str] = "RAW_MEAS"

    iod: Annotated[int, UINT8("IOD")]
    nmeas: Annotated[int, UINT8("NMEAS")]
    meas: Annotated[tuple[RawMeasChannel, ...], Group("Channel", RawMeasChannel, count="nmeas")]


@dataclass(frozen=True, slots=True)
class GpsSubframe:
    """GPS SUBFRAME (0xE0), GPS subframe buffer data. Payload length 33.

    ``words`` are the 24 parity-checked, polarity-adjusted data bits of words
    1 to 10 of the subframe (bit 1 the most significant), without parity.
    """

    MSG_ID: ClassVar[int] = 0xE0
    NAME: ClassVar[str] = "GPS SUBFRAME"

    svid: Annotated[int, UINT8("SVID")]
    sfid: Annotated[int, UINT8("SFID")]
    words: Annotated[tuple[int, ...], BYTES3("WORD", count=10)]


@dataclass(frozen=True, slots=True)
class GlonassString:
    """GLONASS STRING (0xE1), GLONASS string buffer data. Payload length 12.

    ``data`` holds bits 80 to 9 of the string, eight to a byte from bit 80,
    relative bi-binary, Hamming-checked, polarity-adjusted; the Hamming bits
    8 to 1 are not sent. ``svid`` is the slot number + 64.
    """

    MSG_ID: ClassVar[int] = 0xE1
    NAME: ClassVar[str] = "GLONASS STRING"

    svid: Annotated[int, UINT8("SVID")]
    string: Annotated[int, UINT8("String Number")]
    data: Annotated[tuple[int, ...], UINT8("Bit 80-73", count=9)]


@dataclass(frozen=True, slots=True)
class BeidouD1Subframe:
    """BEIDOU2 D1 SUBFRAME (0xE2). Payload length 31.

    ``data`` is 28 bytes: the 26 data bits of word 1, then the 22 of each of
    words 2 to 10, packed from the most significant bit, without parity.
    ``svid`` is SVID + 200.
    """

    MSG_ID: ClassVar[int] = 0xE2
    NAME: ClassVar[str] = "BEIDOU2 D1 SUBFRAME"

    svid: Annotated[int, UINT8("SVID")]
    sfid: Annotated[int, UINT8("SFID")]
    data: Annotated[tuple[int, ...], UINT8("WORD 1 bit01~ bit08", count=28)]


@dataclass(frozen=True, slots=True)
class BeidouD2Subframe:
    """BEIDOU2 D2 SUBFRAME (0xE3). Payload length 31; the layout of 0xE2."""

    MSG_ID: ClassVar[int] = 0xE3
    NAME: ClassVar[str] = "BEIDOU2 D2 SUBFRAME"

    svid: Annotated[int, UINT8("SVID")]
    sfid: Annotated[int, UINT8("SFID")]
    data: Annotated[tuple[int, ...], UINT8("WORD 1 bit01~ bit08", count=28)]


@dataclass(frozen=True, slots=True)
class ExtRawMeasChannel:
    """One channel of EXT_RAW_MEAS (0xE5): fields 15 to 45, 31 bytes.

    ``gnss_signal``: bits 0 to 3 the GNSS type (0 GPS, 1 SBAS, 2 GLONASS,
    3 Galileo, 4 QZSS, 5 BeiDou, 6 IRNSS), bits 4 to 7 the signal type.
    ``freq_lock``: bits 0 to 3 the GLONASS frequency ID (channel + 7), bits
    4 to 7 the lock time indicator (0 to 15). The three standard deviations
    are "not supported in version 1". ``indicator`` bits 0 to 5:
    pseudorange, Doppler and carrier phase available, cycle slip possible,
    coherent integration of 10 ms or more, unknown half-cycle ambiguity.
    """

    gnss_signal: Annotated[int, UNTYPED("GNSS type / Signal type", 1)]
    svid: Annotated[int, UINT8("SVID")]
    freq_lock: Annotated[int, UNTYPED("Frequency ID / Lock time indicator", 1)]
    cn0: Annotated[int, UINT8("CN0")]
    pseudorange: Annotated[int, DPFP("Pseudorange")]
    carrier: Annotated[int, DPFP("Accumulated carrier cycle")]
    doppler: Annotated[int, SPFP("Doppler frequency")]
    pseudorange_stdev: Annotated[int, UNTYPED("Pseudorange standard deviation", 1)]
    carrier_stdev: Annotated[int, UNTYPED("Accumulated carrier cycle standard deviation", 1)]
    doppler_stdev: Annotated[int, UNTYPED("Doppler frequency standard deviation", 1)]
    indicator: Annotated[int, UNTYPED("Channel Indicator", 2)]
    reserved2: Annotated[int, UNTYPED("Reserved 2", 2)]


@dataclass(frozen=True, slots=True)
class ExtRawMeas:
    """EXT_RAW_MEAS (0xE5), extended raw measurement data, version 1.

    Payload length 14 + NMEAS · 31. ``indicator`` (the measurement
    indicator) bits 0 to 2: triggered by geotagging, receiver clock adjusted
    by +1 ms, by -1 ms (both: several ms).
    """

    MSG_ID: ClassVar[int] = 0xE5
    NAME: ClassVar[str] = "EXT_RAW_MEAS"
    VERSION: ClassVar[int] = 1

    version: Annotated[int, UINT8("Version")]
    iod: Annotated[int, UINT8("IOD")]
    week: Annotated[int, UINT16("Receiver WN")]
    tow: Annotated[int, UINT32("Receiver TOW")]
    period: Annotated[int, UINT16("Measurement period")]
    indicator: Annotated[int, UNTYPED("Measurement indicator", 1)]
    reserved1: Annotated[int, UNTYPED("Reserved 1", 1)]
    nmeas: Annotated[int, UINT8("NMEAS")]
    meas: Annotated[tuple[ExtRawMeasChannel, ...],
                    Group("Channel", ExtRawMeasChannel, count="nmeas")]


@dataclass(frozen=True, slots=True)
class GeneralSubframe:
    """GENERAL SUBFRAME (0xE6), general subframe data, version 1.

    Payload length 5 + 4 · length. ``gnss_signal`` is coded as in
    :class:`ExtRawMeasChannel`. ``words`` are the navigation data in 32-bit
    words; for Galileo I/NAV the note maps the even and odd page parts onto
    words 1 to 4 and 5 to 8 (its "Remark").
    """

    MSG_ID: ClassVar[int] = 0xE6
    NAME: ClassVar[str] = "GENERAL SUBFRAME"
    VERSION: ClassVar[int] = 1

    version: Annotated[int, UINT8("Version")]
    gnss_signal: Annotated[int, UINT8("GNSS type / Signal type")]
    svid: Annotated[int, UINT8("SVID")]
    length: Annotated[int, UINT8("Length of navigation data")]
    words: Annotated[tuple[int, ...], BYTES4("WORD", count="length")]
