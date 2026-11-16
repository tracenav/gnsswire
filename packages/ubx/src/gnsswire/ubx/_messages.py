"""Message tables: RXM-PMP, RXM-RAWX, RXM-SFRBX and NAV-TIMELS.

Each class is the "Payload description" table of the u-blox F9 HPG 1.51
Interface Description (UBXDOC-963802114-13124 R01, UBX protocol version
27.50) cited in its docstring, row for row and in byte-offset order; the
string in each row is the spec's field name. The exception is RXM-PMP
version 0, which is from the u-blox D9 PMP 1.04 Interface Description
(UBX-21040023 R01). The earlier F9 HPG 1.32 description (UBX-22008968 R01)
prints the same rows, types, offsets and version bytes under the same
section numbers, so frames from receivers that follow it decode alike.

The u-blox X20 HPG 2.11 Interface Description (UBXDOC-304424225-21617 R01,
UBX protocol version 50.11) prints every table here except RXM-PMP version 0
with the same rows, types, offsets and version byte (section cited in each
docstring); its machine-readable form, u-blox's JSON interface description
of the same release, agrees row for row. Where its text differs from the F9
document, the docstring says so. Values are the raw integers:
``ebno`` of RXM-PMP is in units of 2^-3 dB, ``iTOW`` of NAV-TIMELS in ms,
the ``R8`` and ``R4`` fields of RXM-RAWX the bits of their IEEE 754 numbers
(``_table``), and so on.

``VERSION`` is the value the table gives for its ``version`` field ("0x01 for
this version"). :func:`gnsswire.ubx.decode` picks the table by class, ID and
version byte, and refuses a version that no staged document prints.
"""

from dataclasses import dataclass
from typing import Annotated, ClassVar

from ._table import I1, I4, R4, R8, U1, U2, U4, X1, Bytes, Group


@dataclass(frozen=True, slots=True)
class RxmPmp:
    """UBX-RXM-PMP (0x02 0x72), PMP (L-band) message, version 1.

    Section 3.17.3.1, length 24 + numBytesUserData. The description gives
    numBytesUserData as 0 to 504; that is a range, not a width, and is not
    enforced. Version 0, which has a different layout, is :class:`RxmPmpV0`.
    The D9 PMP 1.04 description (section 2.13.1.2) prints this version with
    the same rows, and so does the X20 HPG 2.11 description (section
    3.16.3.1), which describes no other version and calls the message
    input/output rather than input.
    """

    MSG_CLASS: ClassVar[int] = 0x02
    MSG_ID: ClassVar[int] = 0x72
    NAME: ClassVar[str] = "RXM-PMP"
    VERSION: ClassVar[int] = 0x01

    version: Annotated[int, U1("version")]
    reserved0: Annotated[int, U1("reserved0")]
    num_bytes_user_data: Annotated[int, U2("numBytesUserData")]
    time_tag: Annotated[int, U4("timeTag")]
    unique_word: Annotated[tuple[int, ...], U4("uniqueWord", count=2)]
    service_identifier: Annotated[int, U2("serviceIdentifier")]
    spare: Annotated[int, U1("spare")]
    unique_word_bit_errors: Annotated[int, U1("uniqueWordBitErrors")]
    fec_bits: Annotated[int, U2("fecBits")]
    ebno: Annotated[int, U1("ebno")]
    reserved1: Annotated[int, U1("reserved1")]
    user_data: Annotated[bytes, Bytes("userData", length="num_bytes_user_data")]


