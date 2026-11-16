"""Galileo I/NAV and F/NAV, from the Galileo OS SIS ICD issue 2.2 (November 2025).

I/NAV (E1-B and E5b-I, section 4.3). A nominal page is an even and an odd
page part of 120 bits each (Tables 37 and 38): even/odd bit, page type,
112 bits of data, 6 tail bits; then even/odd bit, page type, 16 bits of
data, 64 further bits (on E1-B OSNMA 40, SAR 22 and spare 2; on E5b-I
"Reserved 1", 64), the CRC (24), 8 bits (SSP on E1-B, "Reserved 2" on
E5b-I) and 6 tail bits. The CRC covers both parts' even/odd and page type
bits, both data fields and the 64 bits (196 bits, Table 38 notes), and is
CRC-24Q (section 5.1.9.4, Eq. 25: G(X) = (1 + X)P(X)). An alert page (page
type 1, Table 39) has the same bit positions and CRC coverage; its reserved
bits are kept in the same rows. :class:`InavPage` is the page;
:func:`decode_inav` checks its CRC.

The 128-bit I/NAV word of a nominal page is the 112 data bits of the even
part followed by the 16 of the odd part (Table 38, "Data field composed of a
nominal word"). Word types 0 to 6 and 10 have tables (section 4.3.5, Tables
42 to 47, 51 and 54); any other type decodes to :class:`InavOther`.

F/NAV (E5a-I, section 4.2). A page is the 244 bits after the
synchronisation pattern: page type (6), navigation data (208), CRC (24),
tail (6) (Table 28, section 4.2.2.3); the CRC, CRC-24Q again, covers the
page type and the navigation data. Page types 1 to 4 have tables (Tables
30 to 33) that span the whole page; any other type is :class:`FnavOther`.

Signed rows are those the parameter tables of chapter 5 mark with "*"
(two's complement): Tables 67 (ephemeris), 70 (clock), 72 (BGD), 74
(ionosphere), 75 (GST-UTC) and 76 (GST-GPS).

Row tags are the ICD's parameter names. Issue 2.2 names the signal health
status E5aSHS, E5bSHS and E1-BSHS (Tables 82 and 83), which issue 2.1 called
E5aHS, E5bHS and E1-BHS; the field names here (``e5a_hs`` and so on) keep
the issue 2.1 spelling, since renaming a field would break callers, and
the bits, their positions and their values (Table 84) are unchanged.

:class:`InavAssembler` and :class:`FnavAssembler` collect the words or
pages of one satellite and return an :class:`InavEphemeris` or
:class:`FnavEphemeris`, named and scaled as ``gnsswire.rtcm3.Msg1046`` and
``Msg1045`` (RTCM 10403.3 Tables 3.5-111 and 3.5-110 keep the ICD's widths
and scale factors).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

from gnsswire.bits import CRC24Q, S, U

from ._common import FieldError, ParityError, read_bits, write_bits

PART_BITS = 120
WORD_BITS = 128
FNAV_BITS = 244


def crc24q(value: int, nbits: int) -> int:
    """CRC-24Q of ``nbits`` bits; leading zero bits do not change it (initial value 0)."""
    return CRC24Q(value.to_bytes((nbits + 7) // 8, "big"))


# --- I/NAV pages -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class InavPage:
    """A nominal (or alert) I/NAV page: the even and the odd page part. Tables 38 and 39."""

    even: Annotated[int, U(1, "Even/odd = 0")]
    page_type: Annotated[int, U(1, "Page Type")]
    data_k: Annotated[int, U(56, "Data (1/2), bits 1-56")]
    data_k2: Annotated[int, U(56, "Data (1/2), bits 57-112")]
    tail: Annotated[int, U(6, "Tail")]
    odd: Annotated[int, U(1, "Even/odd = 1")]
    page_type_odd: Annotated[int, U(1, "Page Type")]
    data_j: Annotated[int, U(16, "Data (2/2)")]
    osnma: Annotated[int, U(40, "OSNMA (E1-B); Reserved 1 bits 1-40 (E5b-I)")]
    sar: Annotated[int, U(22, "SAR (E1-B); Reserved 1 bits 41-62 (E5b-I)")]
    spare: Annotated[int, U(2, "Spare (E1-B); Reserved 1 bits 63-64 (E5b-I)")]
    crc24: Annotated[int, U(24, "CRC")]
    ssp: Annotated[int, U(8, "SSP (E1-B); Reserved 2 (E5b-I)")]
    tail_odd: Annotated[int, U(6, "Tail")]

    @property
    def word(self) -> int:
        """The 128-bit word: data (1/2) then data (2/2)."""
        return (self.data_k << 56 | self.data_k2) << 16 | self.data_j

    def crc_input(self) -> int:
        """The 196 protected bits, in order: even part bits 1-114, odd part bits 1-82."""
        even = self.even << 113 | self.page_type << 112 | self.data_k << 56 | self.data_k2
        odd = (self.odd << 81 | self.page_type_odd << 80 | self.data_j << 64
               | self.osnma << 24 | self.sar << 2 | self.spare)
        return even << 82 | odd


def decode_inav(even: int, odd: int) -> InavPage:
    """The page of an even and an odd 120-bit page part; :class:`ParityError` on a CRC failure."""
    for part in (even, odd):
        if not isinstance(part, int) or not 0 <= part < 1 << PART_BITS:
            raise FieldError(f"a page part is 120 bits, got {part!r}")
    page = read_bits(InavPage, even << PART_BITS | odd, 2 * PART_BITS)
    if crc24q(page.crc_input(), 196) != page.crc24:
        raise ParityError(f"I/NAV CRC {page.crc24:06x}, section 5.1.9.4 gives "
                          f"{crc24q(page.crc_input(), 196):06x}")
    return page


def encode_inav(page: InavPage) -> tuple[int, int]:
    """The even and odd 120-bit page parts of ``page``, its fields as they are."""
    if type(page) is not InavPage:
        raise FieldError(f"expected an InavPage, got {type(page).__qualname__}")
    bits = write_bits(page)
    return bits >> PART_BITS, bits & ((1 << PART_BITS) - 1)


def inav_page(word: Any, *, osnma: int = 0, sar: int = 0, spare: int = 0, ssp: int = 0) -> InavPage:
    """A nominal page carrying ``word`` (a word table, or its 128-bit int), CRC computed."""
    bits = word if isinstance(word, int) else encode_inav_word(word)
    page = InavPage(even=0, page_type=0, data_k=bits >> 72, data_k2=(bits >> 16) & ((1 << 56) - 1),
                    tail=0, odd=1, page_type_odd=0, data_j=bits & 0xFFFF, osnma=osnma, sar=sar,
                    spare=spare, crc24=0, ssp=ssp, tail_odd=0)
    return dataclasses.replace(page, crc24=crc24q(page.crc_input(), 196))


# --- I/NAV words (section 4.3.5) ------------------------------------------------------

@dataclass(frozen=True, slots=True)
class InavWord1:
    """Word type 1: ephemeris (1/4). Table 42."""

    TYPE: ClassVar[int] = 1
    word_type: Annotated[int, U(6, "Type")]
    iodnav: Annotated[int, U(10, "IODnav")]
    toe: Annotated[int, U(14, "t0e")]
    m0: Annotated[int, S(32, "M0")]
    e: Annotated[int, U(32, "e")]
    sqrt_a: Annotated[int, U(32, "sqrt(A)")]
    reserved: Annotated[int, U(2, "Reserved")]


@dataclass(frozen=True, slots=True)
class InavWord2:
    """Word type 2: ephemeris (2/4). Table 43."""

    TYPE: ClassVar[int] = 2
    word_type: Annotated[int, U(6, "Type")]
    iodnav: Annotated[int, U(10, "IODnav")]
    omega0: Annotated[int, S(32, "OMEGA0")]
    i0: Annotated[int, S(32, "i0")]
    omega: Annotated[int, S(32, "omega")]
    idot: Annotated[int, S(14, "IDOT")]
    reserved: Annotated[int, U(2, "Reserved")]


@dataclass(frozen=True, slots=True)
class InavWord3:
    """Word type 3: ephemeris (3/4) and SISA(E1, E5b). Table 44."""

    TYPE: ClassVar[int] = 3
    word_type: Annotated[int, U(6, "Type")]
    iodnav: Annotated[int, U(10, "IODnav")]
    omega_dot: Annotated[int, S(24, "OMEGADOT")]
    delta_n: Annotated[int, S(16, "Delta n")]
    cuc: Annotated[int, S(16, "Cuc")]
    cus: Annotated[int, S(16, "Cus")]
    crc: Annotated[int, S(16, "Crc")]
    crs: Annotated[int, S(16, "Crs")]
    sisa: Annotated[int, U(8, "SISA(E1,E5b)")]


@dataclass(frozen=True, slots=True)
class InavWord4:
    """Word type 4: SVID, ephemeris (4/4) and clock correction. Table 45."""

    TYPE: ClassVar[int] = 4
    word_type: Annotated[int, U(6, "Type")]
    iodnav: Annotated[int, U(10, "IODnav")]
    svid: Annotated[int, U(6, "SVID")]
    cic: Annotated[int, S(16, "Cic")]
    cis: Annotated[int, S(16, "Cis")]
    toc: Annotated[int, U(14, "t0c")]
    af0: Annotated[int, S(31, "af0")]
    af1: Annotated[int, S(21, "af1")]
    af2: Annotated[int, S(6, "af2")]
    spare: Annotated[int, U(2, "Spare")]


@dataclass(frozen=True, slots=True)
class InavWord5:
    """Word type 5: ionosphere, BGD, signal health, data validity and GST. Table 46."""

    TYPE: ClassVar[int] = 5
    word_type: Annotated[int, U(6, "Type")]
    ai0: Annotated[int, U(11, "ai0")]
    ai1: Annotated[int, S(11, "ai1")]
    ai2: Annotated[int, S(14, "ai2")]
    region1: Annotated[int, U(1, "Ionospheric disturbance flag, region 1")]
    region2: Annotated[int, U(1, "Ionospheric disturbance flag, region 2")]
    region3: Annotated[int, U(1, "Ionospheric disturbance flag, region 3")]
    region4: Annotated[int, U(1, "Ionospheric disturbance flag, region 4")]
    region5: Annotated[int, U(1, "Ionospheric disturbance flag, region 5")]
    bgd_e5a_e1: Annotated[int, S(10, "BGD(E1,E5a)")]
    bgd_e5b_e1: Annotated[int, S(10, "BGD(E1,E5b)")]
    e5b_hs: Annotated[int, U(2, "E5bSHS")]
    e1b_hs: Annotated[int, U(2, "E1BSHS")]
    e5b_dvs: Annotated[int, U(1, "E5bDVS")]
    e1b_dvs: Annotated[int, U(1, "E1BDVS")]
    wn: Annotated[int, U(12, "WN")]
    tow: Annotated[int, U(20, "TOW")]
    spare: Annotated[int, U(23, "Spare")]


@dataclass(frozen=True, slots=True)
class InavWord6:
    """Word type 6: GST-UTC conversion. Table 47."""

    TYPE: ClassVar[int] = 6
    word_type: Annotated[int, U(6, "Type")]
    a0: Annotated[int, S(32, "A0")]
    a1: Annotated[int, S(24, "A1")]
    dt_ls: Annotated[int, S(8, "Delta tLS")]
    tot: Annotated[int, U(8, "tot")]
    wnot: Annotated[int, U(8, "WN0t")]
    wn_lsf: Annotated[int, U(8, "WNLSF")]
    dn: Annotated[int, U(3, "DN")]
    dt_lsf: Annotated[int, S(8, "Delta tLSF")]
    tow: Annotated[int, U(20, "TOW")]
    spare: Annotated[int, U(3, "Spare")]


@dataclass(frozen=True, slots=True)
class InavWord10:
    """Word type 10: almanac of SVID3 (2/2) and GST-GPS conversion. Table 51."""

    TYPE: ClassVar[int] = 10
    word_type: Annotated[int, U(6, "Type")]
    ioda: Annotated[int, U(4, "IODa")]
    omega0: Annotated[int, S(16, "OMEGA0")]
    omega_dot: Annotated[int, S(11, "OMEGADOT")]
    m0: Annotated[int, S(16, "M0")]
    af0: Annotated[int, S(16, "af0")]
    af1: Annotated[int, S(13, "af1")]
    e5b_hs: Annotated[int, U(2, "E5bSHS")]
    e1b_hs: Annotated[int, U(2, "E1BSHS")]
    a0g: Annotated[int, S(16, "A0G")]
    a1g: Annotated[int, S(12, "A1G")]
    t0g: Annotated[int, U(8, "t0G")]
    wn0g: Annotated[int, U(6, "WN0G")]


@dataclass(frozen=True, slots=True)
class InavWord0:
    """Word type 0: spare word with GST. Table 54 (WN and TOW valid when ``time`` is 2, '10')."""

    TYPE: ClassVar[int] = 0
    word_type: Annotated[int, U(6, "Type")]
    time: Annotated[int, U(2, "Time")]
    # 88 spare bits, kept as two rows (a bits row is at most 64 bits wide).
    spare: Annotated[int, U(44, "Spare, bits 9-52")]
    spare2: Annotated[int, U(44, "Spare, bits 53-96")]
    wn: Annotated[int, U(12, "WN")]
    tow: Annotated[int, U(20, "TOW")]


@dataclass(frozen=True, slots=True)
class InavOther:
    """A word type without a table here, kept whole.

    Section 4.3.5 also defines word types 7 to 9 (almanac, Tables 48 to 50),
    16 (reduced clock and ephemeris, Table 52), 17 to 20 (FEC2 Reed-Solomon,
    Table 53) and 22 (ARAIM integrity support message, Table 55); 63 is the
    dummy word (section 4.3.6, Table 57).
    """

    word_type: Annotated[int, U(6, "Type")]
    data: Annotated[int, U(61, "bits 7-67")]
    data2: Annotated[int, U(61, "bits 68-128")]


INAV_WORDS: dict[int, type] = {cls.TYPE: cls for cls in (
    InavWord0, InavWord1, InavWord2, InavWord3, InavWord4, InavWord5, InavWord6, InavWord10)}


def decode_inav_word(word: int) -> Any:
    """The table of a 128-bit I/NAV word, by its type (its first 6 bits)."""
    return read_bits(INAV_WORDS.get(word >> 122, InavOther), word, WORD_BITS)


def encode_inav_word(message: Any) -> int:
    if type(message) not in (*INAV_WORDS.values(), InavOther):
        raise FieldError(f"{type(message).__qualname__} is not an I/NAV word table")
    return write_bits(message)


def inav_word(page: InavPage) -> Any:
    """The word table of a nominal page; :class:`FieldError` for an alert page."""
    if page.page_type != 0 or page.page_type_odd != 0:
        raise FieldError("an alert page (page type 1) carries no nominal word")
    return decode_inav_word(page.word)


# --- F/NAV pages (section 4.2.4) -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FnavPage1:
    """Page type 1: SVID, clock, SISA, ionosphere, BGD, GST, health and validity. Table 30."""

    TYPE: ClassVar[int] = 1
    page_type: Annotated[int, U(6, "Type")]
    svid: Annotated[int, U(6, "SVID")]
    iodnav: Annotated[int, U(10, "IODnav")]
    toc: Annotated[int, U(14, "t0c")]
    af0: Annotated[int, S(31, "af0")]
    af1: Annotated[int, S(21, "af1")]
    af2: Annotated[int, S(6, "af2")]
    sisa: Annotated[int, U(8, "SISA(E1,E5a)")]
    ai0: Annotated[int, U(11, "ai0")]
    ai1: Annotated[int, S(11, "ai1")]
    ai2: Annotated[int, S(14, "ai2")]
    region1: Annotated[int, U(1, "Ionospheric disturbance flag, region 1")]
    region2: Annotated[int, U(1, "Ionospheric disturbance flag, region 2")]
    region3: Annotated[int, U(1, "Ionospheric disturbance flag, region 3")]
    region4: Annotated[int, U(1, "Ionospheric disturbance flag, region 4")]
    region5: Annotated[int, U(1, "Ionospheric disturbance flag, region 5")]
    bgd_e5a_e1: Annotated[int, S(10, "BGD(E1,E5a)")]
    e5a_hs: Annotated[int, U(2, "E5aSHS")]
    wn: Annotated[int, U(12, "WN")]
    tow: Annotated[int, U(20, "TOW")]
    e5a_dvs: Annotated[int, U(1, "E5aDVS")]
    spare: Annotated[int, U(26, "Spare")]
    crc24: Annotated[int, U(24, "CRC")]
    tail: Annotated[int, U(6, "Tail")]


@dataclass(frozen=True, slots=True)
class FnavPage2:
    """Page type 2: ephemeris (1/3) and GST. Table 31."""

    TYPE: ClassVar[int] = 2
    page_type: Annotated[int, U(6, "Type")]
    iodnav: Annotated[int, U(10, "IODnav")]
    m0: Annotated[int, S(32, "M0")]
    omega_dot: Annotated[int, S(24, "OMEGADOT")]
    e: Annotated[int, U(32, "e")]
    sqrt_a: Annotated[int, U(32, "sqrt(A)")]
    omega0: Annotated[int, S(32, "OMEGA0")]
    idot: Annotated[int, S(14, "IDOT")]
    wn: Annotated[int, U(12, "WN")]
    tow: Annotated[int, U(20, "TOW")]
    crc24: Annotated[int, U(24, "CRC")]
    tail: Annotated[int, U(6, "Tail")]


@dataclass(frozen=True, slots=True)
class FnavPage3:
    """Page type 3: ephemeris (2/3) and GST. Table 32."""

    TYPE: ClassVar[int] = 3
    page_type: Annotated[int, U(6, "Type")]
    iodnav: Annotated[int, U(10, "IODnav")]
    i0: Annotated[int, S(32, "i0")]
    omega: Annotated[int, S(32, "omega")]
    delta_n: Annotated[int, S(16, "Delta n")]
    cuc: Annotated[int, S(16, "Cuc")]
    cus: Annotated[int, S(16, "Cus")]
    crc: Annotated[int, S(16, "Crc")]
    crs: Annotated[int, S(16, "Crs")]
    toe: Annotated[int, U(14, "t0e")]
    wn: Annotated[int, U(12, "WN")]
    tow: Annotated[int, U(20, "TOW")]
    spare: Annotated[int, U(8, "Spare")]
    crc24: Annotated[int, U(24, "CRC")]
    tail: Annotated[int, U(6, "Tail")]


@dataclass(frozen=True, slots=True)
class FnavPage4:
    """Page type 4: ephemeris (3/3), GST-UTC and GST-GPS conversion, TOW. Table 33."""

    TYPE: ClassVar[int] = 4
    page_type: Annotated[int, U(6, "Type")]
    iodnav: Annotated[int, U(10, "IODnav")]
    cic: Annotated[int, S(16, "Cic")]
    cis: Annotated[int, S(16, "Cis")]
    a0: Annotated[int, S(32, "A0")]
    a1: Annotated[int, S(24, "A1")]
    dt_ls: Annotated[int, S(8, "Delta tLS")]
    tot: Annotated[int, U(8, "t0t")]
    wnot: Annotated[int, U(8, "WN0t")]
    wn_lsf: Annotated[int, U(8, "WNLSF")]
    dn: Annotated[int, U(3, "DN")]
    dt_lsf: Annotated[int, S(8, "Delta tLSF")]
    t0g: Annotated[int, U(8, "t0G")]
    a0g: Annotated[int, S(16, "A0G")]
    a1g: Annotated[int, S(12, "A1G")]
    wn0g: Annotated[int, U(6, "WN0G")]
    tow: Annotated[int, U(20, "TOW")]
    spare: Annotated[int, U(5, "Spare")]
    crc24: Annotated[int, U(24, "CRC")]
    tail: Annotated[int, U(6, "Tail")]


@dataclass(frozen=True, slots=True)
class FnavOther:
    """A page type without a table here, kept whole.

    Section 4.2.4 also defines page types 5 and 6 (almanac, Tables 34 and
    35); 63 is the dummy page (section 4.2.5, Table 36).
    """

    page_type: Annotated[int, U(6, "Type")]
    data: Annotated[int, U(64, "Navigation data bits 1-64")]
    data2: Annotated[int, U(64, "Navigation data bits 65-128")]
    data3: Annotated[int, U(64, "Navigation data bits 129-192")]
    data4: Annotated[int, U(16, "Navigation data bits 193-208")]
    crc24: Annotated[int, U(24, "CRC")]
    tail: Annotated[int, U(6, "Tail")]


FNAV_PAGES: dict[int, type] = {cls.TYPE: cls for cls in (FnavPage1, FnavPage2, FnavPage3,
                                                          FnavPage4)}


def decode_fnav(page: int) -> Any:
    """The table of a 244-bit F/NAV page; :class:`ParityError` on a CRC failure."""
    if not isinstance(page, int) or not 0 <= page < 1 << FNAV_BITS:
        raise FieldError(f"an F/NAV page is 244 bits, got {page!r}")
    protected, crc = page >> 30, (page >> 6) & 0xFFFFFF
    if crc24q(protected, 214) != crc:
        raise ParityError(f"F/NAV CRC {crc:06x}, section 5.1.9.4 gives "
                          f"{crc24q(protected, 214):06x}")
    return read_bits(FNAV_PAGES.get(page >> 238, FnavOther), page, FNAV_BITS)


def encode_fnav(message: Any) -> int:
    """The 244 bits of an F/NAV page table, its fields (CRC included) as they are."""
    if type(message) not in (*FNAV_PAGES.values(), FnavOther):
        raise FieldError(f"{type(message).__qualname__} is not an F/NAV page table")
    return write_bits(message)


def with_crc(message: Any) -> Any:
    """An F/NAV page table with its CRC computed from its other fields."""
    bits = encode_fnav(dataclasses.replace(message, crc24=0))
    return dataclasses.replace(message, crc24=crc24q(bits >> 30, 214))


# --- ephemerides ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class InavEphemeris:
    """One issue of a Galileo satellite's I/NAV clock and ephemeris: words 1 to 5.

    The fields are those of ``gnsswire.rtcm3.Msg1046`` (RTCM 10403.3 Table
    3.5-111), same names and integers, in the same order, without
    ``number``, ``reserved`` (DF001, which I/NAV does not have) and
    ``extension``. ``satellite`` is the SVID of word 4; ``week`` is the WN of
    word 5; ``e5b_validity`` and ``e1b_validity`` are its E5bDVS and E1BDVS,
    ``e5b_health`` and ``e1b_health`` its E5bSHS and E1BSHS. I/NAV words 5, 6
    and 10 hold more than 1046 has (ionosphere, GST-UTC and GST-GPS
    parameters, TOW); those stay in the word tables.
    """

    satellite: int
    week: int
    iodnav: int
    sisa: int
    idot: int
    toc: int
    af2: int
    af1: int
    af0: int
    crs: int
    delta_n: int
    m0: int
    cuc: int
    e: int
    cus: int
    sqrt_a: int
    toe: int
    cic: int
    omega0: int
    cis: int
    i0: int
    crc: int
    omega: int
    omega_dot: int
    bgd_e5a_e1: int
    bgd_e5b_e1: int
    e5b_health: int
    e5b_validity: int
    e1b_health: int
    e1b_validity: int


@dataclass(frozen=True, slots=True)
class FnavEphemeris:
    """One issue of a Galileo satellite's F/NAV clock and ephemeris: page types 1 to 4.

    The fields are those of ``gnsswire.rtcm3.Msg1045`` (RTCM 10403.3 Table
    3.5-110), same names and integers, in the same order, without
    ``number``, ``reserved`` (DF001) and ``extension``. ``satellite`` is the
    SVID of page type 1, ``week`` its WN; ``e5a_health`` and
    ``e5a_validity`` are its E5aSHS and E5aDVS.
    """

    satellite: int
    week: int
    iodnav: int
    sisa: int
    idot: int
    toc: int
    af2: int
    af1: int
    af0: int
    crs: int
    delta_n: int
    m0: int
    cuc: int
    e: int
    cus: int
    sqrt_a: int
    toe: int
    cic: int
    omega0: int
    cis: int
    i0: int
    crc: int
    omega: int
    omega_dot: int
    bgd_e5a_e1: int
    e5a_health: int
    e5a_validity: int


INAV_RTCM_NUMBER = 1046
FNAV_RTCM_NUMBER = 1045


def inav_ephemeris(w1: InavWord1, w2: InavWord2, w3: InavWord3, w4: InavWord4,
                   w5: InavWord5) -> InavEphemeris:
    if not w1.iodnav == w2.iodnav == w3.iodnav == w4.iodnav:
        raise FieldError(f"IODnav {w1.iodnav}, {w2.iodnav}, {w3.iodnav}, {w4.iodnav}: not one "
                         f"issue (section 5.1.9.2, Table 78)")
    return InavEphemeris(
        satellite=w4.svid, week=w5.wn, iodnav=w1.iodnav, sisa=w3.sisa, idot=w2.idot,
        toc=w4.toc, af2=w4.af2, af1=w4.af1, af0=w4.af0, crs=w3.crs, delta_n=w3.delta_n,
        m0=w1.m0, cuc=w3.cuc, e=w1.e, cus=w3.cus, sqrt_a=w1.sqrt_a, toe=w1.toe, cic=w4.cic,
        omega0=w2.omega0, cis=w4.cis, i0=w2.i0, crc=w3.crc, omega=w2.omega,
        omega_dot=w3.omega_dot, bgd_e5a_e1=w5.bgd_e5a_e1, bgd_e5b_e1=w5.bgd_e5b_e1,
        e5b_health=w5.e5b_hs, e5b_validity=w5.e5b_dvs, e1b_health=w5.e1b_hs,
        e1b_validity=w5.e1b_dvs)


def fnav_ephemeris(p1: FnavPage1, p2: FnavPage2, p3: FnavPage3, p4: FnavPage4) -> FnavEphemeris:
    if not p1.iodnav == p2.iodnav == p3.iodnav == p4.iodnav:
        raise FieldError(f"IODnav {p1.iodnav}, {p2.iodnav}, {p3.iodnav}, {p4.iodnav}: not one "
                         f"issue (section 5.1.9.2, Table 78)")
    return FnavEphemeris(
        satellite=p1.svid, week=p1.wn, iodnav=p1.iodnav, sisa=p1.sisa, idot=p2.idot,
        toc=p1.toc, af2=p1.af2, af1=p1.af1, af0=p1.af0, crs=p3.crs, delta_n=p3.delta_n,
        m0=p2.m0, cuc=p3.cuc, e=p2.e, cus=p3.cus, sqrt_a=p2.sqrt_a, toe=p3.toe, cic=p4.cic,
        omega0=p2.omega0, cis=p4.cis, i0=p3.i0, crc=p3.crc, omega=p3.omega,
        omega_dot=p2.omega_dot, bgd_e5a_e1=p1.bgd_e5a_e1, e5a_health=p1.e5a_hs,
        e5a_validity=p1.e5a_dvs)


def rtcm_fields(eph: InavEphemeris | FnavEphemeris) -> dict[str, int]:
    """Keyword arguments of ``Msg1046`` (I/NAV) or ``Msg1045`` (F/NAV), ``number`` included.

    ``reserved`` (DF001), which neither message carries over the air, is 0.
    """
    number = INAV_RTCM_NUMBER if isinstance(eph, InavEphemeris) else FNAV_RTCM_NUMBER
    fields = {f.name: getattr(eph, f.name) for f in dataclasses.fields(eph)}
    return {"number": number, **fields, "reserved": 0}


class InavAssembler:
    """Collects I/NAV words 1 to 5 per satellite; :meth:`push` returns each new complete issue.

    The latest word of each type is kept. Words 1 to 4 carry IODnav and
    must agree on it (the ICD's issue of data, section 5.1.9.2); word 5
    has none, so the latest word 5 received is taken. E1-B and E5b-I words
    of one satellite may be mixed: both carry the same words (section 4.3.1).
    """

    def __init__(self) -> None:
        self._parts: dict[Any, dict[int, Any]] = {}
        self._last: dict[Any, InavEphemeris] = {}

    def push(self, satellite: int, word: Any) -> InavEphemeris | None:
        if type(word) not in (InavWord1, InavWord2, InavWord3, InavWord4, InavWord5):
            return None
        parts = self._parts.setdefault(satellite, {})
        parts[word.TYPE] = word
        if len(parts) < 5:
            return None
        try:
            eph = inav_ephemeris(*(parts[t] for t in (1, 2, 3, 4, 5)))
        except FieldError:
            return None
        if self._last.get(satellite) == eph:
            return None
        self._last[satellite] = eph
        return eph


class FnavAssembler:
    """Collects F/NAV page types 1 to 4 per satellite; :meth:`push` returns each new issue.

    The latest page of each type is kept; the four must agree on IODnav.
    """

    def __init__(self) -> None:
        self._parts: dict[Any, dict[int, Any]] = {}
        self._last: dict[Any, FnavEphemeris] = {}

    def push(self, satellite: int, page: Any) -> FnavEphemeris | None:
        if type(page) not in FNAV_PAGES.values():
            return None
        parts = self._parts.setdefault(satellite, {})
        parts[page.TYPE] = page
        if len(parts) < 4:
            return None
        try:
            eph = fnav_ephemeris(*(parts[t] for t in (1, 2, 3, 4)))
        except FieldError:
            return None
        if self._last.get(satellite) == eph:
            return None
        self._last[satellite] = eph
        return eph
