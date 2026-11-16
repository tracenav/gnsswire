"""Message tables: OCB (SM 0-0 to 0-4), HPAC (SM 1-0 to 1-4), GAD (SM 2-0) and BPAC (SM 3-0).

Each class is the block table of SPARTN v2.0.3 section 6.5 cited in its
docstring, row for row and in order; the SF numbers are the rows' tags and
the widths those of Table 6.2. Values are the raw unsigned integers on the
wire (section 6.3): a decoded value is ``encoded * resolution + range
minimum``, which is the caller's to apply, together with the special values.

Constellation (``**`` in the tables): the fields Table 6.2 defines per
constellation (ephemeris type, satellite mask, IODE, bias masks) take their
width from the message subtype TF007, which is in the transport layer, not
the payload. The tables therefore take ``subtype`` as a parameter
(``PARAMS``, see :mod:`gnsswire.bits`): 0 GPS, 1 GLONASS, 2 Galileo,
3 BeiDou, 4 QZSS (Table 6.1). A subtype outside 0 to 4 is a decode error.

Masks: each mask of Table 6.2 that is "composed of" a size indicator and a
bitmask (SF011, SF012, SF025 to SF028, SF093 to SF095, SF102 to SF107) is
two rows here, the indicator and the bitmask; together they are the field.
Mask bit 0 is the leftmost (first sent) bit, so the bitmask's most
significant bit is the first satellite or signal. The blocks that a mask
selects repeat once per set bit, in mask order. A bias mask is kept as
sent, spare bits included; the signal each bit stands for is in its row of
Table 6.2. v2.0.3 defines Galileo bits 3 and 4 (SF102: L8Q and L6C phase
biases; SF105: C8Q and C6C code biases), which v2.0.2 left spare; the
widths, and so the layout, are the same in both versions.

Values the spec leaves TBD where they change the layout are decode errors,
because no reading of them is defined: SF040 = 3, and equation types SF041
and SF054 of 3 to 7.

Fill and extensions: TF016 is padded with fill bits to TF003 bytes (Table
7.1), whose value the table does not give. Section 8.4 item 4: "Several
messages include reserved bits which in the future may be used to extend
message content at the end of the payload. Therefore, decoder
implementations should not use payload length to indicate where they stop
decoding." So every message table ends with ``extension``, which keeps
whatever follows the table (``None`` when that is no more than zero fill
bits) as a ``gnsswire.bits.Extension``, and writes it back, so that
``encode(decode(frame))`` is the frame; ``decode(frame, strict=True)``
refuses such a payload instead.
"""

from dataclasses import dataclass
from typing import Annotated, ClassVar

from gnsswire.bits import Expr, Extension, F, Group, Mask, Rest, U, popcount

# The row that ends every message table: what follows the table.
Ext = Annotated[Extension | None, Rest()]

GPS, GLONASS, GALILEO, BEIDOU, QZSS = range(5)


def per_gnss(widths: dict[int, int | tuple[int, ...]], selector: Expr | None = None) -> Expr:
    """A width picked by the subtype, and for a mask by its size indicator ``selector``.

    ``widths`` maps each subtype to a width, or to the widths that the size
    indicator's values 0, 1, ... select.
    """
    if selector is None:
        return F.subtype.map(widths)  # type: ignore[arg-type]
    n = len(next(iter(widths.values())))  # type: ignore[arg-type]
    table = {s * n + i: w for s, ws in widths.items() for i, w in enumerate(ws)}  # type: ignore[arg-type]
    return (F.subtype * n + selector).map(table)


# Table 6.2, per constellation.
EPHEMERIS_TYPE = {GPS: 2, GLONASS: 2, GALILEO: 3, BEIDOU: 4, QZSS: 3}   # SF016 SF017 SF096 SF097 SF098
SATELLITE_MASK = {GPS: (32, 44, 56, 64), GLONASS: (24, 36, 48, 63),     # SF011 SF012
                  GALILEO: (36, 45, 54, 64), BEIDOU: (37, 46, 55, 64),  # SF093 SF094
                  QZSS: (10, 40, 48, 64)}                               # SF095
