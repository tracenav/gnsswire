"""Multiple Signal Messages (MSM), RTCM 10403.3 section 3.5.16.3.

One table, :class:`Msm`, for every GNSS and every MSM level 1 to 7: the
systems differ only in the epoch-time field of the header and in how mask
bits map to satellites and signals (sections 3.5.16.4 to 3.5.16.9), which is
interpretation and stays with the caller; the levels differ in which rows are
present and in the widths of the high-resolution rows (Table 3.5-72). The
level is the last digit of the message number (Tables 3.5-89, -93, -97,
-100, -103 and -106: 1071 to 1077 for GPS, and so on). A message is

- the header, Table 3.5-78 (169 + X bits), where X = Nsat·Nsig is the
  width of the cell mask DF396, Nsat and Nsig being the set bits of the
  satellite mask DF394 and the signal mask DF395;
- satellite data, Table 3.5-79 (MSM1 to MSM3, 10·Nsat bits), 3.5-80 (MSM4
  and MSM6, 18·Nsat) or 3.5-81 (MSM5 and MSM7, 36·Nsat);
- signal data, Tables 3.5-82 to 3.5-88 (MSM1: 15·Ncell bits, MSM2: 27,
  MSM3: 42, MSM4: 48, MSM5: 63, MSM6: 65, MSM7: 80), Ncell being the set
  bits of the cell mask.

A row that a level does not have is ``None``. Rows present at several
levels with different widths are one field: ``fine_range`` is DF400 (int15)
in MSM1 and MSM3 to MSM5 and DF405 (int20) in MSM6 and MSM7, ``fine_phase``
DF401 (int22) or DF406 (int24), ``lock`` DF402 (uint4) or DF407 (uint10),
``cnr`` DF403 (uint6) or DF408 (uint10). Which DF a value is follows from
the level; its resolution is the caller's to apply.

Section 3.5.16.3.4, "internal looping": each data field is sent for every
satellite (or cell) before the next field, so each is a tuple here in mask
order, satellite data in the order of DF394's bits from the most significant
and cell data in the order of DF396's bits.

GNSS epoch time, Table 3.5-78, is 30 bits "specific for each GNSS": DF004
for GPS (section 3.5.16.4.2) and SBAS (3.5.16.7.2), DF248 for Galileo
(3.5.16.6.2), DF428 for QZSS (3.5.16.8.2) and DF427 for BeiDou
(3.5.15.8.2, numbered so in the standard) are each one uint30 and are
``epoch``. For GLONASS, Table 3.5-94 splits it into DF416 (day of week, 3
bits) and DF034 (time of day, 27 bits), which are ``glonass_day`` and
``glonass_epoch``; ``epoch`` is then ``None``. Table 3.5-94 gives DF416 the
type int3, while DF416's own entry in Table 3.4-1 is uint3 with range 0 to 7
(7: not known). This table follows Table 3.4-1; both readings keep the same
three bits.

The extended satellite information of MSM5 and MSM7 (Table 3.5-81, uint4,
"specific for each GNSS") is ``extended_info``: for GLONASS it is DF419, the
frequency channel number (section 3.5.16.5.2); for the other systems it is
"reserved for future use" and kept as the bits on the wire.

The cell mask is limited to 64 bits (Table 3.5-78 notes: "X≤64"); a message
with more satellite-signal combinations fails to encode or decode.

Section 3.5.16.3.4 also lets future versions append data to an MSM ("Actual
message length ... may be greater than ... the minimal required message
length"), which a decoder "shall skip (ignore)" and treat "as normal", while
an encoder "shall NOT" add any. ``extension`` keeps such data, so that the
message decodes and re-encodes to its own bytes (``_station``).
"""

from dataclasses import dataclass
from typing import Annotated

from gnsswire.bits import F, S, U, popcount

from ._station import Ext

# First three digits of the message number of each GNSS (Table 3.5-71).
GPS, GLONASS, GALILEO, SBAS, QZSS, BEIDOU = 107, 108, 109, 110, 111, 112