@dataclass(frozen=True, slots=True)
class RxmPmpV0:
    """UBX-RXM-PMP (0x02 0x72), PMP (L-band) message, version 0.

    Not in the F9 HPG or X20 HPG documents: u-blox D9 PMP 1.04 Interface
    Description (UBX-21040023 R01), section 2.13.1.1, length 528. userData is a fixed
    U1[504] between uniqueWordBitErrors and fecBits; the version has no
    count of the bytes in use, so all 504 are kept.
    """

    MSG_CLASS: ClassVar[int] = 0x02
    MSG_ID: ClassVar[int] = 0x72
    NAME: ClassVar[str] = "RXM-PMP"
    VERSION: ClassVar[int] = 0x00

    version: Annotated[int, U1("version")]
    reserved0: Annotated[tuple[int, ...], U1("reserved0", count=3)]
    time_tag: Annotated[int, U4("timeTag")]
    unique_word: Annotated[tuple[int, ...], U4("uniqueWord", count=2)]
    service_identifier: Annotated[int, U2("serviceIdentifier")]
    spare: Annotated[int, U1("spare")]
    unique_word_bit_errors: Annotated[int, U1("uniqueWordBitErrors")]
    user_data: Annotated[bytes, Bytes("userData", length=504)]
    fec_bits: Annotated[int, U2("fecBits")]
    ebno: Annotated[int, U1("ebno")]
    reserved1: Annotated[int, U1("reserved1")]


@dataclass(frozen=True, slots=True)
class RxmSfrbx:
    """UBX-RXM-SFRBX (0x02 0x13), broadcast navigation data subframe, version 2.

    Section 3.17.9.1 (X20 HPG 2.11: section 3.16.8.1), length 8 + numWords·4.
    The data words are kept as the U4 integers on the wire; which bits of a
    word carry the navigation message depends on the signal (the GNSS's ICD,
    and the receiver description's section on broadcast navigation data) and
    is the caller's to interpret. numWords is "up to 16, for currently
    supported signals" (F9 HPG 1.51 and X20 HPG 2.11; F9 HPG 1.32 said "up
    to 10"), a range that is not enforced. sigId is kept as sent: F9 HPG
    1.51 section 1.5.4 (Table 4) lists more signals than F9 HPG 1.32 did
    (Galileo E6, BeiDou B3I, and the BeiDou B1C and B2a data components,
    sigId 6 and 8, with 5 and 7 now the pilots), and X20 HPG 2.11 (section
    1.5.4, Table 4) adds QZSS L1C/B.
    """

    MSG_CLASS: ClassVar[int] = 0x02
    MSG_ID: ClassVar[int] = 0x13
    NAME: ClassVar[str] = "RXM-SFRBX"
    VERSION: ClassVar[int] = 0x02

    gnss_id: Annotated[int, U1("gnssId")]
    sv_id: Annotated[int, U1("svId")]
    sig_id: Annotated[int, U1("sigId")]
    freq_id: Annotated[int, U1("freqId")]
    num_words: Annotated[int, U1("numWords")]
    chn: Annotated[int, U1("chn")]
    version: Annotated[int, U1("version")]
    reserved0: Annotated[int, U1("reserved0")]
    dwrd: Annotated[tuple[int, ...], U4("dwrd", count="num_words")]


@dataclass(frozen=True, slots=True)
class RxmRawxMeas:
    """One measurement of UBX-RXM-RAWX: the repeated group, offsets 16 + n·32 to 47 + n·32.

    ``pr_mes`` (m), ``cp_mes`` (cycles) and ``do_mes`` (Hz) are the bits of
    the R8, R8 and R4 numbers on the wire, as unsigned integers. The four
    ``X1`` bitfields are kept whole: bits 3…0 of ``pr_stdev``, ``cp_stdev``
    and ``do_stdev`` are prStd, cpStd and doStd (scales 0.01·2^n m, 0.004
    cycles and 0.002·2^n Hz); bits 0 to 3 of ``trk_stat`` are prValid,
    cpValid, halfCyc and subHalfCyc.
    """

    pr_mes: Annotated[int, R8("prMes")]
    cp_mes: Annotated[int, R8("cpMes")]
    do_mes: Annotated[int, R4("doMes")]
    gnss_id: Annotated[int, U1("gnssId")]
    sv_id: Annotated[int, U1("svId")]
    sig_id: Annotated[int, U1("sigId")]
    freq_id: Annotated[int, U1("freqId")]
    locktime: Annotated[int, U2("locktime")]
    cno: Annotated[int, U1("cno")]
    pr_stdev: Annotated[int, X1("prStdev")]
    cp_stdev: Annotated[int, X1("cpStdev")]
    do_stdev: Annotated[int, X1("doStdev")]
    trk_stat: Annotated[int, X1("trkStat")]
    reserved1: Annotated[int, U1("reserved1")]