IODE = {GPS: 8, GLONASS: 7, GALILEO: 10, BEIDOU: 8, QZSS: 8}            # SF018 SF019 SF099 SF100 SF101
PHASE_BIAS_MASK = {GPS: (6, 11), GLONASS: (5, 9), GALILEO: (8, 15),     # SF025 SF026 SF102
                   BEIDOU: (8, 15), QZSS: (6, 11)}                      # SF103 SF104
CODE_BIAS_MASK = {GPS: (6, 11), GLONASS: (5, 9), GALILEO: (8, 15),      # SF027 SF028 SF105
                  BEIDOU: (8, 15), QZSS: (6, 11)}                       # SF106 SF107
SATELLITE_MASK_TAG = "SF011/SF012/SF093/SF094/SF095"

# SF014 bit 0 is the leftmost of three.
ORBIT, CLOCK, BIAS = 0b100, 0b010, 0b001


# --- OCB, section 6.5.1 ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Orbit:
    """Orbit block, Table 6.5 (49, 50, 52, 55, 56 or 58 bits)."""

    iode: Annotated[int, U(per_gnss(IODE), "SF018/SF019/SF099/SF100/SF101")]
    radial: Annotated[int, U(14, "SF020")]
    along: Annotated[int, U(14, "SF020")]
    cross: Annotated[int, U(14, "SF020")]
    yaw: Annotated[int | None, U(6, "SF021", when=F.yaw_present)]


@dataclass(frozen=True, slots=True)
class Clock:
    """Clock block, Table 6.6 (20 bits)."""

    iode_continuity: Annotated[int, U(3, "SF022")]
    correction: Annotated[int, U(14, "SF020")]
    ure: Annotated[int, U(3, "SF024")]


@dataclass(frozen=True, slots=True)
class PhaseBias:
    """Phase bias block, Table 6.12 (18 bits)."""

    fix: Annotated[int, U(1, "SF023")]
    continuity: Annotated[int, U(3, "SF015")]
    correction: Annotated[int, U(14, "SF020")]


@dataclass(frozen=True, slots=True)
class Bias:
    """Bias block, Tables 6.7 (GPS), 6.8 (GLONASS), 6.9 (Galileo), 6.10 (BeiDou), 6.11 (QZSS).

    The five tables differ only in the widths of their two masks.
    """

    phase_mask_size: Annotated[int, U(1, "SF025/SF026/SF102/SF103/SF104")]
    phase_mask: Annotated[int, U(per_gnss(PHASE_BIAS_MASK, F.phase_mask_size),
                                 "SF025/SF026/SF102/SF103/SF104")]
    phase: Annotated[tuple[PhaseBias, ...], Group(PhaseBias, count=popcount(F.phase_mask))]
    code_mask_size: Annotated[int, U(1, "SF027/SF028/SF105/SF106/SF107")]
    code_mask: Annotated[int, U(per_gnss(CODE_BIAS_MASK, F.code_mask_size),
                                "SF027/SF028/SF105/SF106/SF107")]
    code: Annotated[tuple[int, ...], U(11, "SF029", count=popcount(F.code_mask))]


@dataclass(frozen=True, slots=True)
class OcbSatellite:
    """Satellite block, Table 6.4.

    AMBIGUOUS: the layout of a satellite whose SF013 (DNU) is set. The two
    readings differ by six bits:

    - Table 6.2, SF013, special values: "1 : No fields in the associated
      satellite block will be present"; notes: "When this flag is set, the
      remaining fields of this section for this satellite shall not be
      present." The block is SF013 alone (1 bit).
    - Table 8.2, "Nominal Size Calculation": ``HeaderBlock + (7 + Dnu *
      (OrbitBlock + ClockBlock + BiasBlock)) * NSc``, where "Dnu 0 when
      satellite should not be used". The block keeps SF014 and SF015 (7 bits).

    This codec follows Table 6.2, for these reasons. The field definition is
    the normative text, and it says the same thing twice, in two columns.
    Table 8.2 is headed "nominal" and is not exact elsewhere either: its OCB
    header is ``15 + MNsc``, which counts a 2-bit ephemeris type, right for
    GPS and GLONASS but one bit short for Galileo and QZSS (SF096, SF098: 3
    bits) and two short for BeiDou (SF097: 4 bits); and it multiplies the
    per-satellite sizes by the satellite count as if every satellite had the
    same blocks. Table 6.4 lists SF014 and SF015 without a condition, but it
    lists the orbit, clock and bias blocks without their conditions too, so
    it does not decide. The revision history mentions no change to SF013,
    and the document has no message example with a DNU satellite.

    With DNU set, ``present`` and ``continuity`` are ``None``. The other
    reading is available as the ``dnu_reading`` parameter of :class:`Ocb`
    (``DNU_TABLE_8_2``): there, a DNU satellite has ``present`` and
    ``continuity`` and still no blocks. ``gnsswire.spartn.decode`` takes it
    when the payload length shows it (see there). No data at hand has a DNU
    satellite.
    """

    dnu: Annotated[int, U(1, "SF013")]
    present: Annotated[int | None, U(3, "SF014", when=(F.dnu == 0) | F.dnu_reading)]
    continuity: Annotated[int | None, U(3, "SF015", when=(F.dnu == 0) | F.dnu_reading)]
    orbit: Annotated[Orbit | None, Group(Orbit, when=(F.dnu == 0) & (F.present & ORBIT != 0))]
    clock: Annotated[Clock | None, Group(Clock, when=(F.dnu == 0) & (F.present & CLOCK != 0))]
    bias: Annotated[Bias | None, Group(Bias, when=(F.dnu == 0) & (F.present & BIAS != 0))]


