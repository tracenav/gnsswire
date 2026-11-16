"""Broadcast ephemerides: 1019 (GPS), 1020 (GLONASS), 1042 (BeiDou), 1044 (QZSS), 1045, 1046.

1045 and 1046 are Galileo F/NAV and I/NAV. Each class is the field table of
RTCM 10403.3 cited in its docstring, row for row and in order; the DF numbers
are the rows' tags. The standard keeps the widths, scale factors and units of
each system's interface document (sections 3.5.8, 3.5.9, 3.5.18, 3.5.19 and
3.5.20), so a field here is the integer the satellite broadcast, unscaled:
``sqrt_a`` of 1019 counts 2^-19 m^1/2 as in IS-GPS-200N Table 20-III (unchanged by
IRN-IS-200N-003 and IRN-IS-200N-004), and so on.

1041 (NavIC/IRNSS) and 1043 (SBAS) have no table: RTCM 10403.3 as staged
(2016-10-07) does not define them, and the amendment or edition that does is
not at hand. They raise ``Unsupported``.

Data types are the standard's: ``int(n)`` is two's complement (``S``),
``intS(n)`` sign-magnitude (``SM``, the GLONASS fields of 1020), ``uint(n)``
and ``bit(n)`` unsigned (``U``). A sign-magnitude negative zero, which the
GLONASS ICD does not exclude, decodes to ``gnsswire.bits.NEGATIVE_ZERO`` and
re-encodes as it came.

``extension`` is what follows the table in the message (``_station``).
"""

from dataclasses import dataclass
from typing import Annotated

from gnsswire.bits import SM, S, U

from ._station import Ext


