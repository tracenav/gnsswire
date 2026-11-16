"""IGS State Space Representation (IGS SSR): RTCM proprietary message 4076.

Source: "IGS State Space Representation (SSR) Format, Version 1.00",
International GNSS Service, 2020-10-05 (cited below as "IGS SSR"). The
format is carried in ordinary RTCM 3 frames (IGS SSR section 2: "uses the
basic structure of RTCM3 ... the first data field is a 12-bit message
number"), the number being 4076, which RTCM assigned to the IGS. Every
message starts with DF002 = 4076, the IGM/IM version IDF001 (uint3) and the
IGS message number IDF002 (uint8), the sub-type, which says which table
follows (section 6, Table 5):

========== =========================================== ===================
sub-type   message                                     class
========== =========================================== ===================
21 + 20·s  IGM01 SSR Orbit Correction                  :class:`IgsOrbit`
22 + 20·s  IGM02 SSR Clock Correction                  :class:`IgsClock`
23 + 20·s  IGM03 SSR Combined Orbit and Clock          :class:`IgsCombined`
24 + 20·s  IGM04 SSR High Rate Clock Correction        :class:`IgsHighRateClock`
25 + 20·s  IGM05 SSR Code Bias                         :class:`IgsCodeBias`
26 + 20·s  IGM06 SSR Phase Bias                        :class:`IgsPhaseBias`
27 + 20·s  IGM07 SSR URA                               :class:`IgsUra`
201        IM201 SSR Ionosphere VTEC Spherical Harmonics :class:`IgsVtec`
========== =========================================== ===================

where s is 0 for GPS, 1 GLONASS, 2 Galileo, 3 QZSS, 4 BDS and 5 SBAS
(:data:`IGS_SUBTYPES`). As for MSM (``_msm``), one class serves every
system: the systems' tables differ only in what the satellite and signal
identifiers and the IOD mean (Table 7, IDF011, IDF012, IDF024), which is
interpretation. The sub-types Table 5 marks "Reserved" (IM000 to IM020,
IM028 to IM040 and so on, NavIC's IM141 to IM160, IM202 to IM254) and 255
("reserved for extension") have no table and raise ``Unsupported``.

Each class is the header table of section 8 (Tables 8, 10, 12, 14, 16, 19,
22, 24), with the satellite part (Tables 9, 11, 13, 15, 17, 20, 23) as a
repeated group of IDF010 "No. of Satellites" items, and the bias parts
(Tables 18, 21) as a group of IDF023 "No. of Biases Processed" items inside
each satellite: "Each SV Block consists of a satellite specific part
immediately followed by a code specific part per processed code bias"
(section 8.2). The counts are fields, kept as sent, and must equal the
lengths of the tuples that follow them.

Fields are the raw IDF integers. Resolutions and units are Table 7's, given
per row below (for example ``radial`` in 0.1 mm, ``c2`` in 0.00002 mm/s²);
nothing is scaled, and no correction is applied to anything. Table 7 types
IDF004, IDF005, IDF006, IDF012, IDF029, IDF030, IDF032, IDF033 and IDF034
"bit(n)"; they are read as unsigned integers of n bits, MSB first.

Notes on the tables (the readings taken are listed in the package README,
"Limitations"):

- Table 9 (orbit, satellite part) labels its rows "Delta Orbit Cross-Track
  IDF016 int20" and "Dot Orbit Delta Radial IDF015 int21", while Table 7
  and Table 13 (combined) have IDF015 as cross-track (int20) and IDF016 as
  the radial velocity (int21). The names and widths agree in both tables,
  so the bits are the same either way; the rows here are tagged as Table 7
  and Table 13 tag them.
- IDF001 has a value per sub-type ("0 - experimental, 1 - 6 Version, 7 -
  reserved"). This document is version 1.00 and gives one table per
  sub-type; it does not say whether the tables depend on IDF001. Every
  value is decoded with these tables and kept as ``version``.
- IM201, the coefficient counts: Table 7 gives (N+1)(N+2)/2 −
  (N−M)(N−M+1)/2 cosine and that less N+1 sine coefficients, N = IDF037 + 1
  and M = IDF038 + 1, and section 8.4.1 orders them "Cnm (m=0,M, n=m,N)",
  "Snm (m=1,M, n=m,N)"; section 4.5.1 has M ≤ N. For M ≤ N the formula and
  the loop agree. For M > N (not allowed by 4.5.1) the formula and the loop
  differ; the counts here follow the loop, that is the formula with M
  taken as min(M, N), so such a message still decodes as a transmitter
  following the loop would write it.
"""