@dataclass(frozen=True, slots=True)
class Ocb:
    """Orbit, clock and bias message, SM 0-0 to 0-4: header block of Table 6.3 and satellites.

    ``mask`` (with its size indicator ``mask_size``) is SF011, SF012, SF093,
    SF094 or SF095 by subtype; ``satellites`` follow it in mask order.

    Parameters: ``subtype`` (TF007), and ``dnu_reading``, the layout of a
    satellite with DNU set (:class:`OcbSatellite`): ``DNU_TABLE_6_2`` (0,
    SF013 alone) or ``DNU_TABLE_8_2`` (1, SF013 to SF015).
    """

    PARAMS: ClassVar[tuple[str, ...]] = ("subtype", "dnu_reading")
    MESSAGE_TYPE: ClassVar[int] = 0
    SUBTYPES: ClassVar[tuple[int, ...]] = (GPS, GLONASS, GALILEO, BEIDOU, QZSS)

    siou: Annotated[int, U(9, "SF005")]
    end_of_set: Annotated[int, U(1, "SF010")]
    reserved: Annotated[int, U(1, "SF069")]
    yaw_present: Annotated[int, U(1, "SF008")]
    datum: Annotated[int, U(1, "SF009")]
    ephemeris_type: Annotated[int, U(per_gnss(EPHEMERIS_TYPE), "SF016/SF017/SF096/SF097/SF098")]
    mask_size: Annotated[int, U(2, SATELLITE_MASK_TAG)]
    mask: Annotated[int, U(per_gnss(SATELLITE_MASK, F.mask_size), SATELLITE_MASK_TAG)]
    satellites: Annotated[tuple[OcbSatellite, ...], Group(OcbSatellite, count=popcount(F.mask))]
    extension: Ext = None


DNU_TABLE_6_2, DNU_TABLE_8_2 = 0, 1


@dataclass(frozen=True, slots=True)
class OcbHeader:
    """The header block of any OCB message, SM 0-x (Table 6.3), without the satellite blocks.

    Section 8.4 item 5: providers "may elect to mark the End-of-Set in any
    SM-0 message", so decoders "should be designed so as to decode the SF010
    field of all current and future SM 0 message possibilities ... (i.e.,
    the SF010 field will be at the exact same location for all current and
    future OCB message types)". The first five rows (SF005, SF010, SF069,
    SF008, SF009) are read for every subtype; the ephemeris type and the
    satellite mask, whose widths Table 6.2 defines per constellation, only
    for subtypes 0 to 4, and are ``None`` for the others (TBD in Table 6.1).
    The same rows as the start of :class:`Ocb`.
    """

    PARAMS: ClassVar[tuple[str, ...]] = ("subtype",)

    siou: Annotated[int, U(9, "SF005")]
    end_of_set: Annotated[int, U(1, "SF010")]
    reserved: Annotated[int, U(1, "SF069")]
    yaw_present: Annotated[int, U(1, "SF008")]
    datum: Annotated[int, U(1, "SF009")]
    ephemeris_type: Annotated[int | None, U(per_gnss(EPHEMERIS_TYPE),
                                            "SF016/SF017/SF096/SF097/SF098",
                                            when=F.subtype <= QZSS)]
    mask_size: Annotated[int | None, U(2, SATELLITE_MASK_TAG, when=F.subtype <= QZSS)]
    mask: Annotated[int | None, U(per_gnss(SATELLITE_MASK, F.mask_size), SATELLITE_MASK_TAG,
                                  when=F.subtype <= QZSS)]


