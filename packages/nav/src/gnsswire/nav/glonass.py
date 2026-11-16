"""GLONASS navigation message strings (L1OF, L2OF), from the GLONASS ICD edition 5.1 (2008).

A string is 85 bits, numbered 85 (first transmitted) down to 1: bit 85 is
the idle chip ("0"), bits 84 to 9 data, bits 8 to 1 the check bits of the
Hamming code (section 4.3.3, Figure 4.3). Here a string is an ``int`` of
85 bits, bit 85 the most significant. The Hamming code is section 4.7:
check bits beta1 to beta7 each make one checksum C1 to C7 over listed data
bit positions zero, and beta8 makes the sum over all 85 bits (CSigma)
zero. :func:`decode` takes a string whose checksums are all zero, the only
case in which section 4.7 calls the string correct without correcting it,
and refuses any other (it does not correct a bit); :func:`hamming` computes
the check bits.

The data bits are those of the relative bi-binary code once the receiver
has decoded it (the carriers deliver them so: UBX-RXM-SFRBX, SkyTraq 0xE1).

Strings 1 to 4 carry the immediate data (ephemeris, Tables 4.5 and 4.6),
string 5 the time scale parameters (Tables 4.9 and 4.11), the even strings
6 to 14 and odd strings 7 to 15 the almanac (Table 4.11); in the fifth frame
of the superframe strings 14 and 15 are not almanac (Table 4.12) and, the
frame number not being in the string, decode as almanac unless ``frame=5``
is given, in which case they are :class:`Other`. Rows are numbered as in
Table 4.6 and 4.11; unnamed positions are the reserved bits of Table 4.12.
Signed rows are sign-magnitude: "the MSB is the sign bit" (section 4.4,
Tables 4.5 and 4.9).

:class:`Assembler` returns an :class:`Ephemeris`, named and scaled as
``gnsswire.rtcm3.Msg1020`` (RTCM 10403.3 Table 3.5-22 keeps the ICD's
widths, scale factors and sign-magnitude coding), when strings 1 to 5 of
one frame have been received, one after another (a frame's strings come
in order, 2 s apart, section 4.3.2).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

from gnsswire.bits import SM, U

from ._common import FieldError, ParityError, read_bits, write_bits

STRING_BITS = 85


def _positions(*spec: int | tuple[int, int]) -> tuple[int, ...]:
    out: list[int] = []
    for s in spec:
        out += list(range(s[0], s[1] + 1)) if isinstance(s, tuple) else [s]
    return tuple(out)


# Section 4.7: the data bit positions of checksums C1 to C7.
_CHECKS = (
    (9, 10, 12, 13, 15, 17, 19, 20, 22, 24, 26, 28, 30, 32, 34, 35, 37, 39, 41, 43, 45, 47, 49, 51,
     53, 55, 57, 59, 61, 63, 65, 66, 68, 70, 72, 74, 76, 78, 80, 82, 84),
    (9, 11, 12, 14, 15, 18, 19, 21, 22, 25, 26, 29, 30, 33, 34, 36, 37, 40, 41, 44, 45, 48, 49, 52,
     53, 56, 57, 60, 61, 64, 65, 67, 68, 71, 72, 75, 76, 79, 80, 83, 84),
    _positions((10, 12), (16, 19), (23, 26), (31, 34), (38, 41), (46, 49), (54, 57), (62, 65),
               (69, 72), (77, 80), 85),
    _positions((13, 19), (27, 34), (42, 49), (58, 65), (73, 80)),
    _positions((20, 34), (50, 65), (81, 85)),
    _positions((35, 65)),
    _positions((66, 85)),
)
_MASKS = tuple(sum(1 << (n - 1) for n in check) for check in _CHECKS)


def hamming(string: int) -> int:
    """beta8 to beta1 (bits 8 to 1) for the data bits 85 to 9 of ``string``."""
    betas = [(string & mask).bit_count() & 1 for mask in _MASKS]   # beta1 to beta7
    beta8 = ((string >> 8).bit_count() + sum(betas)) & 1
    return beta8 << 7 | sum(b << i for i, b in enumerate(betas))


def checksums(string: int) -> tuple[int, ...]:
    """C1 to C7 and CSigma of section 4.7."""
    cs = tuple(((string >> i) & 1) ^ ((string & mask).bit_count() & 1)
               for i, mask in enumerate(_MASKS))
    return cs + (string.bit_count() & 1,)


# --- tables -----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Head:
    idle: Annotated[int, U(1, "bit 85, idle chip")]
    m: Annotated[int, U(4, "m, bits 84-81")]


@dataclass(frozen=True, slots=True)
class String1(_Head):
    """String 1: P1, tk, x. Tables 4.5, 4.6 and 4.12."""

    M: ClassVar[int] = 1

    reserved: Annotated[int, U(2, "bits 80-79, reserved")]
    p1: Annotated[int, U(2, "P1, bits 78-77")]
    tk: Annotated[int, U(12, "tk, bits 76-65")]
    x_dot: Annotated[int, SM(24, "x', bits 64-41")]
    x_ddot: Annotated[int, SM(5, "x'', bits 40-36")]
    x: Annotated[int, SM(27, "x, bits 35-9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


@dataclass(frozen=True, slots=True)
class String2(_Head):
    """String 2: Bn, P2, tb, y. Tables 4.5, 4.6 and 4.12."""

    M: ClassVar[int] = 2

    bn: Annotated[int, U(3, "Bn, bits 80-78")]
    p2: Annotated[int, U(1, "P2, bit 77")]
    tb: Annotated[int, U(7, "tb, bits 76-70")]
    reserved: Annotated[int, U(5, "bits 69-65, reserved")]
    y_dot: Annotated[int, SM(24, "y', bits 64-41")]
    y_ddot: Annotated[int, SM(5, "y'', bits 40-36")]
    y: Annotated[int, SM(27, "y, bits 35-9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


@dataclass(frozen=True, slots=True)
class String3(_Head):
    """String 3: P3, gamma, P, ln, z. Tables 4.5, 4.6 and 4.12."""

    M: ClassVar[int] = 3

    p3: Annotated[int, U(1, "P3, bit 80")]
    gamma: Annotated[int, SM(11, "gamma_n, bits 79-69")]
    reserved: Annotated[int, U(1, "bit 68, reserved")]
    p: Annotated[int, U(2, "P, bits 67-66")]
    ln: Annotated[int, U(1, "ln, bit 65")]
    z_dot: Annotated[int, SM(24, "z', bits 64-41")]
    z_ddot: Annotated[int, SM(5, "z'', bits 40-36")]
    z: Annotated[int, SM(27, "z, bits 35-9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


@dataclass(frozen=True, slots=True)
class String4(_Head):
    """String 4: tau, delta tau, En, P4, FT, NT, n, M. Tables 4.5, 4.6 and 4.12."""

    M: ClassVar[int] = 4

    tau: Annotated[int, SM(22, "tau_n, bits 80-59")]
    delta_tau: Annotated[int, SM(5, "delta tau_n, bits 58-54")]
    en: Annotated[int, U(5, "En, bits 53-49")]
    reserved1: Annotated[int, U(14, "bits 48-35, reserved")]
    p4: Annotated[int, U(1, "P4, bit 34")]
    ft: Annotated[int, U(4, "FT, bits 33-30")]
    reserved2: Annotated[int, U(3, "bits 29-27, reserved")]
    nt: Annotated[int, U(11, "NT, bits 26-16")]
    n: Annotated[int, U(5, "n, bits 15-11")]
    sat_type: Annotated[int, U(2, "M, bits 10-9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


@dataclass(frozen=True, slots=True)
class String5(_Head):
    """String 5: NA, tau_c, N4, tau_GPS, ln. Tables 4.9, 4.11 and 4.12."""

    M: ClassVar[int] = 5

    na: Annotated[int, U(11, "NA, bits 80-70")]
    tau_c: Annotated[int, SM(32, "tau_c, bits 69-38")]
    reserved: Annotated[int, U(1, "bit 37, reserved")]
    n4: Annotated[int, U(5, "N4, bits 36-32")]
    tau_gps: Annotated[int, SM(22, "tau_GPS, bits 31-10")]
    ln: Annotated[int, U(1, "ln, bit 9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


@dataclass(frozen=True, slots=True)
class AlmanacEven(_Head):
    """Strings 6, 8, 10, 12 and 14: almanac of satellite nA, first part. Table 4.11."""

    cn: Annotated[int, U(1, "Cn, bit 80")]
    sat_type: Annotated[int, U(2, "MnA, bits 79-78")]
    na: Annotated[int, U(5, "nA, bits 77-73")]
    tau_a: Annotated[int, SM(10, "tau_nA, bits 72-63")]
    lambda_: Annotated[int, SM(21, "lambda_nA, bits 62-42")]
    delta_i: Annotated[int, SM(18, "delta i_nA, bits 41-24")]
    epsilon: Annotated[int, U(15, "epsilon_nA, bits 23-9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


@dataclass(frozen=True, slots=True)
class AlmanacOdd(_Head):
    """Strings 7, 9, 11, 13 and 15: almanac of satellite nA, second part. Table 4.11."""

    omega: Annotated[int, SM(16, "omega_nA, bits 80-65")]
    t_lambda: Annotated[int, U(21, "t_lambda_nA, bits 64-44")]
    delta_t: Annotated[int, SM(22, "delta T_nA, bits 43-22")]
    delta_t_dot: Annotated[int, SM(7, "delta T'_nA, bits 21-15")]
    h: Annotated[int, U(5, "H_nA, bits 14-10")]
    ln: Annotated[int, U(1, "ln, bit 9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


@dataclass(frozen=True, slots=True)
class Other(_Head):
    """A string without a table here (strings 14 and 15 of frame 5, string numbers 0 or 16 and
    up, which the ICD does not define): bits 80 to 1 kept whole."""

    # Two rows: a bits row is at most 64 bits wide.
    data: Annotated[int, U(36, "bits 80-45")]
    data2: Annotated[int, U(36, "bits 44-9")]
    kx: Annotated[int, U(8, "Hamming code, bits 8-1")]


TABLES: dict[int, type] = {cls.M: cls for cls in (String1, String2, String3, String4, String5)}
TABLES.update({m: AlmanacEven for m in (6, 8, 10, 12, 14)})
TABLES.update({m: AlmanacOdd for m in (7, 9, 11, 13, 15)})
ALL = (String1, String2, String3, String4, String5, AlmanacEven, AlmanacOdd, Other)


def check(string: int) -> None:
    """:class:`ParityError` unless every checksum of section 4.7 is zero."""
    if not isinstance(string, int) or not 0 <= string < 1 << STRING_BITS:
        raise FieldError(f"a string is 85 bits, got {string!r}")
    cs = checksums(string)
    if any(cs):
        raise ParityError(f"Hamming checksums C1-C7, CSigma {cs}: section 4.7 needs all zero")


def decode(string: int, *, frame: int | None = None) -> Any:
    """The table of an 85-bit string (bit 85 the most significant), Hamming code checked."""
    check(string)
    m = (string >> 80) & 0xF
    cls = Other if frame == 5 and m in (14, 15) else TABLES.get(m, Other)
    return read_bits(cls, string, STRING_BITS)


def encode(message: Any) -> int:
    """The 85 bits of a string table, its fields (``kx`` included) as they are."""
    if type(message) not in ALL:
        raise FieldError(f"{type(message).__qualname__} is not a GLONASS string table")
    return write_bits(message)


def with_hamming(message: Any) -> Any:
    """``message`` with ``kx`` computed from its other bits (section 4.7)."""
    bits = encode(dataclasses.replace(message, kx=0))
    return dataclasses.replace(message, kx=hamming(bits))


# --- ephemeris ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Ephemeris:
    """One issue of a GLONASS satellite's immediate data: strings 1 to 5 of one frame.

    The fields are those of ``gnsswire.rtcm3.Msg1020`` (RTCM 10403.3 Table
    3.5-22) that come from strings 1 to 5, same names and integers, in the
    same order: ``satellite`` is n of string 4 (DF038), ``bn_msb`` the MSB
    of Bn (DF108), ``ln_third`` and ``ln_fifth`` the ln of strings 3 and 5,
    ``m`` the satellite type M of string 4 (DF130). 1020 also has
    ``channel`` (DF040, the frequency channel + 7, which the strings do not
    hold: the carrier's), ``almanac_health`` and
    ``almanac_health_available`` (DF104, DF105: Cn of the almanac, in
    another string), ``additional`` (DF131, set to 1 because string 5 is
    present) and seven reserved bits; :func:`rtcm_fields` takes the
    first three as arguments. The strings hold, and 1020 does not, the two
    LSBs of Bn (``bn``, kept whole here, after the 1020 fields) and the
    string 1 reserved bits.
    """

    satellite: int
    p1: int
    tk: int
    bn_msb: int
    p2: int
    tb: int
    x_dot: int
    x: int
    x_ddot: int
    y_dot: int
    y: int
    y_ddot: int
    z_dot: int
    z: int
    z_ddot: int
    p3: int
    gamma: int
    p: int
    ln_third: int
    tau: int
    delta_tau: int
    en: int
    p4: int
    ft: int
    nt: int
    m: int
    na: int
    tau_c: int
    n4: int
    tau_gps: int
    ln_fifth: int
    bn: int


RTCM_NUMBER = 1020


def ephemeris(s1: String1, s2: String2, s3: String3, s4: String4, s5: String5) -> Ephemeris:
    return Ephemeris(
        satellite=s4.n, p1=s1.p1, tk=s1.tk, bn_msb=s2.bn >> 2, p2=s2.p2, tb=s2.tb,
        x_dot=s1.x_dot, x=s1.x, x_ddot=s1.x_ddot, y_dot=s2.y_dot, y=s2.y, y_ddot=s2.y_ddot,
        z_dot=s3.z_dot, z=s3.z, z_ddot=s3.z_ddot, p3=s3.p3, gamma=s3.gamma, p=s3.p,
        ln_third=s3.ln, tau=s4.tau, delta_tau=s4.delta_tau, en=s4.en, p4=s4.p4, ft=s4.ft,
        nt=s4.nt, m=s4.sat_type, na=s5.na, tau_c=s5.tau_c, n4=s5.n4, tau_gps=s5.tau_gps,
        ln_fifth=s5.ln, bn=s2.bn)


def rtcm_fields(eph: Ephemeris, *, channel: int, almanac_health: int | None = None
                ) -> dict[str, int]:
    """Keyword arguments of ``gnsswire.rtcm3.Msg1020`` for ``eph`` (``number`` included).

    ``channel`` is DF040, the frequency channel number + 7 (UBX-RXM-SFRBX
    ``freqId`` is exactly that); ``almanac_health`` is Cn from the almanac,
    or ``None`` when it is not known (DF105 = 0).
    """
    fields = {f.name: getattr(eph, f.name) for f in dataclasses.fields(eph) if f.name != "bn"}
    fields["channel"] = channel
    fields["almanac_health"] = 0 if almanac_health is None else almanac_health
    fields["almanac_health_available"] = 0 if almanac_health is None else 1
    fields["additional"] = 1
    fields["reserved"] = 0
    order = ("number", "satellite", "channel", "almanac_health", "almanac_health_available",
             "p1", "tk", "bn_msb", "p2", "tb", "x_dot", "x", "x_ddot", "y_dot", "y", "y_ddot",
             "z_dot", "z", "z_ddot", "p3", "gamma", "p", "ln_third", "tau", "delta_tau", "en",
             "p4", "ft", "nt", "m", "additional", "na", "tau_c", "n4", "tau_gps", "ln_fifth",
             "reserved")
    fields["number"] = RTCM_NUMBER
    return {name: fields[name] for name in order}


class Assembler:
    """Collects strings 1 to 5 per stream; :meth:`push` returns each new complete issue.

    A stream is one satellite on one signal (pass a key such as
    ``(slot, signal)``). Strings 1 to 5 count only when they arrive in
    order, each right after the one before it in the same stream: then they
    are strings 1 to 5 of one frame. Any other string starts the count over.
    """

    def __init__(self) -> None:
        self._run: dict[Any, list[Any]] = {}
        self._last: dict[Any, Ephemeris] = {}

    def push(self, stream: Any, message: Any) -> Ephemeris | None:
        run = self._run.setdefault(stream, [])
        m = getattr(type(message), "M", None)
        if m == 1:
            run[:] = [message]
        elif m is not None and len(run) == m - 1:
            run.append(message)
        else:
            run.clear()
        if len(run) < 5:
            return None
        eph = ephemeris(*run)
        run.clear()
        if self._last.get(stream) == eph:
            return None
        self._last[stream] = eph
        return eph