_SYSTEM = F.number // 10
_LEVEL = F.number % 10
_NSAT = popcount(F.sat_mask)
_NCELL = popcount(F.cell_mask)


def _levels(*present: int):
    """1 for an MSM level that has the row (Table 3.5-72), else 0."""
    return _LEVEL.map({level: int(level in present) for level in range(1, 8)})


def _width(standard: int, high: int):
    """Width at MSM1 to MSM5, and at the high-resolution MSM6 and MSM7."""
    return _LEVEL.map({level: high if level >= 6 else standard for level in range(1, 8)})


# Every MSM of the six systems in RTCM 10403.3 (Tables 3.5-89, -93, -97,
# -100, -103 and -106), levels 1 to 7.
MSM_TYPES = tuple(10 * system + level for system in (GPS, GLONASS, GALILEO, SBAS, QZSS, BEIDOU)
                  for level in range(1, 8))


@dataclass(frozen=True, slots=True)
class Msm:
    """An MSM1 to MSM7 message of any GNSS. RTCM 10403.3 Tables 3.5-78 to 3.5-88."""

    # Header, Table 3.5-78.
    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    epoch: Annotated[int | None, U(30, "DF004/DF248/DF427/DF428", when=_SYSTEM != GLONASS)]
    glonass_day: Annotated[int | None, U(3, "DF416", when=_SYSTEM == GLONASS)]
    glonass_epoch: Annotated[int | None, U(27, "DF034", when=_SYSTEM == GLONASS)]
    multiple: Annotated[int, U(1, "DF393")]
    iods: Annotated[int, U(3, "DF409")]
    reserved: Annotated[int, U(7, "DF001")]
    clock_steering: Annotated[int, U(2, "DF411")]
    external_clock: Annotated[int, U(2, "DF412")]
    smoothing: Annotated[int, U(1, "DF417")]
    smoothing_interval: Annotated[int, U(3, "DF418")]
    sat_mask: Annotated[int, U(64, "DF394")]
    sig_mask: Annotated[int, U(32, "DF395")]
    cell_mask: Annotated[int, U(_NSAT * popcount(F.sig_mask), "DF396")]
    # Satellite data, Tables 3.5-79 to 3.5-81.
    rough_ms: Annotated[tuple[int, ...] | None,
                        U(8, "DF397", count=_NSAT, when=_levels(4, 5, 6, 7))]
    extended_info: Annotated[tuple[int, ...] | None,
                             U(4, "DF419", count=_NSAT, when=_levels(5, 7))]
    rough_mod: Annotated[tuple[int, ...], U(10, "DF398", count=_NSAT)]
    rough_rate: Annotated[tuple[int, ...] | None,
                          S(14, "DF399", count=_NSAT, when=_levels(5, 7))]
    # Signal data, Tables 3.5-82 to 3.5-88.
    fine_range: Annotated[tuple[int, ...] | None,
                          S(_width(15, 20), "DF400/DF405", count=_NCELL,
                            when=_levels(1, 3, 4, 5, 6, 7))]
    fine_phase: Annotated[tuple[int, ...] | None,
                          S(_width(22, 24), "DF401/DF406", count=_NCELL,
                            when=_levels(2, 3, 4, 5, 6, 7))]
    lock: Annotated[tuple[int, ...] | None,
                    U(_width(4, 10), "DF402/DF407", count=_NCELL, when=_levels(2, 3, 4, 5, 6, 7))]
    half_cycle: Annotated[tuple[int, ...] | None,
                          U(1, "DF420", count=_NCELL, when=_levels(2, 3, 4, 5, 6, 7))]
    cnr: Annotated[tuple[int, ...] | None,
                   U(_width(6, 10), "DF403/DF408", count=_NCELL, when=_levels(4, 5, 6, 7))]
    fine_rate: Annotated[tuple[int, ...] | None,
                         S(15, "DF404", count=_NCELL, when=_levels(5, 7))]
    extension: Ext = None