# --- HPAC, section 6.5.2 --------------------------------------------------------------

# SF040: 0 none, 1 polynomial block, 2 polynomial and grid blocks; 3 undefined.
POLY_PRESENT = {0: 0, 1: 1, 2: 1}
# SF041 and SF054 equation types 0, 1, 2; 3 to 7 TBD.
HAS_C00 = {0: 1, 1: 1, 2: 1}
HAS_LINEAR = {0: 0, 1: 1, 2: 1}
HAS_C11 = {0: 0, 1: 0, 2: 1}


@dataclass(frozen=True, slots=True)
class TropoSmall:
    """Troposphere small coefficient block, Table 6.17 (7, 21 or 30 bits by SF041)."""

    t00: Annotated[int, U(7, "SF045", when=F.equation_type.map(HAS_C00))]
    t01: Annotated[int | None, U(7, "SF046", when=F.equation_type.map(HAS_LINEAR))]
    t10: Annotated[int | None, U(7, "SF046", when=F.equation_type.map(HAS_LINEAR))]
    t11: Annotated[int | None, U(9, "SF047", when=F.equation_type.map(HAS_C11))]


@dataclass(frozen=True, slots=True)
class TropoLarge:
    """Troposphere large coefficient block, Table 6.18 (9, 27 or 38 bits by SF041)."""

    t00: Annotated[int, U(9, "SF048", when=F.equation_type.map(HAS_C00))]
    t01: Annotated[int | None, U(9, "SF049", when=F.equation_type.map(HAS_LINEAR))]
    t10: Annotated[int | None, U(9, "SF049", when=F.equation_type.map(HAS_LINEAR))]
    t11: Annotated[int | None, U(11, "SF050", when=F.equation_type.map(HAS_C11))]


@dataclass(frozen=True, slots=True)
class Troposphere:
    """Troposphere data block, Table 6.16: polynomial coefficient block, then grid block.

    The grid block (SF051 and the residuals) is present only when the area's
    tropo blocks indicator (SF040) is 2, with one residual per grid point
    present (SF039).
    """

    equation_type: Annotated[int, U(3, "SF041")]
    quality: Annotated[int, U(3, "SF042")]
    hydrostatic: Annotated[int, U(8, "SF043")]
    coefficient_size: Annotated[int, U(1, "SF044")]
    small: Annotated[TropoSmall | None, Group(TropoSmall, when=F.coefficient_size == 0)]
    large: Annotated[TropoLarge | None, Group(TropoLarge, when=F.coefficient_size == 1)]
    residual_size: Annotated[int | None, U(1, "SF051", when=F.tropo_blocks == 2)]
    residuals: Annotated[tuple[int, ...] | None, U(
        F.residual_size.map({0: 6, 1: 8}), "SF052/SF053", count=F.grid_points,
        when=F.tropo_blocks == 2)]


@dataclass(frozen=True, slots=True)
class IonoSmall:
    """Ionosphere small coefficient block, Table 6.21 (12, 36 or 49 bits by SF054)."""

    c00: Annotated[int, U(12, "SF057", when=F.equation_type.map(HAS_C00))]
    c01: Annotated[int | None, U(12, "SF058", when=F.equation_type.map(HAS_LINEAR))]
    c10: Annotated[int | None, U(12, "SF058", when=F.equation_type.map(HAS_LINEAR))]
    c11: Annotated[int | None, U(13, "SF059", when=F.equation_type.map(HAS_C11))]


