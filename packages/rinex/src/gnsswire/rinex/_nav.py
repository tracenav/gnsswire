"""Navigation message files: :func:`read_nav`, :func:`write_nav`, :func:`nav_fields`.

Sources:

- RINEX 3.05 (1 December 2020): Table A5 (header), Tables A6, A8, A10, A12,
  A14, A16 and A18 (the data records of GPS, Galileo, GLONASS, QZSS, BDS,
  SBAS and NavIC/IRNSS), sections 5.4 and 6.8.
- RINEX 4.02 (1 October 2024): Table A7 (header), section 5.4.1 (the data
  record header line), Tables A9 to A11, A13, A15 to A17, A19 to A21, A23 to
  A26, A28, A30 and A31 (EPH), A33 (STO), A34 (EOP), A35 to A40 (ION),
  sections 6.3 and 6.8.
- RINEX 2.11 (10 December 2007): Tables A3 and A4 (GPS), A10 and A11
  (GLONASS), A15 and A16 (GEO).

The file structure:

- Header records as in an observation file: content in columns 1 to 60,
  the label in 61 to 80, RINEX VERSION / TYPE first and END OF HEADER last.
  They are kept as text (:class:`HeaderRecord`), unread but for the version
  and the file type.
- Data records. Each is a first line (SV / EPOCH / SV CLK in an ephemeris:
  satellite, epoch, three values) and BROADCAST ORBIT lines of up to four
  values. "All new navigation messages reuse the fixed grid of four columns
  with a width of 19 characters" (4.02 section 5.4), and the STO, EOP and
  ION messages of RINEX 4 are on the same grid, so one pair of record
  classes holds every message: :class:`NavEpoch` and :class:`NavLine` in
  RINEX 3 and 4 (``A1,I2.2,1X,I4,5(1X,I2.2),3D19.12`` and ``4X,4D19.12``),
  :class:`NavEpoch2` and :class:`NavLine2` in RINEX 2
  (``I2,1X,I2.2,4(1X,I2),F5.1,3D19.12`` and ``3X,4D19.12``). In RINEX 4 a
  record is preceded by its header line, ``> EPH G01 LNAV``
  (:class:`NavType`).

What a value means is given by the message's table, transcribed below as
names (``NAV2``, ``NAV3``, ``NAV4_EPH``, ``NAV4_STO``, ``NAV4_EOP``,
``NAV4_ION``); :func:`nav_fields` gives a record's values by those names.
Values are text, as everywhere in this codec; :func:`real` gives one as an
exact decimal.

Readings this codec makes where the documents leave room:

- A record's lines are found by their shape, not counted: in RINEX 3 a
  line with a character in column 1 starts a record, in RINEX 2 one with a
  character in columns 1 to 2, in RINEX 4 the line after a ``>`` line; the
  lines up to the next start are its BROADCAST ORBIT lines. The number
  found must then be the number its table gives.
- GLONASS records of a RINEX 3 file have three or four BROADCAST ORBIT
  lines: 3.05 added the fourth ("Added a 5th line to the GLONASS navigation
  message", revision history, 1-Sep-2020), and files of 3.00 to 3.04 have
  three. The version in the header is not used to choose.
- GLONASS L1OC and L3OC (4.02 Tables A16 and A17) end with BROADCAST ORBIT
  - 8 as URAI_orb, URAI_clk, a spare and the transmission time; the
  example of Table A18 prints three values on that line, the transmission
  time third. The names follow the tables: in a record written as the
  example is, the third value has no name (it is in ``record.values``) and
  ``t_tm`` is ``""``.
- A RINEX 4 record whose type has no table here (a record type other than
  EPH, STO, EOP and ION, or an EPH or ION message type or subtype that
  4.02 does not define) is kept whole on the same grid, with no check of
  its values or of its number of lines; :func:`nav_fields` raises
  :class:`Unsupported` for it. STO and EOP records have one layout each
  (Tables A33, A34) whatever their message type: Table A41 prints an STO
  record of type ``LEG``, which Table 21 does not list.
- Spare fields, and fields past those a table names (RINEX 4 drops the
  spares that end a line in RINEX 3), are kept and not checked. A named
  value must be blank or a number: digits with an optional point, sign and
  exponent after ``D``, ``E``, ``d`` or ``e`` (3.05 section 6.8). Exponents
  of other than two digits are accepted, though the documents require two.
- The epoch fields must be numbers of their formats; in RINEX 2, 3 and 4
  EPH records the satellite number must be one (``A1,I2.2``, with ``A1,I2``
  as the QZSS tables print it also accepted; ``I2`` in RINEX 2), and in a
  RINEX 4 EPH record the same satellite as in its header line. STO, EOP and
  ION records have blanks there (``4X,I4``).
- The format of BROADCAST ORBIT - 5 in Table A31 of 4.02 (NavIC L1NV) is
  printed ``2X,E19.12,...``; it is read as ``4X`` like every other line, as
  the example in Table A32 has it.
- Table A39 of 4.02 (NavIC NeQuick-N) labels the fourth value of the
  second and third regions' boundary lines "Latitude max" where the first
  region has "MOPID max"; all three are named ``mopid_max``.
- BDS ``CNVX`` ION records are read as BDGIM (Table A37), the only table
  that names BDS with that message type; Klobuchar records (Table A35) are
  G, J and I ``LNAV``, G and J ``CNVX`` and C ``D1D2``, with any subtype.
- Lines end in LF or CR LF, the same throughout a file, and both are kept,
  as in an observation file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

from ._obs import END_OF_HEADER, SYSTEMS, _header_line, _header_record, _label, _lines
from ._records import Col, Error, HeaderRecord, Invalid, Unsupported, cut, join

# ---- records -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NavType:
    """The data record header line of RINEX 4 (4.02 section 5.4.1), after its ``>``.

    ``> EPH G01 LNAV``: the record type (EPH, STO, EOP, ION; Table 19), the
    source (system letter and, when given, satellite number), the message
    type (Tables 20 and 21; ``A2`` for BDS D1 and D2) and the subtype
    (Tables 22 to 25), "all the fields ... separated by one blank". Fields
    the line ends before are ``""``.
    """

    kind: Annotated[str, Col(4, "1X,A3")]
    source: Annotated[str, Col(4, "1X,A3")]
    message: Annotated[str, Col(5, "1X,A4")]
    subtype: Annotated[str, Col(5, "1X,A4")]


@dataclass(frozen=True, slots=True)
class NavEpoch:
    """The first line of a RINEX 3 or 4 record: SV / EPOCH / SV CLK and its like.

    ``sat`` is the satellite number of an ephemeris (``G06``) and blank in
    STO, EOP and ION records, whose format starts ``4X,I4``. ``v1`` to
    ``v3`` are the three values of the line: ``3D19.12`` (``3E19.12`` in
    4.02), or ``1X,A18`` each in an STO record.
    """

    sat: Annotated[str, Col(3, "A1,I2.2")]
    year: Annotated[str, Col(5, "1X,I4")]
    month: Annotated[str, Col(3, "1X,I2.2")]
    day: Annotated[str, Col(3, "1X,I2.2")]
    hour: Annotated[str, Col(3, "1X,I2.2")]
    minute: Annotated[str, Col(3, "1X,I2.2")]
    second: Annotated[str, Col(3, "1X,I2.2")]
    v1: Annotated[str, Col(19, "D19.12")]
    v2: Annotated[str, Col(19, "D19.12")]
    v3: Annotated[str, Col(19, "D19.12")]


@dataclass(frozen=True, slots=True)
class NavLine:
    """A BROADCAST ORBIT line of RINEX 3 or 4 (or STO, EOP, ION message line)."""

    indent: Annotated[str, Col(4, "4X")]
    v1: Annotated[str, Col(19, "D19.12")]
    v2: Annotated[str, Col(19, "D19.12")]
    v3: Annotated[str, Col(19, "D19.12")]
    v4: Annotated[str, Col(19, "D19.12")]


@dataclass(frozen=True, slots=True)
class NavEpoch2:
    """PRN / EPOCH / SV CLK of RINEX 2 (2.11 Tables A4, A11, A16).

    ``sat`` is the PRN (GPS), the slot number (GLONASS) or PRN - 100 (GEO)
    by the file's type; the year has two digits.
    """

    sat: Annotated[str, Col(2, "I2")]
    year: Annotated[str, Col(3, "1X,I2.2")]
    month: Annotated[str, Col(3, "1X,I2")]
    day: Annotated[str, Col(3, "1X,I2")]
    hour: Annotated[str, Col(3, "1X,I2")]
    minute: Annotated[str, Col(3, "1X,I2")]
    second: Annotated[str, Col(5, "F5.1")]
    v1: Annotated[str, Col(19, "D19.12")]
    v2: Annotated[str, Col(19, "D19.12")]
    v3: Annotated[str, Col(19, "D19.12")]


@dataclass(frozen=True, slots=True)
class NavLine2:
    """A BROADCAST ORBIT line of RINEX 2."""

    indent: Annotated[str, Col(3, "3X")]
    v1: Annotated[str, Col(19, "D19.12")]
    v2: Annotated[str, Col(19, "D19.12")]
    v3: Annotated[str, Col(19, "D19.12")]
    v4: Annotated[str, Col(19, "D19.12")]


@dataclass(frozen=True, slots=True)
class NavRecord:
    """One navigation data record: its lines, each as the text of its columns.

    ``type`` is the record's header line in RINEX 4 and ``None`` in RINEX 2
    and 3; ``epoch`` and ``lines`` are :class:`NavEpoch` and
    :class:`NavLine` (:class:`NavEpoch2` and :class:`NavLine2` in RINEX 2).
    :func:`nav_fields` gives the values by name.
    """

    type: NavType | None
    epoch: NavEpoch | NavEpoch2
    lines: tuple[NavLine | NavLine2, ...]

    @property
    def values(self) -> tuple[str, ...]:
        """Every value of the record in order: three of the first line, four per line."""
        e = self.epoch
        return (e.v1, e.v2, e.v3, *(v for ln in self.lines for v in (ln.v1, ln.v2, ln.v3, ln.v4)))


@dataclass(frozen=True, slots=True)
class NavFile:
    """A whole navigation message file."""

    header: tuple[HeaderRecord, ...]   # RINEX VERSION / TYPE to END OF HEADER
    records: tuple[NavRecord, ...]
    newline: str = "\n"                # "\n" or "\r\n"
    final_newline: bool = True         # whether the last line ends with ``newline``

    @property
    def version(self) -> str:
        """The format version, columns 1 to 9 of RINEX VERSION / TYPE, stripped."""
        return self.header[0].content[:9].strip()

    @property
    def file_type(self) -> str:
        """Column 21 of RINEX VERSION / TYPE: ``N``, or in RINEX 2 ``N``, ``G`` or ``H``."""
        return self.header[0].content[20:21]


# ---- message tables ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NavLayout:
    """The names of a message's values, as its table orders them.

    ``first`` names the three values of the first line and ``lines`` those
    of each BROADCAST ORBIT line; ``None`` is a spare, and a line a table
    ends early has fewer than four names. ``text`` holds the names of
    values that are character fields. ``also`` lists other numbers of
    lines a record may have (GLONASS in RINEX 3: three, before 3.05).
    """

    source: str
    first: tuple[str | None, ...]
    lines: tuple[tuple[str | None, ...], ...]
    text: frozenset[str] = frozenset()
    also: tuple[int, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(n for group in (self.first, *self.lines) for n in group if n is not None)


_CLOCK = ("clock_bias", "clock_drift", "clock_drift_rate")
# BROADCAST ORBIT 2 and 4, alike in every Keplerian message.
_ORBIT2 = ("cuc", "e", "cus", "sqrt_a")
_ORBIT4 = ("i0", "crc", "omega", "omega_dot")
_TOE3 = ("toe", "cic", "omega0", "cis")


def _kepler(iod: str) -> tuple[tuple[str | None, ...], ...]:
    """BROADCAST ORBIT 1 to 4 of the legacy messages; ``iod`` names the first value."""
    return ((iod, "crs", "delta_n", "m0"), _ORBIT2, _TOE3, _ORBIT4)


def _cnav(third: tuple[str, ...]) -> tuple[tuple[str | None, ...], ...]:
    """BROADCAST ORBIT 1 to 4 of the CNAV family; ``third`` is line 3."""
    return (("a_dot", "crs", "delta_n0", "m0"), _ORBIT2, third, _ORBIT4)


_TOP3 = ("t_op", "cic", "omega0", "cis")
_GLONASS = (("x", "x_dot", "x_acc", "health"),
            ("y", "y_dot", "y_acc", "freq_num"),
            ("z", "z_dot", "z_acc", "age"))
_GLONASS4 = ("status_flags", "group_delay", "urai", "health_flags")
_GLONASS_CLOCK = ("clock_bias", "freq_bias", "frame_time")
_SBAS = (("x", "x_dot", "x_acc", "health"),
         ("y", "y_dot", "y_acc", "accuracy"),
         ("z", "z_dot", "z_acc", "iodn"))
_SBAS_CLOCK = ("clock_bias", "freq_bias", "t_tm")
_GPS56 = (("idot", "l2_codes", "week", "l2p_flag"), ("accuracy", "health", "tgd", "iodc"))
_GAL56 = (("idot", "data_sources", "week", None),
          ("sisa", "health", "bgd_e5a_e1", "bgd_e5b_e1"))
_BDS56 = (("idot", None, "week", None), ("accuracy", "sath1", "tgd1", "tgd2"))
_IRN56 = (("idot", None, "week", None), ("accuracy", "health", "tgd", None))

# RINEX 2.11, by file type (column 21 of RINEX VERSION / TYPE).
NAV2: dict[str, NavLayout] = {
    "N": NavLayout("RINEX 2.11 Table A4", _CLOCK, (
        *_kepler("iode"), *_GPS56, ("t_tm", "fit_interval", None, None))),
    "G": NavLayout("RINEX 2.11 Table A11", _GLONASS_CLOCK, _GLONASS),
    "H": NavLayout("RINEX 2.11 Table A16", _SBAS_CLOCK, _SBAS),
}
# The system letter of the satellites of a RINEX 2 file, by its type.
NAV2_SYSTEM = {"N": "G", "G": "R", "H": "S"}

# RINEX 3.05, by satellite system.
NAV3: dict[str, NavLayout] = {
    "G": NavLayout("RINEX 3.05 Table A6", _CLOCK, (
        *_kepler("iode"), *_GPS56, ("t_tm", "fit_interval", None, None))),
    "E": NavLayout("RINEX 3.05 Table A8", _CLOCK, (
        *_kepler("iodnav"), *_GAL56, ("t_tm", None, None, None))),
    "R": NavLayout("RINEX 3.05 Table A10", _GLONASS_CLOCK, (*_GLONASS, _GLONASS4), also=(3,)),
    "J": NavLayout("RINEX 3.05 Table A12", _CLOCK, (
        *_kepler("iode"), *_GPS56, ("t_tm", "fit_flag", None, None))),
    "C": NavLayout("RINEX 3.05 Table A14", _CLOCK, (
        *_kepler("aode"), *_BDS56, ("t_tm", "aodc", None, None))),
    "S": NavLayout("RINEX 3.05 Table A16", _SBAS_CLOCK, _SBAS),
    "I": NavLayout("RINEX 3.05 Table A18", _CLOCK, (
        *_kepler("iodec"), *_IRN56, ("t_tm", None, None, None))),
}

_CNAV567 = (("idot", "delta_n0_dot", "urai_ned0", "urai_ned1"),
            ("urai_ed", "health", "tgd", "urai_ned2"),
            ("isc_l1ca", "isc_l2c", "isc_l5i5", "isc_l5q5"))
_CNAV_LAST = ("t_tm", "wn_op", "flags")
_CNV2_8 = ("isc_l1cd", "isc_l1cp")
_BDS_CNAV56 = (("idot", "delta_n0_dot", "sat_type", "t_op"),
               ("sisai_oe", "sisai_ocb", "sisai_oc1", "sisai_oc2"))
_BDS_CNAV8 = ("sismai", "health", "integrity_flags", "iodc")
_BDS_CNAV9 = ("t_tm", None, None, "iode")


def _glonass_cdma(delay: str) -> tuple[tuple[str | None, ...], ...]:
    return (("x", "x_dot", "x_acc", "health"),
            ("y", "y_dot", "y_acc", "validity"),
            ("z", "z_dot", "z_acc", delay),
            ("sat_type", "source_flags", "aode", "aodc"),
            ("attitude_flag", "t_in", "tau1", "tau2"),
            ("yaw", "sign_flag", "yaw_rate", "yaw_acc"),
            ("max_yaw_rate", "pc_x", "pc_y", "pc_z"),
            ("urai_orb", "urai_clk", None, "t_tm"))


# RINEX 4.02 EPH records, by (satellite system, message type).
NAV4_EPH: dict[tuple[str, str], NavLayout] = {
    ("G", "LNAV"): NavLayout("RINEX 4.02 Table A9", _CLOCK, (
        *_kepler("iode"), *_GPS56, ("t_tm", "fit_interval"))),
    ("G", "CNAV"): NavLayout("RINEX 4.02 Table A10", _CLOCK, (
        *_cnav(_TOP3), *_CNAV567, _CNAV_LAST)),
    ("G", "CNV2"): NavLayout("RINEX 4.02 Table A11", _CLOCK, (
        *_cnav(_TOP3), *_CNAV567, _CNV2_8, _CNAV_LAST)),
    ("E", "INAV"): NavLayout("RINEX 4.02 Table A13", _CLOCK, (
        *_kepler("iodnav"), _GAL56[0][:3], _GAL56[1], ("t_tm",))),
    ("E", "FNAV"): NavLayout("RINEX 4.02 Table A13", _CLOCK, (
        *_kepler("iodnav"), _GAL56[0][:3], _GAL56[1], ("t_tm",))),
    ("R", "FDMA"): NavLayout("RINEX 4.02 Table A15", _GLONASS_CLOCK, (*_GLONASS, _GLONASS4)),
    ("R", "L1OC"): NavLayout("RINEX 4.02 Table A16", _CLOCK, _glonass_cdma("tgd_l2ocp")),
    ("R", "L3OC"): NavLayout("RINEX 4.02 Table A17", _CLOCK, _glonass_cdma("isc_l3ocp")),
    ("J", "LNAV"): NavLayout("RINEX 4.02 Table A19", _CLOCK, (
        *_kepler("iode"), ("idot", "status_flags", "week", "l2p_flag"), _GPS56[1],
        ("t_tm", "fit_flag"))),
    ("J", "CNAV"): NavLayout("RINEX 4.02 Table A20", _CLOCK, (
        *_cnav(_TOP3), *_CNAV567, _CNAV_LAST)),
    ("J", "CNV2"): NavLayout("RINEX 4.02 Table A21", _CLOCK, (
        *_cnav(_TOP3), *_CNAV567, _CNV2_8, _CNAV_LAST)),
    ("C", "D1"): NavLayout("RINEX 4.02 Table A23", _CLOCK, (
        *_kepler("aode"), *_BDS56, ("t_tm", "aodc"))),
    ("C", "D2"): NavLayout("RINEX 4.02 Table A23", _CLOCK, (
        *_kepler("aode"), *_BDS56, ("t_tm", "aodc"))),
    ("C", "CNV1"): NavLayout("RINEX 4.02 Table A24", _CLOCK, (
        *_cnav(_TOE3), *_BDS_CNAV56, ("isc_b1cd", None, "tgd_b1cp", "tgd_b2ap"),
        _BDS_CNAV8, _BDS_CNAV9)),
    ("C", "CNV2"): NavLayout("RINEX 4.02 Table A25", _CLOCK, (
        *_cnav(_TOE3), *_BDS_CNAV56, (None, "isc_b2ad", "tgd_b1cp", "tgd_b2ap"),
        _BDS_CNAV8, _BDS_CNAV9)),
    ("C", "CNV3"): NavLayout("RINEX 4.02 Table A26", _CLOCK, (
        *_cnav(_TOE3), *_BDS_CNAV56, ("sismai", "health", "integrity_flags", "tgd_b2bi"),
        ("t_tm",))),
    ("S", "SBAS"): NavLayout("RINEX 4.02 Table A28", _SBAS_CLOCK, _SBAS),
    ("I", "LNAV"): NavLayout("RINEX 4.02 Table A30", _CLOCK, (
        *_kepler("iodec"), *_IRN56, ("t_tm",))),
    ("I", "L1NV"): NavLayout("RINEX 4.02 Table A31", _CLOCK, (
        *_cnav(("iodec", "cic", "omega0", "cis")),
        ("idot", "delta_n0_dot", None, "rsf"),
        ("urai", "health", "tgd_l1p_l5", "tgd_s_l5"),
        ("isc_s_l1p", "isc_l1d_l1p", "isc_l1p_s", "isc_l1d_s"),
        ("t_tm",))),
}

# RINEX 4.02 STO and EOP records: one layout each, whatever the source.
NAV4_STO = NavLayout("RINEX 4.02 Table A33", ("offset", "sbas_id", "utc_id"),
                     (("t_tm", "a0", "a1", "a2"),),
                     text=frozenset({"offset", "sbas_id", "utc_id"}))
NAV4_EOP = NavLayout("RINEX 4.02 Table A34", ("xp", "xp_dot", "xp_dot2"), (
    (None, "yp", "yp_dot", "yp_dot2"), ("t_tm", "dut1", "dut1_dot", "dut1_dot2")))

_KLOBUCHAR = NavLayout("RINEX 4.02 Table A35", ("alpha0", "alpha1", "alpha2"), (
    ("alpha3", "beta0", "beta1", "beta2"), ("beta3",)))


def _region(n: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return ((f"a0_{n}", f"a1_{n}", f"a2_{n}", f"idf_{n}"),
            (f"lon_min_{n}", f"lon_max_{n}", f"mopid_min_{n}", f"mopid_max_{n}"))


# RINEX 4.02 ION records, by (satellite system, message type, subtype); a
# subtype of "*" stands for any.
NAV4_ION: dict[tuple[str, str, str], NavLayout] = {
    ("G", "LNAV", "*"): _KLOBUCHAR,
    ("G", "CNVX", "*"): _KLOBUCHAR,
    ("J", "LNAV", "*"): _KLOBUCHAR,
    ("J", "CNVX", "*"): _KLOBUCHAR,
    ("I", "LNAV", "*"): _KLOBUCHAR,
    ("C", "D1D2", "*"): _KLOBUCHAR,
    ("E", "IFNV", "*"): NavLayout("RINEX 4.02 Table A36", ("ai0", "ai1", "ai2"),
                                  (("disturbance_flags",),)),
    ("C", "CNVX", "*"): NavLayout("RINEX 4.02 Table A37", ("alpha1", "alpha2", "alpha3"), (
        ("alpha4", "alpha5", "alpha6", "alpha7"), ("alpha8", "alpha9"))),
    ("I", "L1NV", "KLOB"): NavLayout("RINEX 4.02 Table A38", ("iodk",), (
        ("alpha0", "alpha1", "alpha2", "alpha3"), ("beta0", "beta1", "beta2", "beta3"),
        ("lon_min", "lon_max", "lat_min", "lat_max"))),
    ("I", "L1NV", "NEQN"): NavLayout("RINEX 4.02 Table A39", ("iodn",), (
        *_region(1), *_region(2), *_region(3))),
    ("R", "LXOC", "*"): NavLayout("RINEX 4.02 Table A40", ("c_a", "c_f107", "c_ap"), ()),
}

NAV_KINDS = ("EPH", "STO", "EOP", "ION")   # 4.02 Table 19
NAV_VERSIONS = ("2", "3", "4")

# ---- reading -----------------------------------------------------------------------

_REAL = re.compile(r"([+-]?)(\d*)(?:\.(\d*))?(?:[DdEe]([+-]?\d+))?")
_INT = re.compile(r" *\d+")
_F1 = re.compile(r" *\d*\.\d")
_SAT = re.compile(r"[A-Z][ \d]\d")
_SAT2 = re.compile(r"[ \d]\d")
_DATE = ("year", "month", "day", "hour", "minute", "second")


def real(field: str) -> tuple[int, int] | None:
    """A floating point field as ``(digits, exponent)``: its value is digits * 10**exponent.

    ``real("-.839701388031D-03") == (-839701388031, -15)``;
    ``real(" 1.330170780420e-04") == (1330170780420, -16)``;
    ``real("  2.0") == (20, -1)``. A blank field is ``None``. ``D``, ``E``,
    ``d`` and ``e`` are the exponent letters (3.05 section 6.8); nothing is
    rounded and no float is made.
    """
    text = field.strip()
    if not text:
        return None
    m = _REAL.fullmatch(text)
    if m is None or not (m[2] or m[3]):
        raise Error(f"{field!r} is not a number")
    digits = int(m[2] + (m[3] or ""))
    return (-digits if m[1] == "-" else digits), int(m[4] or 0) - len(m[3] or "")


def nav_type(nav: NavFile, record: NavRecord) -> tuple[str, str, str, str]:
    """``(record type, system, message type, subtype)`` of a record.

    ``("EPH", "G", "LNAV", "")`` for ``> EPH G01 LNAV``. A RINEX 2 or 3
    record is an ``"EPH"`` with no message type: its system is the letter
    of its satellite number (RINEX 3) or the one the file's type stands for
    (RINEX 2: ``N`` GPS, ``G`` GLONASS, ``H`` GEO, given as ``S``).
    """
    return _type(_major(nav), nav.file_type, record)


def _type(major: str, file_type: str, record: NavRecord) -> tuple[str, str, str, str]:
    if major == "2":
        return "EPH", NAV2_SYSTEM[file_type], "", ""
    if major == "3":
        return "EPH", record.epoch.sat[:1], "", ""
    t = record.type
    if not isinstance(t, NavType):
        raise Invalid("a RINEX 4 record needs its header line, a NavType")
    return t.kind.strip(), t.source.strip()[:1], t.message.strip(), t.subtype.strip()


def _layout(major: str, file_type: str, record: NavRecord) -> NavLayout | None:
    kind, system, message, subtype = _type(major, file_type, record)
    if major == "2":
        return NAV2[file_type]
    if major == "3":
        return NAV3.get(system)
    if kind == "EPH":
        return NAV4_EPH.get((system, message))
    if kind == "STO":
        return NAV4_STO
    if kind == "EOP":
        return NAV4_EOP
    if kind == "ION":
        return NAV4_ION.get((system, message, subtype)) or NAV4_ION.get((system, message, "*"))
    return None


def nav_fields(nav: NavFile, record: NavRecord) -> dict[str, str]:
    """The values of ``record`` by the names of its table, in the table's order.

    Each value is the text of its columns, ``""`` when the record ends
    before it; spares are left out (they are in ``record.values``). Raises
    :class:`Unsupported` for a record whose type has no table here.
    """
    layout = _layout(_major(nav), nav.file_type, record)
    if layout is None:
        raise Unsupported(f"no table for {' '.join(nav_type(nav, record)).strip()} records")
    return {name: value for name, value in _named(layout, record) if name is not None}


def _named(layout: NavLayout, record: NavRecord) -> list[tuple[str | None, str]]:
    """(name, value) for every position the layout covers, absent values as ``""``."""
    e = record.epoch
    out = list(zip(layout.first, (e.v1, e.v2, e.v3)))
    for i, names in enumerate(layout.lines):
        ln = record.lines[i] if i < len(record.lines) else None
        values = (ln.v1, ln.v2, ln.v3, ln.v4) if ln is not None else ("",) * 4
        out += zip(names, values)
    return out


def _major(nav: NavFile) -> str:
    if not nav.header or not isinstance(nav.header[0], HeaderRecord):
        raise Invalid("the header must start with RINEX VERSION / TYPE")
    return _check_version(nav.header[0])


def _check_version(header: HeaderRecord) -> str:
    if _label(header) != "RINEX VERSION / TYPE":
        raise Invalid("the first record is not RINEX VERSION / TYPE")
    version = header.content[:9].strip()
    major = version.split(".")[0]
    if major not in NAV_VERSIONS:
        raise Unsupported(f"RINEX version {version!r}: navigation files of 2.xx, 3.xx and "
                          "4.xx are implemented")
    file_type = header.content[20:21]
    if file_type not in (NAV2 if major == "2" else ("N",)):
        raise Unsupported(f"file type {file_type!r} of version {version}: not a navigation "
                          "message file")
    return major


def _check_record(major: str, file_type: str, record: NavRecord, where: str) -> None:
    """What :func:`read_nav` requires of a record beyond its columns."""
    e = record.epoch
    for name in _DATE:
        value = getattr(e, name)
        pattern = _F1 if major == "2" and name == "second" else _INT
        if not pattern.fullmatch(value):
            raise Invalid(f"{where}: {name} {value!r} is not a number of its format")
    for i, ln in enumerate(record.lines):
        if ln.indent.strip():
            raise Invalid(f"{where}: columns 1 to {len(ln.indent)} of line {i + 1} after "
                          "the first are not blank")
    kind, system, _, _ = _type(major, file_type, record)
    if major == "4":
        t = record.type
        for name in ("kind", "source", "message", "subtype"):
            value = getattr(t, name)
            if value[:1].strip():
                raise Invalid(f"{where}: the {name} of the record header line does not "
                              "follow a blank")
        if not t.kind.strip() or not t.source.strip() or not t.message.strip():
            raise Invalid(f"{where}: a record header line holds a record type, a source "
                          "and a message type")
    if major == "2":
        if not _SAT2.fullmatch(e.sat):
            raise Invalid(f"{where}: {e.sat!r} is not a satellite number (I2)")
    elif kind == "EPH":
        if not _SAT.fullmatch(e.sat) or e.sat[0] not in SYSTEMS:
            raise Invalid(f"{where}: {e.sat!r} is not a satellite number (A1,I2.2)")
        if major == "4" and e.sat != record.type.source[1:]:
            raise Invalid(f"{where}: satellite {e.sat!r} under a header line for "
                          f"{record.type.source[1:]!r}")
    elif kind in NAV_KINDS and e.sat.strip():
        raise Invalid(f"{where}: columns 1 to 3 of {kind} line 0 are not blank")
    layout = _layout(major, file_type, record)
    if layout is None:
        return
    if len(record.lines) not in (len(layout.lines), *layout.also):
        raise Invalid(f"{where}: {len(record.lines)} lines after the first, "
                      f"{layout.source} has {len(layout.lines)}")
    for name, value in _named(layout, record):
        if name is None or name in layout.text or not value.strip():
            continue
        m = _REAL.fullmatch(value.strip())
        if m is None or not (m[2] or m[3]):
            raise Invalid(f"{where}: {name} {value!r} is not a number")


def _parse(lines: list[str], n: int, major: str, file_type: str) -> list[NavRecord]:
    """The records of the data lines ``lines[n:]``."""
    epoch_cls, line_cls = (NavEpoch2, NavLine2) if major == "2" else (NavEpoch, NavLine)
    starts = []
    for i in range(n, len(lines)):
        line = lines[i]
        if major == "4":
            if line.startswith(">"):
                starts.append(i)
        elif line[:2 if major == "2" else 1].strip():
            starts.append(i)
    if n < len(lines) and (not starts or starts[0] != n):
        what = "a record header line ('>')" if major == "4" else "the first line of a record"
        raise Invalid(f"line {n + 1}: expected {what}")
    out = []
    for start, end in zip(starts, [*starts[1:], len(lines)]):
        where = f"line {start + 1}"
        kind = None
        if major == "4":
            kind = cut(NavType, lines[start][1:])
            start += 1
            if start == end:
                raise Invalid(f"{where}: a record header line with no record")
        record = NavRecord(kind, cut(epoch_cls, lines[start]),
                           tuple(cut(line_cls, line) for line in lines[start + 1:end]))
        _check_record(major, file_type, record, where)
        out.append(record)
    return out


def read_nav(text: str) -> NavFile:
    """The navigation file in ``text``; raises :class:`Invalid` or :class:`Unsupported`."""
    lines, newline, final = _lines(text)
    header: list[HeaderRecord] = []
    n = 0
    while True:
        if n == len(lines):
            raise Invalid(f"no {END_OF_HEADER} record")
        header.append(_header_record(lines[n], f"line {n + 1}"))
        n += 1
        if n == 1:
            major = _check_version(header[0])
        if _label(header[-1]) == END_OF_HEADER:
            break
    file_type = header[0].content[20:21]
    return NavFile(tuple(header), tuple(_parse(lines, n, major, file_type)), newline, final)


# ---- writing -----------------------------------------------------------------------


def _record_lines(major: str, record: NavRecord, where: str) -> list[str]:
    epoch_cls, line_cls = (NavEpoch2, NavLine2) if major == "2" else (NavEpoch, NavLine)
    if not isinstance(record, NavRecord) or not isinstance(record.epoch, epoch_cls) or not all(
            isinstance(ln, line_cls) for ln in record.lines):
        raise Invalid(f"{where}: {record!r} is not a NavRecord of {epoch_cls.__name__} and "
                      f"{line_cls.__name__}")
    if (major == "4") != isinstance(record.type, NavType) or (
            major != "4" and record.type is not None):
        raise Invalid(f"{where}: a record has a NavType in RINEX 4, and only there")
    out = [">" + join(record.type)] if major == "4" else []
    return [*out, join(record.epoch), *(join(ln) for ln in record.lines)]


def write_nav(nav: NavFile) -> str:
    """The text of ``nav``; ``write_nav(read_nav(text)) == text``.

    Raises :class:`Invalid` for records :func:`read_nav` would not give
    back as they are.
    """
    if nav.newline not in ("\n", "\r\n"):
        raise Invalid(f"newline {nav.newline!r}: LF or CR LF")
    major = _major(nav)
    lines = [_header_line(r) for r in nav.header]
    if _label(nav.header[-1]) != END_OF_HEADER:
        raise Invalid(f"the header must end with {END_OF_HEADER}")
    if any(_label(r) == END_OF_HEADER for r in nav.header[:-1]):
        raise Invalid(f"{END_OF_HEADER} inside the header")
    n = len(lines)
    for i, record in enumerate(nav.records):
        lines += _record_lines(major, record, f"record {i}")
    # Reading the lines back is the check: a record that would be split,
    # merged or cut differently (a character in column 1 of an orbit line,
    # an empty last field) is refused, with what read_nav refuses.
    if tuple(_parse(lines, n, major, nav.file_type)) != tuple(nav.records):
        raise Invalid("the records do not read back from their lines")
    if lines[-1] == "" and not nav.final_newline:
        raise Invalid("an empty last line needs a final newline to be read back")
    return nav.newline.join(lines) + (nav.newline if nav.final_newline else "")


__all__ = ["NAV2", "NAV3", "NAV4_EOP", "NAV4_EPH", "NAV4_ION", "NAV4_STO", "NavEpoch",
           "NavEpoch2", "NavFile", "NavLayout", "NavLine", "NavLine2", "NavRecord", "NavType",
           "nav_fields", "nav_type", "read_nav", "real", "write_nav"]