from dataclasses import dataclass
from typing import Annotated

from gnsswire.bits import F, Group, S, U

from ._station import Ext

IGS_SSR = 4076   # the RTCM message number assigned to the IGS (IGS SSR section 2)

# IGS SSR Table 5: the first sub-type of each system's block of seven
# (IGM01 to IGM07), and the general sub-type IM201.
IGS_SYSTEMS = {"GPS": 21, "GLONASS": 41, "Galileo": 61, "QZSS": 81, "BDS": 101, "SBAS": 121}
IGM_TYPES = ("IGM01", "IGM02", "IGM03", "IGM04", "IGM05", "IGM06", "IGM07")
VTEC = 201

# Sub-type (IDF002) to (system, IGM type), Table 5; IM201 belongs to no system.
IGS_SUBTYPES: dict[int, tuple[str | None, str]] = {
    **{first + i: (system, igm) for system, first in IGS_SYSTEMS.items()
       for i, igm in enumerate(IGM_TYPES)},
    VTEC: (None, "IM201"),
}

# IDF004, SSR Update Interval (Table 7): code 0 to 15 to seconds.
IGS_UPDATE_INTERVALS = (1, 2, 5, 10, 15, 30, 60, 120, 240, 300, 600, 900, 1800, 3600, 7200, 10800)


def update_interval(code: int) -> int:
    """IDF004's code as seconds (IGS SSR Table 7). Raises ``ValueError`` outside 0 to 15.

    Corrections refer to IDF003 plus half this interval, except for code 0
    (IDF013 note); applying that is the caller's.
    """
    if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= 15:
        raise ValueError(f"IDF004 is 0 to 15, not {code!r}")
    return IGS_UPDATE_INTERVALS[code]


def _ids(pairs: range, first_number: int, zero: int | None = None) -> dict[int, int]:
    table = {i: first_number + i - pairs.start for i in pairs}
    if zero is not None:
        table[0] = zero
    return table


# IDF011, GNSS Satellite ID, to the system's satellite number (Table 7):
# "1=1 ... 63=63, 0=64" for GPS, GLONASS and BDS; Galileo 1 to 36; QZSS
# "1=193 ... 10=202"; SBAS "1=120 ... 39=158". Identifiers outside a table
# are "Reserved". Data for callers; decode keeps IDF011 as sent.
IGS_SATELLITES: dict[str, dict[int, int]] = {
    "GPS": _ids(range(1, 64), 1, 64),
    "GLONASS": _ids(range(1, 64), 1, 64),
    "Galileo": _ids(range(1, 37), 1),
    "QZSS": _ids(range(1, 11), 193),
    "BDS": _ids(range(1, 64), 1, 64),
    "SBAS": _ids(range(1, 40), 120),
}

# IDF024, GNSS Signal and Tracking Mode Identifier, to the RINEX band and
# attribute Table 7 prints with each (the second and third characters of a
# RINEX 3 observation code: "1C" gives C1C for a code bias, L1C for a phase
# bias). Identifiers Table 7 lists as "Reserved", or does not list, are
# absent. Table 7 ends the GLONASS list at 9 with ">10 Reserved" and the BDS
# list at 18 with ">19 Reserved", so it says nothing of GLONASS 10 and BDS
# 19; they are absent here too. Data for callers; decode keeps IDF024 as sent.
IGS_SIGNALS: dict[str, dict[int, str]] = {
    "GPS": {0: "1C", 1: "1P", 2: "1W", 3: "1S", 4: "1L", 5: "2C", 6: "2D", 7: "2S", 8: "2L",
            10: "2P", 11: "2W", 14: "5I", 15: "5Q"},
    "GLONASS": {0: "1C", 1: "1P", 2: "2C", 3: "2P", 4: "4A", 5: "4B", 6: "6A", 7: "6B",
                8: "3I", 9: "3Q"},
    "Galileo": {0: "1A", 1: "1B", 2: "1C", 5: "5I", 6: "5Q", 8: "7I", 9: "7Q", 14: "6A",
                15: "6B", 16: "6C"},
    "QZSS": {0: "1C", 1: "1S", 2: "1L", 3: "2S", 4: "2L", 6: "5I", 7: "5Q", 9: "6S", 10: "6L",
             17: "6E"},
    "BDS": {0: "2I", 1: "2Q", 3: "6I", 4: "6Q", 6: "7I", 7: "7Q", 9: "1D", 10: "1P", 12: "5D",
            13: "5P", 15: "1A", 18: "6A"},
    "SBAS": {0: "1C", 1: "5I", 2: "5Q"},
}