@dataclass(frozen=True, slots=True)
class Msg1019:
    """GPS satellite ephemeris. RTCM 10403.3 Table 3.5-21 (488 bits)."""

    number: Annotated[int, U(12, "DF002")]
    satellite: Annotated[int, U(6, "DF009")]
    week: Annotated[int, U(10, "DF076")]
    accuracy: Annotated[int, U(4, "DF077")]
    l2_code: Annotated[int, U(2, "DF078")]
    idot: Annotated[int, S(14, "DF079")]
    iode: Annotated[int, U(8, "DF071")]
    toc: Annotated[int, U(16, "DF081")]
    af2: Annotated[int, S(8, "DF082")]
    af1: Annotated[int, S(16, "DF083")]
    af0: Annotated[int, S(22, "DF084")]
    iodc: Annotated[int, U(10, "DF085")]
    crs: Annotated[int, S(16, "DF086")]
    delta_n: Annotated[int, S(16, "DF087")]
    m0: Annotated[int, S(32, "DF088")]
    cuc: Annotated[int, S(16, "DF089")]
    e: Annotated[int, U(32, "DF090")]
    cus: Annotated[int, S(16, "DF091")]
    sqrt_a: Annotated[int, U(32, "DF092")]
    toe: Annotated[int, U(16, "DF093")]
    cic: Annotated[int, S(16, "DF094")]
    omega0: Annotated[int, S(32, "DF095")]
    cis: Annotated[int, S(16, "DF096")]
    i0: Annotated[int, S(32, "DF097")]
    crc: Annotated[int, S(16, "DF098")]
    omega: Annotated[int, S(32, "DF099")]
    omega_dot: Annotated[int, S(24, "DF100")]
    tgd: Annotated[int, S(8, "DF101")]
    health: Annotated[int, U(6, "DF102")]
    l2p_data: Annotated[int, U(1, "DF103")]
    fit_interval: Annotated[int, U(1, "DF137")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1020:
    """GLONASS satellite ephemeris. RTCM 10403.3 Table 3.5-22 (360 bits).

    The last row, seven reserved bits, has no DF number in the table.
    """

    number: Annotated[int, U(12, "DF002")]
    satellite: Annotated[int, U(6, "DF038")]
    channel: Annotated[int, U(5, "DF040")]
    almanac_health: Annotated[int, U(1, "DF104")]
    almanac_health_available: Annotated[int, U(1, "DF105")]
    p1: Annotated[int, U(2, "DF106")]
    tk: Annotated[int, U(12, "DF107")]
    bn_msb: Annotated[int, U(1, "DF108")]
    p2: Annotated[int, U(1, "DF109")]
    tb: Annotated[int, U(7, "DF110")]
    x_dot: Annotated[int, SM(24, "DF111")]
    x: Annotated[int, SM(27, "DF112")]
    x_ddot: Annotated[int, SM(5, "DF113")]
    y_dot: Annotated[int, SM(24, "DF114")]
    y: Annotated[int, SM(27, "DF115")]
    y_ddot: Annotated[int, SM(5, "DF116")]
    z_dot: Annotated[int, SM(24, "DF117")]
    z: Annotated[int, SM(27, "DF118")]
    z_ddot: Annotated[int, SM(5, "DF119")]
    p3: Annotated[int, U(1, "DF120")]
    gamma: Annotated[int, SM(11, "DF121")]
    p: Annotated[int, U(2, "DF122")]
    ln_third: Annotated[int, U(1, "DF123")]
    tau: Annotated[int, SM(22, "DF124")]
    delta_tau: Annotated[int, SM(5, "DF125")]
    en: Annotated[int, U(5, "DF126")]
    p4: Annotated[int, U(1, "DF127")]
    ft: Annotated[int, U(4, "DF128")]
    nt: Annotated[int, U(11, "DF129")]
    m: Annotated[int, U(2, "DF130")]
    additional: Annotated[int, U(1, "DF131")]
    na: Annotated[int, U(11, "DF132")]
    tau_c: Annotated[int, SM(32, "DF133")]
    n4: Annotated[int, U(5, "DF134")]
    tau_gps: Annotated[int, SM(22, "DF135")]
    ln_fifth: Annotated[int, U(1, "DF136")]
    reserved: Annotated[int, U(7)]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1044:
    """QZSS satellite ephemeris. RTCM 10403.3 Table 3.5-112 (485 bits).

    The rows follow IS-QZSS, which the table cites for every field; that
    document is not staged here, and the fields are kept as the table's
    integers like the others.
    """

    number: Annotated[int, U(12, "DF002")]
    satellite: Annotated[int, U(4, "DF429")]
    toc: Annotated[int, U(16, "DF430")]
    af2: Annotated[int, S(8, "DF431")]
    af1: Annotated[int, S(16, "DF432")]
    af0: Annotated[int, S(22, "DF433")]
    iode: Annotated[int, U(8, "DF434")]
    crs: Annotated[int, S(16, "DF435")]
    delta_n: Annotated[int, S(16, "DF436")]
    m0: Annotated[int, S(32, "DF437")]
    cuc: Annotated[int, S(16, "DF438")]
    e: Annotated[int, U(32, "DF439")]
    cus: Annotated[int, S(16, "DF440")]
    sqrt_a: Annotated[int, U(32, "DF441")]
    toe: Annotated[int, U(16, "DF442")]
    cic: Annotated[int, S(16, "DF443")]
    omega0: Annotated[int, S(32, "DF444")]
    cis: Annotated[int, S(16, "DF445")]
    i0: Annotated[int, S(32, "DF446")]
    crc: Annotated[int, S(16, "DF447")]
    omega: Annotated[int, S(32, "DF448")]
    omega_dot: Annotated[int, S(24, "DF449")]
    idot: Annotated[int, S(14, "DF450")]
    l2_code: Annotated[int, U(2, "DF451")]
    week: Annotated[int, U(10, "DF452")]
    accuracy: Annotated[int, U(4, "DF453")]
    health: Annotated[int, U(6, "DF454")]
    tgd: Annotated[int, S(8, "DF455")]
    iodc: Annotated[int, U(10, "DF456")]
    fit_interval: Annotated[int, U(1, "DF457")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1042:
    """BeiDou satellite ephemeris. RTCM 10403.3 Table 3.5-113 (511 bits)."""

    number: Annotated[int, U(12, "DF002")]
    satellite: Annotated[int, U(6, "DF488")]
    week: Annotated[int, U(13, "DF489")]
    urai: Annotated[int, U(4, "DF490")]
    idot: Annotated[int, S(14, "DF491")]
    aode: Annotated[int, U(5, "DF492")]
    toc: Annotated[int, U(17, "DF493")]
    a2: Annotated[int, S(11, "DF494")]
    a1: Annotated[int, S(22, "DF495")]
    a0: Annotated[int, S(24, "DF496")]
    aodc: Annotated[int, U(5, "DF497")]
    crs: Annotated[int, S(18, "DF498")]
    delta_n: Annotated[int, S(16, "DF499")]
    m0: Annotated[int, S(32, "DF500")]
    cuc: Annotated[int, S(18, "DF501")]
    e: Annotated[int, U(32, "DF502")]
    cus: Annotated[int, S(18, "DF503")]
    sqrt_a: Annotated[int, U(32, "DF504")]
    toe: Annotated[int, U(17, "DF505")]
    cic: Annotated[int, S(18, "DF506")]
    omega0: Annotated[int, S(32, "DF507")]
    cis: Annotated[int, S(18, "DF508")]
    i0: Annotated[int, S(32, "DF509")]
    crc: Annotated[int, S(18, "DF510")]
    omega: Annotated[int, S(32, "DF511")]
    omega_dot: Annotated[int, S(24, "DF512")]
    tgd1: Annotated[int, S(10, "DF513")]
    tgd2: Annotated[int, S(10, "DF514")]
    health: Annotated[int, U(1, "DF515")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1045:
    """Galileo F/NAV satellite ephemeris. RTCM 10403.3 Table 3.5-110 (496 bits)."""

    number: Annotated[int, U(12, "DF002")]
    satellite: Annotated[int, U(6, "DF252")]
    week: Annotated[int, U(12, "DF289")]
    iodnav: Annotated[int, U(10, "DF290")]
    sisa: Annotated[int, U(8, "DF291")]
    idot: Annotated[int, S(14, "DF292")]
    toc: Annotated[int, U(14, "DF293")]
    af2: Annotated[int, S(6, "DF294")]
    af1: Annotated[int, S(21, "DF295")]
    af0: Annotated[int, S(31, "DF296")]
    crs: Annotated[int, S(16, "DF297")]
    delta_n: Annotated[int, S(16, "DF298")]
    m0: Annotated[int, S(32, "DF299")]
    cuc: Annotated[int, S(16, "DF300")]
    e: Annotated[int, U(32, "DF301")]
    cus: Annotated[int, S(16, "DF302")]
    sqrt_a: Annotated[int, U(32, "DF303")]
    toe: Annotated[int, U(14, "DF304")]
    cic: Annotated[int, S(16, "DF305")]
    omega0: Annotated[int, S(32, "DF306")]
    cis: Annotated[int, S(16, "DF307")]
    i0: Annotated[int, S(32, "DF308")]
    crc: Annotated[int, S(16, "DF309")]
    omega: Annotated[int, S(32, "DF310")]
    omega_dot: Annotated[int, S(24, "DF311")]
    bgd_e5a_e1: Annotated[int, S(10, "DF312")]
    e5a_health: Annotated[int, U(2, "DF314")]
    e5a_validity: Annotated[int, U(1, "DF315")]
    reserved: Annotated[int, U(7, "DF001")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1046:
    """Galileo I/NAV satellite ephemeris. RTCM 10403.3 Table 3.5-111 (504 bits)."""

    number: Annotated[int, U(12, "DF002")]
    satellite: Annotated[int, U(6, "DF252")]
    week: Annotated[int, U(12, "DF289")]
    iodnav: Annotated[int, U(10, "DF290")]
    sisa: Annotated[int, U(8, "DF286")]
    idot: Annotated[int, S(14, "DF292")]
    toc: Annotated[int, U(14, "DF293")]
    af2: Annotated[int, S(6, "DF294")]
    af1: Annotated[int, S(21, "DF295")]
    af0: Annotated[int, S(31, "DF296")]
    crs: Annotated[int, S(16, "DF297")]
    delta_n: Annotated[int, S(16, "DF298")]
    m0: Annotated[int, S(32, "DF299")]
    cuc: Annotated[int, S(16, "DF300")]
    e: Annotated[int, U(32, "DF301")]
    cus: Annotated[int, S(16, "DF302")]
    sqrt_a: Annotated[int, U(32, "DF303")]
    toe: Annotated[int, U(14, "DF304")]
    cic: Annotated[int, S(16, "DF305")]
    omega0: Annotated[int, S(32, "DF306")]
    cis: Annotated[int, S(16, "DF307")]
    i0: Annotated[int, S(32, "DF308")]
    crc: Annotated[int, S(16, "DF309")]
    omega: Annotated[int, S(32, "DF310")]
    omega_dot: Annotated[int, S(24, "DF311")]
    bgd_e5a_e1: Annotated[int, S(10, "DF312")]
    bgd_e5b_e1: Annotated[int, S(10, "DF313")]
    e5b_health: Annotated[int, U(2, "DF316")]
    e5b_validity: Annotated[int, U(1, "DF317")]
    e1b_health: Annotated[int, U(2, "DF287")]
    e1b_validity: Annotated[int, U(1, "DF288")]
    reserved: Annotated[int, U(2, "DF001")]
    extension: Ext = None
