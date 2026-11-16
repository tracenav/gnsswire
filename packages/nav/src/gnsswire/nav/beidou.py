"""BeiDou D1 and D2 navigation messages of B1I, from BDS-SIS-ICD-B1I-3.0 (2019-02).

A subframe is ten 30-bit words (sections 5.2.2 and 5.3.1). Word 1 holds 26
information bits: the first 15 (preamble, Rev) are not encoded, the next
11 are one BCH(15,11,1) code word with its 4 parity bits at the end. Words
2 to 10 hold 22 information bits as two BCH(15,11,1) code words, the first
11 information bits being block 1, interleaved bit by bit: X1(1) X2(1)
X1(2) X2(2) ... X1(11) X2(11) P1(1) P2(1) ... P1(4) P2(4) (section 5.1.3).
The generator polynomial is g(X) = 1 + X + X^4. :func:`decode` takes the
ten transmitted words and checks every BCH code word (it does not correct
errors); :func:`encode` computes them.

A subframe's 224 information bits (26 + 9 * 22), the first received the
most significant, are what the field tables are over
(:func:`decode_data`, :func:`encode_data`); a parameter whose bits lie in
consecutive words (SOW, toc, a0, and so on) is one row.

D1 (MEO and IGSO satellites, section 5.2.3, Figures 5-8 to 5-11):
subframes 1 to 3 (:class:`D1Subframe1` to :class:`D1Subframe3`); of
subframe 5, page 7 and 8 (satellite health, :class:`Health1` and
:class:`Health2`) and page 10 (UTC, :class:`Utc`). D2 (GEO satellites,
section 5.3.2, Figures 5-14 and 5-18): pages 1 to 10 of subframe 1 (the
basic navigation information, in the 150 MSBs of the subframe; the other
150 bits are reserved and kept), and pages 35, 36 and 102 of subframe 5,
which have the layout of D1 subframe 5 pages 7, 8 and 10 (Figures 5-18-27,
5-18-28 and 5-18-31) and use the same classes. Anything else decodes to
:class:`Other`, its bits kept whole. Whether a subframe is D1 or D2 is not
in it: the carrier says (or the satellite: D2 is broadcast by the GEO
satellites, section 5.1.1).

Signed rows are those the parameter descriptions of section 5.2.4 give as
two's complement (TGD, alpha, beta, a0, a1, a2, the harmonic corrections,
delta n, M0, OMEGA0, OMEGADOT, i0, IDOT, omega, A0UTC, A1UTC, delta tLS,
delta tLSF).

:class:`Assembler` returns an :class:`Ephemeris` named and scaled as
``gnsswire.rtcm3.Msg1042`` (RTCM 10403.3 Table 3.5-113 keeps the ICD's
widths and scale factors) when the pieces of one issue are present: for
D1, subframes 1, 2 and 3 of one frame (SOW of subframes 2 and 3 equal to
that of subframe 1 plus 6 and 12 s, modulo a week: one frame lasts 30 s, a
subframe 6 s, section 5.2.2, and SOW counts at the leading edge of the
subframe's preamble, section 5.2.4.3); for D2, pages 1 to 10 of subframe 1
from ten consecutive frames (SOW of page k equal to that of page 1 plus
3(k - 1) s; a D2 frame lasts 3 s, section 5.3.1). The ICD gives no other rule tying the parts of one
issue together (AODE is in subframe 1 or page 4 only).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

from gnsswire.bits import S, U

from ._common import FieldError, ParityError, read_bits, write_bits

PREAMBLE = 0b11100010010   # 11 bits, section 5.2.4.1
DATA_BITS = 224
WEEK = 604_800   # seconds; SOW counts from 0 at the start of each BDT week (5.2.4.3)


def bch(info: int) -> int:
    """The 4 parity bits of an 11-bit information block: the remainder of info(X)·X^4 by g(X)."""
    reg = 0
    for i in range(10, -1, -1):
        feedback = ((info >> i) & 1) ^ (reg >> 3)
        reg = ((reg << 1) & 0xF) ^ (0b0011 if feedback else 0)
    return reg


def _interleave(a: int, b: int, n: int) -> int:
    out = 0
    for i in range(n - 1, -1, -1):
        out = out << 2 | ((a >> i) & 1) << 1 | ((b >> i) & 1)
    return out


def _deinterleave(v: int, n: int) -> tuple[int, int]:
    a = b = 0
    for i in range(n - 1, -1, -1):
        a = a << 1 | (v >> (2 * i + 1)) & 1
        b = b << 1 | (v >> (2 * i)) & 1
    return a, b


def words_from_data(data: int) -> tuple[int, ...]:
    """The ten transmitted words of 224 information bits, BCH encoded and interleaved."""
    first = data >> 198   # 26 bits
    words = [first << 4 | bch(first & 0x7FF)]
    for k in range(9):
        info = (data >> (22 * (8 - k))) & 0x3FFFFF
        a, b = info >> 11, info & 0x7FF
        words.append(_interleave(a, b, 11) << 8 | _interleave(bch(a), bch(b), 4))
    return tuple(words)


def data_from_words(words: Sequence[int]) -> int:
    """The 224 information bits of ten transmitted words; :class:`ParityError` on a BCH failure."""
    if len(words) != 10 or not all(isinstance(w, int) and 0 <= w < 1 << 30 for w in words):
        raise FieldError(f"a subframe is ten 30-bit words, got {words!r}")
    first = words[0] >> 4
    if bch(first & 0x7FF) != words[0] & 0xF:
        raise ParityError(f"word 1: BCH parity {words[0] & 0xF:04b}, section 5.1.3 gives "
                          f"{bch(first & 0x7FF):04b}")
    data = first
    for k, word in enumerate(words[1:], start=2):
        a, b = _deinterleave(word >> 8, 11)
        pa, pb = _deinterleave(word & 0xFF, 4)
        if (bch(a), bch(b)) != (pa, pb):
            raise ParityError(f"word {k}: BCH parity of blocks 1 and 2 {pa:04b} {pb:04b}, "
                              f"section 5.1.3 gives {bch(a):04b} {bch(b):04b}")
        data = data << 22 | a << 11 | b
    return data


# --- tables ------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Header:
    """Word 1 and the SOW LSBs of word 2, common to every subframe."""

    preamble: Annotated[int, U(11, "Pre")]
    rev: Annotated[int, U(4, "Rev")]
    fraid: Annotated[int, U(3, "FraID")]
    sow: Annotated[int, U(20, "SOW")]


@dataclass(frozen=True, slots=True)
class D1Subframe1(_Header):
    """D1 subframe 1: clock, health, accuracy, group delays, ionosphere. Figure 5-8."""

    FRAID: ClassVar[int] = 1

    sat_h1: Annotated[int, U(1, "SatH1")]
    aodc: Annotated[int, U(5, "AODC")]
    urai: Annotated[int, U(4, "URAI")]
    week: Annotated[int, U(13, "WN")]
    toc: Annotated[int, U(17, "toc")]
    tgd1: Annotated[int, S(10, "TGD1")]
    tgd2: Annotated[int, S(10, "TGD2")]
    alpha0: Annotated[int, S(8, "alpha0")]
    alpha1: Annotated[int, S(8, "alpha1")]
    alpha2: Annotated[int, S(8, "alpha2")]
    alpha3: Annotated[int, S(8, "alpha3")]
    beta0: Annotated[int, S(8, "beta0")]
    beta1: Annotated[int, S(8, "beta1")]
    beta2: Annotated[int, S(8, "beta2")]
    beta3: Annotated[int, S(8, "beta3")]
    a2: Annotated[int, S(11, "a2")]
    a0: Annotated[int, S(24, "a0")]
    a1: Annotated[int, S(22, "a1")]
    aode: Annotated[int, U(5, "AODE")]


@dataclass(frozen=True, slots=True)
class D1Subframe2(_Header):
    """D1 subframe 2: ephemeris, first part. Figure 5-9 (toe's 2 MSBs end the subframe)."""

    FRAID: ClassVar[int] = 2

    delta_n: Annotated[int, S(16, "Delta n")]
    cuc: Annotated[int, S(18, "Cuc")]
    m0: Annotated[int, S(32, "M0")]
    e: Annotated[int, U(32, "e")]
    cus: Annotated[int, S(18, "Cus")]
    crc: Annotated[int, S(18, "Crc")]
    crs: Annotated[int, S(18, "Crs")]
    sqrt_a: Annotated[int, U(32, "sqrt(A)")]
    toe_msb: Annotated[int, U(2, "toe, 2 MSBs")]


@dataclass(frozen=True, slots=True)
class D1Subframe3(_Header):
    """D1 subframe 3: ephemeris, second part. Figure 5-10 (toe's 15 LSBs open it)."""

    FRAID: ClassVar[int] = 3

    toe_lsb: Annotated[int, U(15, "toe, 15 LSBs")]
    i0: Annotated[int, S(32, "i0")]
    cic: Annotated[int, S(18, "Cic")]
    omega_dot: Annotated[int, S(24, "OMEGADOT")]
    cis: Annotated[int, S(18, "Cis")]
    idot: Annotated[int, S(14, "IDOT")]
    omega0: Annotated[int, S(32, "OMEGA0")]
    omega: Annotated[int, S(32, "omega")]
    rev2: Annotated[int, U(1, "Rev")]


@dataclass(frozen=True, slots=True)
class _Paged(_Header):
    rev2: Annotated[int, U(1, "Rev")]
    pnum: Annotated[int, U(7, "Pnum")]


@dataclass(frozen=True, slots=True)
class Health1(_Paged):
    """Health of satellites 1 to 19: D1 subframe 5 page 7 (Figure 5-11-2), D2 subframe 5
    page 35 (Figure 5-18-27)."""

    health: Annotated[tuple[int, ...], U(9, "Hea1-Hea19", count=19)]
    rev3: Annotated[int, U(7, "Rev")]


@dataclass(frozen=True, slots=True)
class Health2(_Paged):
    """Health of satellites 20 to 30, almanac week and reference time: D1 subframe 5 page 8
    (Figure 5-11-3), D2 subframe 5 page 36 (Figure 5-18-28)."""

    health: Annotated[tuple[int, ...], U(9, "Hea20-Hea30", count=11)]
    wna: Annotated[int, U(8, "WNa")]
    toa: Annotated[int, U(8, "toa")]
    rev3: Annotated[int, U(63, "Rev")]


@dataclass(frozen=True, slots=True)
class Utc(_Paged):
    """BDT-UTC parameters: D1 subframe 5 page 10 (Figure 5-11-5), D2 subframe 5 page 102
    (Figure 5-18-31)."""

    dt_ls: Annotated[int, S(8, "Delta tLS")]
    dt_lsf: Annotated[int, S(8, "Delta tLSF")]
    wn_lsf: Annotated[int, U(8, "WNLSF")]
    a0_utc: Annotated[int, S(32, "A0UTC")]
    a1_utc: Annotated[int, S(24, "A1UTC")]
    dn: Annotated[int, U(8, "DN")]
    # The 90 Rev bits run from bit 135 (the last 2 information bits of word 6) to the end;
    # kept per word, the bits interpreter's rows being at most 64 bits wide.
    rev3: Annotated[int, U(2, "Rev")]
    rev4: Annotated[tuple[int, ...], U(22, "Rev, words 7-10", count=4)]


@dataclass(frozen=True, slots=True)
class _D2Page(_Header):
    pnum: Annotated[int, U(4, "Pnum1")]


@dataclass(frozen=True, slots=True)
class D2Page1(_D2Page):
    """D2 subframe 1 page 1: health, clock reference, accuracy, week, group delays.
    Figure 5-14-1."""

    PNUM: ClassVar[int] = 1

    sat_h1: Annotated[int, U(1, "SatH1")]
    aodc: Annotated[int, U(5, "AODC")]
    urai: Annotated[int, U(4, "URAI")]
    week: Annotated[int, U(13, "WN")]
    toc: Annotated[int, U(17, "toc")]
    tgd1: Annotated[int, S(10, "TGD1")]
    tgd2: Annotated[int, S(10, "TGD2")]
    rev3: Annotated[int, U(12, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page2(_D2Page):
    """D2 subframe 1 page 2: ionosphere. Figure 5-14-2."""

    PNUM: ClassVar[int] = 2

    alpha0: Annotated[int, S(8, "alpha0")]
    alpha1: Annotated[int, S(8, "alpha1")]
    alpha2: Annotated[int, S(8, "alpha2")]
    alpha3: Annotated[int, S(8, "alpha3")]
    beta0: Annotated[int, S(8, "beta0")]
    beta1: Annotated[int, S(8, "beta1")]
    beta2: Annotated[int, S(8, "beta2")]
    beta3: Annotated[int, S(8, "beta3")]
    rev3: Annotated[int, U(8, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page3(_D2Page):
    """D2 subframe 1 page 3: a0 and the 4 MSBs of a1. Figure 5-14-3."""

    PNUM: ClassVar[int] = 3

    rev3: Annotated[int, U(6, "Rev")]
    rev4: Annotated[int, U(22, "Rev")]
    rev5: Annotated[int, U(10, "Rev")]
    a0: Annotated[int, S(24, "a0")]
    a1_msb: Annotated[int, U(4, "a1, 4 MSBs")]
    rev6: Annotated[int, U(6, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page4(_D2Page):
    """D2 subframe 1 page 4: a1 (18 LSBs), a2, AODE, delta n, Cuc (14 MSBs). Figure 5-14-4."""

    PNUM: ClassVar[int] = 4

    a1_lsb: Annotated[int, U(18, "a1, 18 LSBs")]
    a2: Annotated[int, S(11, "a2")]
    aode: Annotated[int, U(5, "AODE")]
    delta_n: Annotated[int, S(16, "Delta n")]
    cuc_msb: Annotated[int, U(14, "Cuc, 14 MSBs")]
    rev3: Annotated[int, U(8, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page5(_D2Page):
    """D2 subframe 1 page 5: Cuc (4 LSBs), M0, Cus, e (10 MSBs). Figure 5-14-5."""

    PNUM: ClassVar[int] = 5

    cuc_lsb: Annotated[int, U(4, "Cuc, 4 LSBs")]
    m0: Annotated[int, S(32, "M0")]
    cus: Annotated[int, S(18, "Cus")]
    e_msb: Annotated[int, U(10, "e, 10 MSBs")]
    rev3: Annotated[int, U(8, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page6(_D2Page):
    """D2 subframe 1 page 6: e (22 LSBs), sqrt(A), Cic (10 MSBs). Figure 5-14-6."""

    PNUM: ClassVar[int] = 6

    e_lsb: Annotated[int, U(22, "e, 22 LSBs")]
    sqrt_a: Annotated[int, U(32, "sqrt(A)")]
    cic_msb: Annotated[int, U(10, "Cic, 10 MSBs")]
    rev3: Annotated[int, U(8, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page7(_D2Page):
    """D2 subframe 1 page 7: Cic (8 LSBs), Cis, toe, i0 (21 MSBs). Figure 5-14-7."""

    PNUM: ClassVar[int] = 7

    cic_lsb: Annotated[int, U(8, "Cic, 8 LSBs")]
    cis: Annotated[int, S(18, "Cis")]
    toe: Annotated[int, U(17, "toe")]
    i0_msb: Annotated[int, U(21, "i0, 21 MSBs")]
    rev3: Annotated[int, U(8, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page8(_D2Page):
    """D2 subframe 1 page 8: i0 (11 LSBs), Crc, Crs, OMEGADOT (19 MSBs). Figure 5-14-8."""

    PNUM: ClassVar[int] = 8

    i0_lsb: Annotated[int, U(11, "i0, 11 LSBs")]
    crc: Annotated[int, S(18, "Crc")]
    crs: Annotated[int, S(18, "Crs")]
    omega_dot_msb: Annotated[int, U(19, "OMEGADOT, 19 MSBs")]
    rev3: Annotated[int, U(6, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page9(_D2Page):
    """D2 subframe 1 page 9: OMEGADOT (5 LSBs), OMEGA0, omega (27 MSBs). Figure 5-14-9."""

    PNUM: ClassVar[int] = 9

    omega_dot_lsb: Annotated[int, U(5, "OMEGADOT, 5 LSBs")]
    omega0: Annotated[int, S(32, "OMEGA0")]
    omega_msb: Annotated[int, U(27, "omega, 27 MSBs")]
    rev3: Annotated[int, U(8, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class D2Page10(_D2Page):
    """D2 subframe 1 page 10: omega (5 LSBs), IDOT. Figure 5-14-10."""

    PNUM: ClassVar[int] = 10

    omega_lsb: Annotated[int, U(5, "omega, 5 LSBs")]
    idot: Annotated[int, S(14, "IDOT")]
    rev3: Annotated[int, U(9, "Rev")]
    rev4: Annotated[int, U(22, "Rev")]
    rev5: Annotated[int, U(22, "Rev")]
    reserved: Annotated[tuple[int, ...], U(22, "Words 6-10, information bits, reserved", count=5)]


@dataclass(frozen=True, slots=True)
class Other(_Header):
    """A subframe or page without a table here: everything after SOW kept whole."""

    data: Annotated[int, U(62, "bits 39-100")]
    data2: Annotated[int, U(62, "bits 101-162")]
    data3: Annotated[int, U(62, "bits 163-224")]


D2_PAGES: dict[int, type] = {cls.PNUM: cls for cls in (
    D2Page1, D2Page2, D2Page3, D2Page4, D2Page5, D2Page6, D2Page7, D2Page8, D2Page9, D2Page10)}
D1_SUBFRAME5 = {7: Health1, 8: Health2, 10: Utc}
D2_SUBFRAME5 = {35: Health1, 36: Health2, 102: Utc}


def table(data: int, d2: bool) -> type:
    """The table of 224 information bits; ``d2`` for a D2 subframe."""
    fraid = (data >> (224 - 18)) & 7
    if fraid == 5:
        pnum = (data >> (224 - 46)) & 0x7F
        return (D2_SUBFRAME5 if d2 else D1_SUBFRAME5).get(pnum, Other)
    if d2:
        if fraid != 1:
            return Other
        return D2_PAGES.get((data >> (224 - 42)) & 0xF, Other)
    return {1: D1Subframe1, 2: D1Subframe2, 3: D1Subframe3}.get(fraid, Other)


def decode_data(data: int, *, d2: bool) -> Any:
    """The subframe of 224 information bits (the first received the most significant)."""
    return read_bits(table(data, d2), data, DATA_BITS)


def encode_data(message: Any) -> int:
    if type(message) not in TABLES:
        raise FieldError(f"{type(message).__qualname__} is not a BeiDou D1 or D2 table")
    return write_bits(message)


def decode(words: Sequence[int], *, d2: bool) -> Any:
    """The subframe of ten transmitted 30-bit words, every BCH code word checked."""
    return decode_data(data_from_words(words), d2=d2)


def encode(message: Any) -> tuple[int, ...]:
    """The ten transmitted words of ``message``, BCH encoded and interleaved."""
    return words_from_data(encode_data(message))


TABLES = (D1Subframe1, D1Subframe2, D1Subframe3, Health1, Health2, Utc, *D2_PAGES.values(),
          Other)


# --- ephemeris -------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Ephemeris:
    """One issue of a BeiDou satellite's clock and ephemeris, from D1 or D2.

    The fields are those of ``gnsswire.rtcm3.Msg1042`` (RTCM 10403.3 Table
    3.5-113), same names and integers, in the same order, without
    ``number`` and ``extension``. ``satellite`` is the PRN the carrier
    names; ``health`` is SatH1 (DF515, 1 bit); ``urai`` is URAI. A field
    split over pages of D2 is joined. D1 subframe 1 and D2 page 2 also hold
    the ionospheric parameters (alpha, beta), which 1042 does not; those
    stay in the tables.
    """

    satellite: int
    week: int
    urai: int
    idot: int
    aode: int
    toc: int
    a2: int
    a1: int
    a0: int
    aodc: int
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
    tgd1: int
    tgd2: int
    health: int


RTCM_NUMBER = 1042


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >> (bits - 1) else value


def d1_ephemeris(satellite: int, sf1: D1Subframe1, sf2: D1Subframe2,
                 sf3: D1Subframe3) -> Ephemeris:
    if not (sf2.sow == (sf1.sow + 6) % WEEK and sf3.sow == (sf1.sow + 12) % WEEK):
        raise FieldError(f"SOW {sf1.sow}, {sf2.sow}, {sf3.sow}: not subframes 1 to 3 of one frame")
    return Ephemeris(
        satellite=satellite, week=sf1.week, urai=sf1.urai, idot=sf3.idot, aode=sf1.aode,
        toc=sf1.toc, a2=sf1.a2, a1=sf1.a1, a0=sf1.a0, aodc=sf1.aodc, crs=sf2.crs,
        delta_n=sf2.delta_n, m0=sf2.m0, cuc=sf2.cuc, e=sf2.e, cus=sf2.cus, sqrt_a=sf2.sqrt_a,
        toe=sf2.toe_msb << 15 | sf3.toe_lsb, cic=sf3.cic, omega0=sf3.omega0, cis=sf3.cis,
        i0=sf3.i0, crc=sf2.crc, omega=sf3.omega, omega_dot=sf3.omega_dot, tgd1=sf1.tgd1,
        tgd2=sf1.tgd2, health=sf1.sat_h1)


def d2_ephemeris(satellite: int, pages: Sequence[Any]) -> Ephemeris:
    p = {page.PNUM: page for page in pages}
    if sorted(p) != list(range(1, 11)):
        raise FieldError("D2 needs pages 1 to 10 of subframe 1")
    if any(p[k].sow != (p[1].sow + 3 * (k - 1)) % WEEK for k in range(2, 11)):
        raise FieldError(f"SOW {[p[k].sow for k in range(1, 11)]}: not ten consecutive frames")
    return Ephemeris(
        satellite=satellite, week=p[1].week, urai=p[1].urai, idot=p[10].idot, aode=p[4].aode,
        toc=p[1].toc, a2=p[4].a2, a1=_signed(p[3].a1_msb << 18 | p[4].a1_lsb, 22), a0=p[3].a0,
        aodc=p[1].aodc, crs=p[8].crs, delta_n=p[4].delta_n, m0=p[5].m0,
        cuc=_signed(p[4].cuc_msb << 4 | p[5].cuc_lsb, 18), e=p[5].e_msb << 22 | p[6].e_lsb,
        cus=p[5].cus, sqrt_a=p[6].sqrt_a, toe=p[7].toe,
        cic=_signed(p[6].cic_msb << 8 | p[7].cic_lsb, 18), omega0=p[9].omega0, cis=p[7].cis,
        i0=_signed(p[7].i0_msb << 11 | p[8].i0_lsb, 32), crc=p[8].crc,
        omega=_signed(p[9].omega_msb << 5 | p[10].omega_lsb, 32),
        omega_dot=_signed(p[8].omega_dot_msb << 5 | p[9].omega_dot_lsb, 24),
        tgd1=p[1].tgd1, tgd2=p[1].tgd2, health=p[1].sat_h1)


def rtcm_fields(eph: Ephemeris) -> dict[str, int]:
    """Keyword arguments of ``gnsswire.rtcm3.Msg1042`` for ``eph`` (``number`` included)."""
    return {"number": RTCM_NUMBER, **{f.name: getattr(eph, f.name)
                                      for f in dataclasses.fields(eph)}}


class Assembler:
    """Collects D1 subframes 1 to 3 and D2 pages 1 to 10 per satellite; :meth:`push` returns
    each new complete issue (the rules are in the module documentation)."""

    def __init__(self) -> None:
        self._parts: dict[Any, dict[Any, Any]] = {}
        self._last: dict[Any, Ephemeris] = {}

    def push(self, satellite: int, message: Any) -> Ephemeris | None:
        kind = type(message)
        if kind in (D1Subframe1, D1Subframe2, D1Subframe3):
            key = ("D1", kind.FRAID)
        elif kind in D2_PAGES.values():
            key = ("D2", kind.PNUM)
        else:
            return None
        parts = self._parts.setdefault(satellite, {})
        parts[key] = message
        try:
            if key[0] == "D1":
                if not all(("D1", k) in parts for k in (1, 2, 3)):
                    return None
                eph = d1_ephemeris(satellite, *(parts["D1", k] for k in (1, 2, 3)))
            else:
                if not all(("D2", k) in parts for k in range(1, 11)):
                    return None
                eph = d2_ephemeris(satellite, [parts["D2", k] for k in range(1, 11)])
        except FieldError:
            return None
        if self._last.get(satellite) == eph:
            return None
        self._last[satellite] = eph
        return eph