# --- header rows shared by every sub-type (Tables 8, 10, 12, 14, 16, 19, 22, 24) ----------
#
# Written out in each class (a table is its rows, in order), with these
# meanings, Table 7:
#   number    DF002   uint12  always 4076
#   version   IDF001  uint3   IGM/IM version: 0 experimental, 1 to 6, 7 reserved
#   subtype   IDF002  uint8   IGS message number (Table 5)
#   epoch     IDF003  uint20  SSR Epoch Time 1 s, 0 to 604799 s of the week
#   interval  IDF004  bit(4)  SSR Update Interval code (update_interval)
#   multiple  IDF005  bit(1)  1: more messages of this sub-type and epoch follow
#   iod_ssr   IDF007  uint4   IOD SSR
#   provider  IDF008  uint16  SSR Provider ID
#   solution  IDF009  uint4   SSR Solution ID


@dataclass(frozen=True, slots=True)
class IgsOrbitSat:
    """IGM01 satellite part, IGS SSR Table 9 (135 bits)."""

    satellite: Annotated[int, U(6, "IDF011")]
    iod: Annotated[int, U(8, "IDF012")]              # GNSS IOD, bit(8)
    radial: Annotated[int, S(22, "IDF013")]          # 0.1 mm
    along: Annotated[int, S(20, "IDF014")]           # 0.4 mm
    cross: Annotated[int, S(20, "IDF015")]           # 0.4 mm (Table 9 prints IDF016)
    dot_radial: Annotated[int, S(21, "IDF016")]      # 0.001 mm/s (Table 9 prints IDF015)
    dot_along: Annotated[int, S(19, "IDF017")]       # 0.004 mm/s
    dot_cross: Annotated[int, S(19, "IDF018")]       # 0.004 mm/s


@dataclass(frozen=True, slots=True)
class IgsOrbit:
    """IGM01 SSR Orbit Correction. IGS SSR Tables 8 and 9 (79 + 135·NS bits)."""

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    regional: Annotated[int, U(1, "IDF006")]         # Global/Regional CRS: 0 ITRF, 1 regional
    satellite_count: Annotated[int, U(6, "IDF010")]
    satellites: Annotated[tuple[IgsOrbitSat, ...], Group(IgsOrbitSat, count=F.satellite_count)]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class IgsClockSat:
    """IGM02 satellite part, IGS SSR Table 11 (76 bits)."""

    satellite: Annotated[int, U(6, "IDF011")]
    c0: Annotated[int, S(22, "IDF019")]              # 0.1 mm
    c1: Annotated[int, S(21, "IDF020")]              # 0.001 mm/s
    c2: Annotated[int, S(27, "IDF021")]              # 0.00002 mm/s²


@dataclass(frozen=True, slots=True)
class IgsClock:
    """IGM02 SSR Clock Correction. IGS SSR Tables 10 and 11 (78 + 76·NS bits)."""

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    satellite_count: Annotated[int, U(6, "IDF010")]
    satellites: Annotated[tuple[IgsClockSat, ...], Group(IgsClockSat, count=F.satellite_count)]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class IgsCombinedSat:
    """IGM03 satellite part, IGS SSR Table 13 (205 bits): Table 9 then Table 11's clock rows."""

    satellite: Annotated[int, U(6, "IDF011")]
    iod: Annotated[int, U(8, "IDF012")]
    radial: Annotated[int, S(22, "IDF013")]          # 0.1 mm
    along: Annotated[int, S(20, "IDF014")]           # 0.4 mm
    cross: Annotated[int, S(20, "IDF015")]           # 0.4 mm
    dot_radial: Annotated[int, S(21, "IDF016")]      # 0.001 mm/s
    dot_along: Annotated[int, S(19, "IDF017")]       # 0.004 mm/s
    dot_cross: Annotated[int, S(19, "IDF018")]       # 0.004 mm/s
    c0: Annotated[int, S(22, "IDF019")]              # 0.1 mm
    c1: Annotated[int, S(21, "IDF020")]              # 0.001 mm/s
    c2: Annotated[int, S(27, "IDF021")]              # 0.00002 mm/s²