@dataclass(frozen=True, slots=True)
class RxmRawx:
    """UBX-RXM-RAWX (0x02 0x15), multi-GNSS raw measurements, version 1.

    Section 3.17.6.1 (X20 HPG 2.11: section 3.16.6.1), length 16 + numMeas·32.
    ``rcv_tow`` is the bits of the R8 receiver time of week (s). ``rec_stat``
    is the X1 bitfield whole: bit 0 leapSec, bit 1 clkReset (the same two bits
    in both documents). Each measurement is a :class:`RxmRawxMeas`.

    The F9 section (1.51 as 1.32) says the only difference from "the
    previous version (UBX-RXM-RAWX-DATA0)" is the addition of the version
    field (the X20 section drops that sentence); that version's own table is in no staged
    document, so a version byte other than 1 is refused like any other
    unknown version (``Unsupported``).
    """

    MSG_CLASS: ClassVar[int] = 0x02
    MSG_ID: ClassVar[int] = 0x15
    NAME: ClassVar[str] = "RXM-RAWX"
    VERSION: ClassVar[int] = 0x01

    rcv_tow: Annotated[int, R8("rcvTow")]
    week: Annotated[int, U2("week")]
    leap_s: Annotated[int, I1("leapS")]
    num_meas: Annotated[int, U1("numMeas")]
    rec_stat: Annotated[int, X1("recStat")]
    version: Annotated[int, U1("version")]
    reserved0: Annotated[tuple[int, ...], U1("reserved0", count=2)]
    meas: Annotated[tuple[RxmRawxMeas, ...], Group("prMes", RxmRawxMeas, count="num_meas")]


@dataclass(frozen=True, slots=True)
class NavTimels:
    """UBX-NAV-TIMELS (0x01 0x26), leap second event information, version 0.

    Section 3.15.26.1 (X20 HPG 2.11: section 3.14.22.1), length 24. ``valid``
    is the X1 bitfield whole: bit 0 is validCurrLs and bit 1
    validTimeToLsEvent; the other bits are reserved (section 3.3.2) and kept.
    Both documents give the same values for srcOfCurrLs (0 to 8, 255) and
    srcOfLsChange (0, 2 to 7), and the same two notes (the 256-week
    ambiguity of past events, and that lsChange 0 is to be ignored), which
    F9 HPG 1.32 did not print; the notes change no field.
    """

    MSG_CLASS: ClassVar[int] = 0x01
    MSG_ID: ClassVar[int] = 0x26
    NAME: ClassVar[str] = "NAV-TIMELS"
    VERSION: ClassVar[int] = 0x00

    itow: Annotated[int, U4("iTOW")]
    version: Annotated[int, U1("version")]
    reserved0: Annotated[tuple[int, ...], U1("reserved0", count=3)]
    src_of_curr_ls: Annotated[int, U1("srcOfCurrLs")]
    curr_ls: Annotated[int, I1("currLs")]
    src_of_ls_change: Annotated[int, U1("srcOfLsChange")]
    ls_change: Annotated[int, I1("lsChange")]
    time_to_ls_event: Annotated[int, I4("timeToLsEvent")]
    date_of_ls_gps_wn: Annotated[int, U2("dateOfLsGpsWn")]
    date_of_ls_gps_dn: Annotated[int, U2("dateOfLsGpsDn")]
    reserved1: Annotated[tuple[int, ...], U1("reserved1", count=3)]
    valid: Annotated[int, X1("valid")]