@dataclass(frozen=True, slots=True)
class IonoLarge:
    """Ionosphere large coefficient block, Table 6.22 (14, 42 or 57 bits by SF054)."""

    c00: Annotated[int, U(14, "SF060", when=F.equation_type.map(HAS_C00))]
    c01: Annotated[int | None, U(14, "SF061", when=F.equation_type.map(HAS_LINEAR))]
    c10: Annotated[int | None, U(14, "SF061", when=F.equation_type.map(HAS_LINEAR))]
    c11: Annotated[int | None, U(15, "SF062", when=F.equation_type.map(HAS_C11))]


@dataclass(frozen=True, slots=True)
class IonoSatellite:
    """Ionosphere satellite block, Table 6.20: polynomial, coefficients, then grid block.

    The grid block (SF063 and the residuals) is present only when the area's
    iono blocks indicator (SF040) is 2, with one residual per grid point
    present (SF039).
    """

    quality: Annotated[int, U(4, "SF055")]
    coefficient_size: Annotated[int, U(1, "SF056")]
    small: Annotated[IonoSmall | None, Group(IonoSmall, when=F.coefficient_size == 0)]
    large: Annotated[IonoLarge | None, Group(IonoLarge, when=F.coefficient_size == 1)]
    residual_size: Annotated[int | None, U(2, "SF063", when=F.iono_blocks == 2)]
    residuals: Annotated[tuple[int, ...] | None, U(
        F.residual_size.map({0: 4, 1: 7, 2: 10, 3: 14}), "SF064/SF065/SF066/SF067",
        count=F.grid_points, when=F.iono_blocks == 2)]


@dataclass(frozen=True, slots=True)
class Ionosphere:
    """Ionosphere data block, Table 6.19: equation type, satellite mask, satellites."""

    equation_type: Annotated[int, U(3, "SF054")]
    mask_size: Annotated[int, U(2, SATELLITE_MASK_TAG)]
    mask: Annotated[int, U(per_gnss(SATELLITE_MASK, F.mask_size), SATELLITE_MASK_TAG)]
    satellites: Annotated[tuple[IonoSatellite, ...], Group(IonoSatellite, count=popcount(F.mask))]


@dataclass(frozen=True, slots=True)
class HpacArea:
    """Atmosphere block, Table 6.14: area data block (Table 6.15), troposphere, ionosphere."""

    area_id: Annotated[int, U(8, "SF031")]
    grid_points: Annotated[int, U(7, "SF039")]
    tropo_blocks: Annotated[int, U(2, "SF040")]
    iono_blocks: Annotated[int, U(2, "SF040")]
    troposphere: Annotated[Troposphere | None, Group(
        Troposphere, when=F.tropo_blocks.map(POLY_PRESENT))]
    ionosphere: Annotated[Ionosphere | None, Group(
        Ionosphere, when=F.iono_blocks.map(POLY_PRESENT))]


@dataclass(frozen=True, slots=True)
class Hpac:
    """High-precision atmosphere correction, SM 1-0 to 1-4: header block of Table 6.13 and areas.

    ``area_count`` is SF030 raw; SF030 + 1 areas follow (see :class:`Gad`).
    """

    PARAMS: ClassVar[tuple[str, ...]] = ("subtype",)
    MESSAGE_TYPE: ClassVar[int] = 1
    SUBTYPES: ClassVar[tuple[int, ...]] = (GPS, GLONASS, GALILEO, BEIDOU, QZSS)

    siou: Annotated[int, U(9, "SF005")]
    aiou: Annotated[int, U(4, "SF068")]
    reserved: Annotated[int, U(1, "SF069")]
    area_count: Annotated[int, U(5, "SF030")]
    areas: Annotated[tuple[HpacArea, ...], Group(HpacArea, count=F.area_count + 1)]
    extension: Ext = None


# --- GAD, section 6.5.3 ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GadArea:
    """Area definition block, Table 6.24 (47 bits)."""

    area_id: Annotated[int, U(8, "SF031")]
    latitude: Annotated[int, U(11, "SF032")]
    longitude: Annotated[int, U(12, "SF033")]
    latitude_nodes: Annotated[int, U(3, "SF034")]
    longitude_nodes: Annotated[int, U(3, "SF035")]
    latitude_spacing: Annotated[int, U(5, "SF036")]
    longitude_spacing: Annotated[int, U(5, "SF037")]