@dataclass(frozen=True, slots=True)
class IgsCombined:
    """IGM03 SSR Combined Orbit and Clock Correction. IGS SSR Tables 12 and 13 (79 + 205·NS bits)."""

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    regional: Annotated[int, U(1, "IDF006")]
    satellite_count: Annotated[int, U(6, "IDF010")]
    satellites: Annotated[tuple[IgsCombinedSat, ...],
                          Group(IgsCombinedSat, count=F.satellite_count)]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class IgsHighRateClockSat:
    """IGM04 satellite part, IGS SSR Table 15 (28 bits)."""

    satellite: Annotated[int, U(6, "IDF011")]
    high_rate_clock: Annotated[int, S(22, "IDF022")]   # 0.1 mm


@dataclass(frozen=True, slots=True)
class IgsHighRateClock:
    """IGM04 SSR High Rate Clock Correction. IGS SSR Tables 14 and 15 (78 + 28·NS bits)."""

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    satellite_count: Annotated[int, U(6, "IDF010")]
    satellites: Annotated[tuple[IgsHighRateClockSat, ...],
                          Group(IgsHighRateClockSat, count=F.satellite_count)]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class IgsCodeBiasSignal:
    """IGM05 code specific part, IGS SSR Table 18 (19 bits)."""

    signal: Annotated[int, U(5, "IDF024")]           # IGS_SIGNALS
    bias: Annotated[int, S(14, "IDF025")]            # 0.01 m


@dataclass(frozen=True, slots=True)
class IgsCodeBiasSat:
    """IGM05 satellite specific part, IGS SSR Table 17 (11 bits), and its code biases."""

    satellite: Annotated[int, U(6, "IDF011")]
    bias_count: Annotated[int, U(5, "IDF023")]
    biases: Annotated[tuple[IgsCodeBiasSignal, ...],
                      Group(IgsCodeBiasSignal, count=F.bias_count)]


@dataclass(frozen=True, slots=True)
class IgsCodeBias:
    """IGM05 SSR Code Bias. IGS SSR Tables 16 to 18 (78 + 11·NS + 19·ΣNCB bits)."""

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    satellite_count: Annotated[int, U(6, "IDF010")]
    satellites: Annotated[tuple[IgsCodeBiasSat, ...],
                          Group(IgsCodeBiasSat, count=F.satellite_count)]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class IgsPhaseBiasSignal:
    """IGM06 phase specific part, IGS SSR Table 21 (32 bits)."""

    signal: Annotated[int, U(5, "IDF024")]           # IGS_SIGNALS
    integer: Annotated[int, U(1, "IDF029")]          # Signal Integer Indicator
    wide_lane: Annotated[int, U(2, "IDF030")]        # 0b10 group one, 0b01 two, 0b11 three
    discontinuity: Annotated[int, U(4, "IDF031")]    # Signal Discontinuity Counter
    bias: Annotated[int, S(20, "IDF028")]            # 0.0001 m


@dataclass(frozen=True, slots=True)
class IgsPhaseBiasSat:
    """IGM06 satellite specific part, IGS SSR Table 20 (28 bits), and its phase biases."""

    satellite: Annotated[int, U(6, "IDF011")]
    bias_count: Annotated[int, U(5, "IDF023")]
    yaw: Annotated[int, U(9, "IDF026")]              # 1/256 semicircle
    yaw_rate: Annotated[int, S(8, "IDF027")]         # 1/8192 semicircle/s
    biases: Annotated[tuple[IgsPhaseBiasSignal, ...],
                      Group(IgsPhaseBiasSignal, count=F.bias_count)]


