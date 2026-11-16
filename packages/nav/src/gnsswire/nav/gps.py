"""GPS LNAV: subframes of the L1 C/A navigation message, from IS-GPS-200N section 20.3.

The basis is IS-GPS-200N (1 August 2022) with its change notices
IRN-IS-200N-003 (27 September 2023) and IRN-IS-200N-004 (16 June 2026).
Every section, figure and table cited here is checked against the document
as they amend it. IRN-IS-200N-004 changes only CNAV (section 30, message
type 40); IRN-IS-200N-003 changes one thing this module implements, the
Data ID of subframes 4 and 5 (below).

A subframe is ten 30-bit words: 24 data bits and 6 parity bits each
(section 20.3.2, Figure 20-1). Parity is the (32,26) Hamming code of Table
20-XIV: the transmitted bits D1 to D24 are the source data bits d1 to d24,
complemented when the last parity bit D30* of the previous word is 1, and
D25 to D30 are computed from d1 to d24 and the previous word's D29* and D30*
(section 20.3.5). Bits 23 and 24 of words 2 and 10 (``t``) are solved for so
that D29 and D30 of those words are zero (Figure 20-2, Figure 20-1 note
"t"), so word 1 of every subframe follows D29* = D30* = 0.

Here a subframe is either the ten words as transmitted (:func:`decode`
checks their parity, :func:`encode` computes it) or its 240 source data
bits (:func:`decode_data`, :func:`encode_data`), as an ``int`` whose most
significant bit is d1 of word 1. A carrier that strips the parity (SkyTraq
0xE0) hands over the data bits; one that keeps it (UBX-RXM-SFRBX) the words.

Field tables (Figure 20-1, sheets 1 to 3, 5, 8 and 9, with Figures 20-2 for
the TLM and HOW words) are over the 240 data bits, so a parameter whose
bits lie in two adjacent words (M0, e, sqrt(A), and so on) is one row;
IODC, whose 2 MSBs are in word 3 and 8 LSBs in word 8, is two. Signed rows
are those Tables 20-I, 20-III, 20-IX and 20-X mark as two's complement.
Values are the integers of the ICD; the scale factors are those tables'.

Subframes 4 and 5 are told apart by subframe ID and their page by the SV
(page) ID of Table 20-V: page 18 of subframe 4 (SV ID 56, ionospheric and
UTC parameters), page 25 of subframe 4 (SV ID 63, A-S flags and SV
configurations, health of SVs 25 to 32) and page 25 of subframe 5 (SV ID
51, health of SVs 1 to 24) have tables. Those tables are read only when the
page's Data ID (the two MSBs of word 3) is "Data ID number two (denoted by
binary code 01)", the LNAV data structure of the appendix (20.3.3.5.1.1).
IS-GPS-200N called that "the only valid value"; IRN-IS-200N-003 deletes
those words and adds section 6.4.6.4, "Data ID Numbers Other Than 2": "The
recommended user protocol is to determine the Data ID before decoding and
using LNAV data", other Data IDs being reserved for "future data
structures". A page with another Data ID, and any other subframe, decodes
to :class:`OtherSubframe`, its data kept whole.

:class:`Assembler` collects subframes 1, 2 and 3 of one satellite and
returns a :class:`Ephemeris` when all three are present and of one issue:
IODE of subframes 2 and 3 equal to the 8 LSBs of IODC in subframe 1
(section 20.3.4.4). Its fields are named and scaled as
``gnsswire.rtcm3.Msg1019`` names them (RTCM 10403.3 Table 3.5-21 keeps the
ICD's widths and scale factors); :func:`rtcm_fields` gives the keyword
arguments of a ``Msg1019``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

from gnsswire.bits import S, U

from ._common import FieldError, ParityError, read_bits, replace, write_bits

PREAMBLE = 0x8B   # 10001011, section 20.3.3.1
DATA_ID = 0b01    # "Data ID number two (denoted by binary code 01)", 20.3.3.5.1.1
DATA_BITS = 240

# Table 20-XIV: for D25 to D30, which of D29* and D30* and which source data bits.
_PARITY = (
    (29, (1, 2, 3, 5, 6, 10, 11, 12, 13, 14, 17, 18, 20, 23)),
    (30, (2, 3, 4, 6, 7, 11, 12, 13, 14, 15, 18, 19, 21, 24)),
    (29, (1, 3, 4, 5, 7, 8, 12, 13, 14, 15, 16, 19, 20, 22)),
    (30, (2, 4, 5, 6, 8, 9, 13, 14, 15, 16, 17, 20, 21, 23)),
    (30, (1, 3, 5, 6, 7, 9, 10, 14, 15, 16, 17, 18, 21, 22, 24)),
    (29, (3, 5, 6, 8, 9, 10, 11, 13, 15, 19, 22, 23, 24)),
)
_MASKS = tuple((star, sum(1 << (24 - i) for i in bits)) for star, bits in _PARITY)


def parity(d: int, d29: int, d30: int) -> int:
    """D25 to D30 (Table 20-XIV) of source data bits ``d`` (d1 the MSB of 24) after D29*, D30*."""
    out = 0
    for star, mask in _MASKS:
        out = out << 1 | (((d & mask).bit_count() + (d29 if star == 29 else d30)) & 1)
    return out


def encode_word(d: int, d29: int, d30: int) -> int:
    """The transmitted 30-bit word of source data ``d`` after a word ending in D29*, D30*."""
    return (d ^ (0xFFFFFF if d30 else 0)) << 6 | parity(d, d29, d30)


def words_from_data(data: int) -> tuple[int, ...]:
    """The ten transmitted words of 240 source data bits, word 1 after D29* = D30* = 0."""
    words = []
    prev = 0
    for i in range(10):
        word = encode_word((data >> (24 * (9 - i))) & 0xFFFFFF, prev >> 1 & 1, prev & 1)
        words.append(word)
        prev = word & 3
    return tuple(words)


def data_from_words(words: Sequence[int]) -> int:
    """The 240 source data bits of ten transmitted words; :class:`ParityError` on a parity failure."""
    if len(words) != 10 or not all(isinstance(w, int) and 0 <= w < 1 << 30 for w in words):
        raise FieldError(f"a subframe is ten 30-bit words, got {words!r}")
    data = 0
    prev = 0
    for i, word in enumerate(words):
        d = (word >> 6) ^ (0xFFFFFF if prev & 1 else 0)
        if parity(d, prev >> 1 & 1, prev & 1) != word & 0x3F:
            raise ParityError(f"word {i + 1}: parity {word & 0x3F:06b}, Table 20-XIV gives "
                              f"{parity(d, prev >> 1 & 1, prev & 1):06b}")
        data = data << 24 | d
        prev = word & 3
    return data


# --- tables (Figure 20-1; TLM and HOW from Figure 20-2) ------------------------

@dataclass(frozen=True, slots=True)
class _Header:
    """TLM (word 1) and HOW (word 2) data bits, common to every subframe."""

    preamble: Annotated[int, U(8, "Preamble")]
    tlm: Annotated[int, U(14, "TLM Message")]
    integrity: Annotated[int, U(1, "Integrity Status Flag")]
    reserved_tlm: Annotated[int, U(1, "TLM bit 24, reserved")]
    tow: Annotated[int, U(17, "TOW-Count Message")]
    alert: Annotated[int, U(1, "Alert Flag")]
    anti_spoof: Annotated[int, U(1, "Anti-Spoof Flag")]
    subframe: Annotated[int, U(3, "Subframe ID")]
    t_how: Annotated[int, U(2, "HOW bits 23-24, solved for parity")]


@dataclass(frozen=True, slots=True)
class Subframe1(_Header):
    """Subframe 1: clock, health and accuracy. Figure 20-1 sheet 1, Table 20-I."""

    SUBFRAME: ClassVar[int] = 1

    week: Annotated[int, U(10, "WN")]
    l2_code: Annotated[int, U(2, "Codes on L2")]
    ura: Annotated[int, U(4, "URA Index")]
    health: Annotated[int, U(6, "SV Health")]
    iodc_msb: Annotated[int, U(2, "IODC, 2 MSBs")]
    l2p_data: Annotated[int, U(1, "L2 P Data Flag")]
    reserved1: Annotated[int, U(23, "word 4 bits 2-24, reserved")]
    reserved2: Annotated[int, U(24, "word 5, reserved")]
    reserved3: Annotated[int, U(24, "word 6, reserved")]
    reserved4: Annotated[int, U(16, "word 7 bits 1-16, reserved")]
    tgd: Annotated[int, S(8, "TGD")]
    iodc_lsb: Annotated[int, U(8, "IODC, 8 LSBs")]
    toc: Annotated[int, U(16, "toc")]
    af2: Annotated[int, S(8, "af2")]
    af1: Annotated[int, S(16, "af1")]
    af0: Annotated[int, S(22, "af0")]
    t: Annotated[int, U(2, "word 10 bits 23-24, solved for parity")]


@dataclass(frozen=True, slots=True)
class Subframe2(_Header):
    """Subframe 2: ephemeris, first part. Figure 20-1 sheet 2, Table 20-III."""

    SUBFRAME: ClassVar[int] = 2

    iode: Annotated[int, U(8, "IODE")]
    crs: Annotated[int, S(16, "Crs")]
    delta_n: Annotated[int, S(16, "Delta n")]
    m0: Annotated[int, S(32, "M0")]
    cuc: Annotated[int, S(16, "Cuc")]
    e: Annotated[int, U(32, "e")]
    cus: Annotated[int, S(16, "Cus")]
    sqrt_a: Annotated[int, U(32, "sqrt(A)")]
    toe: Annotated[int, U(16, "toe")]
    fit_interval: Annotated[int, U(1, "Fit Interval Flag")]
    aodo: Annotated[int, U(5, "AODO")]
    t: Annotated[int, U(2, "word 10 bits 23-24, solved for parity")]


@dataclass(frozen=True, slots=True)
class Subframe3(_Header):
    """Subframe 3: ephemeris, second part. Figure 20-1 sheet 3, Table 20-III."""

    SUBFRAME: ClassVar[int] = 3

    cic: Annotated[int, S(16, "Cic")]
    omega0: Annotated[int, S(32, "OMEGA0")]
    cis: Annotated[int, S(16, "Cis")]
    i0: Annotated[int, S(32, "i0")]
    crc: Annotated[int, S(16, "Crc")]
    omega: Annotated[int, S(32, "omega")]
    omega_dot: Annotated[int, S(24, "OMEGADOT")]
    iode: Annotated[int, U(8, "IODE")]
    idot: Annotated[int, S(14, "IDOT")]
    t: Annotated[int, U(2, "word 10 bits 23-24, solved for parity")]


@dataclass(frozen=True, slots=True)
class _Page(_Header):
    data_id: Annotated[int, U(2, "Data ID")]
    sv_id: Annotated[int, U(6, "SV (Page) ID")]


@dataclass(frozen=True, slots=True)
class Subframe4Page18(_Page):
    """Subframe 4 page 18 (SV ID 56): ionospheric and UTC parameters.

    Figure 20-1 sheet 8, Tables 20-IX and 20-X.
    """

    SUBFRAME: ClassVar[int] = 4
    SV_ID: ClassVar[int] = 56

    alpha0: Annotated[int, S(8, "alpha0")]
    alpha1: Annotated[int, S(8, "alpha1")]
    alpha2: Annotated[int, S(8, "alpha2")]
    alpha3: Annotated[int, S(8, "alpha3")]
    beta0: Annotated[int, S(8, "beta0")]
    beta1: Annotated[int, S(8, "beta1")]
    beta2: Annotated[int, S(8, "beta2")]
    beta3: Annotated[int, S(8, "beta3")]
    a1: Annotated[int, S(24, "A1")]
    a0: Annotated[int, S(32, "A0")]
    tot: Annotated[int, U(8, "tot")]
    wnt: Annotated[int, U(8, "WNt")]
    dt_ls: Annotated[int, S(8, "Delta tLS")]
    wn_lsf: Annotated[int, U(8, "WNLSF")]
    dn: Annotated[int, U(8, "DN")]
    dt_lsf: Annotated[int, S(8, "Delta tLSF")]
    reserved: Annotated[int, U(14, "word 10 bits 9-22, reserved for system use")]
    t: Annotated[int, U(2, "word 10 bits 23-24, solved for parity")]


@dataclass(frozen=True, slots=True)
class Subframe4Page25(_Page):
    """Subframe 4 page 25 (SV ID 63): A-S flags and SV configurations of SVs 1 to 32,
    health of SVs 25 to 32. Figure 20-1 sheet 9."""

    SUBFRAME: ClassVar[int] = 4
    SV_ID: ClassVar[int] = 63

    config: Annotated[tuple[int, ...], U(4, "A-SPOOF & SV CONFIG, SVs 1-32", count=32)]
    reserved1: Annotated[int, U(2, "word 8 bits 17-18, reserved for system use")]
    health: Annotated[tuple[int, ...], U(6, "SV HEALTH, SVs 25-32", count=8)]
    reserved2: Annotated[int, U(4, "word 10 bits 19-22, reserved for system use")]
    t: Annotated[int, U(2, "word 10 bits 23-24, solved for parity")]


@dataclass(frozen=True, slots=True)
class Subframe5Page25(_Page):
    """Subframe 5 page 25 (SV ID 51): almanac reference, health of SVs 1 to 24.

    Figure 20-1 sheet 5.
    """

    SUBFRAME: ClassVar[int] = 5
    SV_ID: ClassVar[int] = 51

    toa: Annotated[int, U(8, "toa")]
    wna: Annotated[int, U(8, "WNa")]
    health: Annotated[tuple[int, ...], U(6, "SV HEALTH, SVs 1-24", count=24)]
    reserved1: Annotated[int, U(6, "word 10 bits 1-6, reserved")]
    reserved2: Annotated[int, U(16, "word 10 bits 7-22, reserved for system use")]
    t: Annotated[int, U(2, "word 10 bits 23-24, solved for parity")]


@dataclass(frozen=True, slots=True)
class OtherSubframe(_Header):
    """Any subframe without a table here: words 3 to 10 kept whole (190 data bits, then t)."""

    data: Annotated[int, U(64, "words 3-5")]
    data2: Annotated[int, U(64, "words 6-8")]
    data3: Annotated[int, U(62, "words 9-10 bits 1-22")]
    t: Annotated[int, U(2, "word 10 bits 23-24, solved for parity")]


TABLES: dict[tuple[int, int | None], type] = {
    (1, None): Subframe1, (2, None): Subframe2, (3, None): Subframe3,
    (4, 56): Subframe4Page18, (4, 63): Subframe4Page25, (5, 51): Subframe5Page25,
}
Message = (Subframe1 | Subframe2 | Subframe3 | Subframe4Page18 | Subframe4Page25
           | Subframe5Page25 | OtherSubframe)


def table(data: int) -> type:
    """The table of 240 data bits: by subframe ID (HOW bits 20-22), and for subframes 4 and 5
    by SV (page) ID when the Data ID is 2 (binary 01; IRN-IS-200N-003, 6.4.6.4)."""
    subframe = (data >> (240 - 46)) & 7
    data_id = (data >> (240 - 50)) & 3
    sv_id = (data >> (240 - 56)) & 0x3F
    if subframe in (4, 5) and data_id != DATA_ID:
        return OtherSubframe
    return TABLES.get((subframe, None)) or TABLES.get((subframe, sv_id)) or OtherSubframe


def decode_data(data: int) -> Message:
    """The subframe of 240 source data bits (d1 of word 1 the most significant)."""
    return read_bits(table(data), data, DATA_BITS)  # type: ignore[no-any-return]


def encode_data(message: Message) -> int:
    """The 240 source data bits of ``message``."""
    _check(message)
    return write_bits(message)


def decode(words: Sequence[int]) -> Message:
    """The subframe of ten transmitted 30-bit words, parity checked (Table 20-XIV)."""
    return decode_data(data_from_words(words))


def encode(message: Message) -> tuple[int, ...]:
    """The ten transmitted 30-bit words of ``message``, parity computed."""
    return words_from_data(encode_data(message))


def _check(message: Any) -> None:
    if type(message) not in (*TABLES.values(), OtherSubframe):
        raise FieldError(f"{type(message).__qualname__} is not a GPS LNAV subframe table")


def solve_t(message: Message) -> Message:
    """``message`` with the ``t`` bits of words 2 and 10 solved so that their D29 and D30 are
    zero, as the satellite sends them (Figure 20-2), leaving every other bit as it is."""
    for name, word in (("t_how", 1), ("t", 9)):
        for t in range(4):
            candidate = replace(message, **{name: t})
            words = encode(candidate)
            if words[word] & 3 == 0:
                message = candidate
                break
    return message


# --- ephemeris -----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Ephemeris:
    """One issue of a GPS satellite's clock and ephemeris, from subframes 1, 2 and 3.

    The fields are those of ``gnsswire.rtcm3.Msg1019`` (RTCM 10403.3 Table
    3.5-21), same names, same integers, in the same order, without
    ``number`` and ``extension``; then ``aodo``, which LNAV has and 1019
    does not. 1019 has nothing that LNAV lacks. ``satellite`` is the PRN
    the carrier names (the subframes do not hold it); ``iodc`` joins the
    two parts of subframe 1; ``iode`` is the IODE of subframes 2 and 3,
    which equals the 8 LSBs of ``iodc``.
    """

    satellite: int
    week: int
    accuracy: int
    l2_code: int
    idot: int
    iode: int
    toc: int
    af2: int
    af1: int
    af0: int
    iodc: int
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
    tgd: int
    health: int
    l2p_data: int
    fit_interval: int
    aodo: int


RTCM_NUMBER = 1019
NOT_IN_RTCM = ("aodo",)


def ephemeris(satellite: int, sf1: Subframe1, sf2: Subframe2, sf3: Subframe3) -> Ephemeris:
    """The ephemeris of three subframes of one issue; :class:`FieldError` if they are not."""
    iodc = sf1.iodc_msb << 8 | sf1.iodc_lsb
    if not sf2.iode == sf3.iode == iodc & 0xFF:
        raise FieldError(f"IODC {iodc} (8 LSBs {iodc & 0xFF}), IODE {sf2.iode} and {sf3.iode}: "
                         f"not one issue (IS-GPS-200N with IRN-IS-200N-003 and -004, "
                         f"20.3.4.4)")
    return Ephemeris(
        satellite=satellite, week=sf1.week, accuracy=sf1.ura, l2_code=sf1.l2_code,
        idot=sf3.idot, iode=sf2.iode, toc=sf1.toc, af2=sf1.af2, af1=sf1.af1, af0=sf1.af0,
        iodc=iodc, crs=sf2.crs, delta_n=sf2.delta_n, m0=sf2.m0, cuc=sf2.cuc, e=sf2.e,
        cus=sf2.cus, sqrt_a=sf2.sqrt_a, toe=sf2.toe, cic=sf3.cic, omega0=sf3.omega0,
        cis=sf3.cis, i0=sf3.i0, crc=sf3.crc, omega=sf3.omega, omega_dot=sf3.omega_dot,
        tgd=sf1.tgd, health=sf1.health, l2p_data=sf1.l2p_data,
        fit_interval=sf2.fit_interval, aodo=sf2.aodo)


def rtcm_fields(eph: Ephemeris) -> dict[str, int]:
    """Keyword arguments of ``gnsswire.rtcm3.Msg1019`` for ``eph`` (``number`` included)."""
    fields = {f.name: getattr(eph, f.name) for f in dataclasses.fields(eph)
              if f.name not in NOT_IN_RTCM}
    return {"number": RTCM_NUMBER, **fields}


class Assembler:
    """Collects subframes 1 to 3 per satellite; :meth:`push` returns each new complete issue.

    Only the latest subframe of each kind is kept. An ephemeris is returned
    when the subframe just pushed completes a set of one issue (IODE of
    subframes 2 and 3 equal to the 8 LSBs of IODC, section 20.3.4.4) that
    differs from the last one returned for that satellite.
    """

    def __init__(self) -> None:
        self._parts: dict[Any, dict[int, Any]] = {}
        self._last: dict[Any, Ephemeris] = {}

    def push(self, satellite: int, message: Message) -> Ephemeris | None:
        if not isinstance(message, (Subframe1, Subframe2, Subframe3)):
            return None
        parts = self._parts.setdefault(satellite, {})
        parts[message.SUBFRAME] = message
        if len(parts) < 3:
            return None
        try:
            eph = ephemeris(satellite, parts[1], parts[2], parts[3])
        except FieldError:
            return None
        if self._last.get(satellite) == eph:
            return None
        self._last[satellite] = eph
        return eph