@dataclass(frozen=True, slots=True)
class Gad:
    """Geographic area definition, SM 2-0: header block of Table 6.23 and areas (19 + 47·n bits).

    ``area_count`` is SF030 raw. Table 6.2 gives it the range 1 to 32 in 5
    bits without saying how the range is coded; with section 6.3 (decoded
    value = encoded value * resolution + range minimum, resolution 1) the
    number of areas is SF030 + 1, which is also the only reading under which
    all 32 counts the range allows fit in 5 bits. pyspartn reads it the
    same way, and so do the recorded streams the codec has been tried on
    (README.md, "Contribute").
    """

    PARAMS: ClassVar[tuple[str, ...]] = ()
    MESSAGE_TYPE: ClassVar[int] = 2
    SUBTYPES: ClassVar[tuple[int, ...]] = (0,)

    siou: Annotated[int, U(9, "SF005")]
    aiou: Annotated[int, U(4, "SF068")]
    reserved: Annotated[int, U(1, "SF069")]
    area_count: Annotated[int, U(5, "SF030")]
    areas: Annotated[tuple[GadArea, ...], Group(GadArea, count=F.area_count + 1)]
    extension: Ext = None


# --- BPAC, section 6.5.4 --------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BpacGridPoint:
    """BPAC grid node VTEC block, Table 6.28 (12 or 16 bits)."""

    quality: Annotated[int, U(4, "SF055")]
    size: Annotated[int, U(1, "SF081")]
    residual: Annotated[int, U(F.size.map({0: 7, 1: 11}), "SF082/SF083")]


@dataclass(frozen=True, slots=True)
class BpacArea:
    """BPAC area block, Table 6.26: the area data block of Table 6.27 (43 + N bits), then VTECs.

    ``latitude_nodes`` and ``longitude_nodes`` are SF075 and SF076 raw.
    Table 6.2 gives each the range 1 to 16 in 4 bits; with section 6.3 (as
    for SF030, :class:`Gad`) the counts are SF075 + 1 and SF076 + 1, and the
    grid node present mask SF079 is N = (SF075 + 1) * (SF076 + 1) bits wide,
    1 to 256, as SF079's own row says ("Bit mask of length N (between 1 and
    256 bits)"). Only that reading reaches 256.

    AMBIGUOUS: how many VTEC blocks follow. Table 6.26 says "Repeated for
    each grid point"; SF079 indicates "the presence of grid point data in
    the BPAC area VTEC block", and Table 8.2 sizes the VTEC blocks as
    ``(5+Vs) * NGpPrst``, "NGpPrst Number of grid points present". A mask
    of present points means nothing if every point has a block, so this
    follows SF079 and Table 8.2: one block per set bit of the mask, in mask
    order (bit 0, the leftmost, first).
    """

    area_id: Annotated[int, U(2, "SF072")]
    latitude: Annotated[int, U(8, "SF073")]
    longitude: Annotated[int, U(9, "SF074")]
    latitude_nodes: Annotated[int, U(4, "SF075")]
    longitude_nodes: Annotated[int, U(4, "SF076")]
    latitude_spacing: Annotated[int, U(2, "SF077")]
    longitude_spacing: Annotated[int, U(2, "SF078")]
    average_vtec: Annotated[int, U(12, "SF080")]
    present: Annotated[int, Mask((F.latitude_nodes + 1) * (F.longitude_nodes + 1), "SF079")]
    grid_points: Annotated[tuple[BpacGridPoint, ...],
                           Group(BpacGridPoint, count=popcount(F.present))]


@dataclass(frozen=True, slots=True)
class Bpac:
    """Basic-precision atmosphere correction, SM 3-0: header block of Table 6.25 and areas.

    ``area_count`` is SF071 raw; SF071 + 1 areas follow (range 1 to 4 in 2
    bits, read as SF030 is, :class:`Gad`).
    """

    PARAMS: ClassVar[tuple[str, ...]] = ()
    MESSAGE_TYPE: ClassVar[int] = 3
    SUBTYPES: ClassVar[tuple[int, ...]] = (0,)

    siou: Annotated[int, U(9, "SF005")]
    reserved: Annotated[int, U(1, "SF069")]
    shell_height: Annotated[int, U(2, "SF070")]
    area_count: Annotated[int, U(2, "SF071")]
    areas: Annotated[tuple[BpacArea, ...], Group(BpacArea, count=F.area_count + 1)]
    extension: Ext = None