@dataclass(frozen=True, slots=True)
class IgsPhaseBias:
    """IGM06 SSR Phase Bias. IGS SSR Tables 19 to 21 (80 + 28·NS + 32·ΣNPB bits)."""

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    dispersive: Annotated[int, U(1, "IDF032")]       # Dispersive Bias Consistency Indicator
    mw: Annotated[int, U(1, "IDF033")]               # MW Consistency Indicator
    satellite_count: Annotated[int, U(6, "IDF010")]
    satellites: Annotated[tuple[IgsPhaseBiasSat, ...],
                          Group(IgsPhaseBiasSat, count=F.satellite_count)]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class IgsUraSat:
    """IGM07 satellite part, IGS SSR Table 23 (12 bits)."""

    satellite: Annotated[int, U(6, "IDF011")]
    ura: Annotated[int, U(6, "IDF034")]              # URA_CLASS (bits 5-3), URA_VALUE (2-0)


@dataclass(frozen=True, slots=True)
class IgsUra:
    """IGM07 SSR URA. IGS SSR Tables 22 and 23 (78 + 12·NS bits)."""

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    satellite_count: Annotated[int, U(6, "IDF010")]
    satellites: Annotated[tuple[IgsUraSat, ...], Group(IgsUraSat, count=F.satellite_count)]
    extension: Ext = None


# IM201 coefficient counts (module docstring): N = IDF037 + 1, M = IDF038 + 1,
# M taken as min(M, N).
_N = F.degree_minus_1 + 1
_M = F.order_minus_1 + 1
_MN = _M - (_M - _N) * (_M > _N)
_COSINE = ((_N + 1) * (_N + 2) - (_N - _MN) * (_N - _MN + 1)) // 2
_SINE = _COSINE - (_N + 1)


@dataclass(frozen=True, slots=True)
class IgsVtecLayer:
    """One ionospheric layer of IM201: IGS SSR Table 25 (16 bits), then Tables 26 and 27.

    ``cosine`` holds C(n,m) for m = 0 to M and n = m to N, ``sine`` S(n,m)
    for m = 1 to M and n = m to N, in that order (section 8.4.1).
    """

    height: Annotated[int, U(8, "IDF036")]           # 10 km
    degree_minus_1: Annotated[int, U(4, "IDF037")]   # N - 1
    order_minus_1: Annotated[int, U(4, "IDF038")]    # M - 1
    cosine: Annotated[tuple[int, ...], S(16, "IDF039", count=_COSINE)]   # 0.005 TECU
    sine: Annotated[tuple[int, ...], S(16, "IDF040", count=_SINE)]       # 0.005 TECU


@dataclass(frozen=True, slots=True)
class IgsVtec:
    """IM201 SSR Ionosphere VTEC Spherical Harmonics. IGS SSR Tables 24 to 27.

    83 + 16·NIL + 16·NHC bits (Table 6), NIL = IDF035 + 1 layers and NHC
    coefficients over all layers.
    """

    number: Annotated[int, U(12, "DF002")]
    version: Annotated[int, U(3, "IDF001")]
    subtype: Annotated[int, U(8, "IDF002")]
    epoch: Annotated[int, U(20, "IDF003")]
    interval: Annotated[int, U(4, "IDF004")]
    multiple: Annotated[int, U(1, "IDF005")]
    iod_ssr: Annotated[int, U(4, "IDF007")]
    provider: Annotated[int, U(16, "IDF008")]
    solution: Annotated[int, U(4, "IDF009")]
    quality: Annotated[int, U(9, "IDF041")]          # 0.05 TECU; 0 unknown
    layers_minus_1: Annotated[int, U(2, "IDF035")]   # NIL - 1
    layers: Annotated[tuple[IgsVtecLayer, ...],
                      Group(IgsVtecLayer, count=F.layers_minus_1 + 1)]
    extension: Ext = None


_IGM_CLASSES = (IgsOrbit, IgsClock, IgsCombined, IgsHighRateClock, IgsCodeBias, IgsPhaseBias,
                IgsUra)

# IDF002 sub-type to its table (Table 5).
IGS_MESSAGES: dict[int, type] = {
    **{first + i: cls for first in IGS_SYSTEMS.values() for i, cls in enumerate(_IGM_CLASSES)},
    VTEC: IgsVtec,
}


def igs_subtype(payload: bytes) -> int | None:
    """IDF002 of a 4076 message (bits 15 to 22), or ``None`` if it is shorter than 23 bits."""
    if len(payload) < 3:
        return None
    return ((payload[1] & 1) << 7) | (payload[2] >> 1)
