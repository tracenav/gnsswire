# gnsswire-rinex

RINEX observation and navigation files for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-rinex)](https://pypi.org/project/gnsswire-rinex/)

gnsswire-rinex reads and writes RINEX 2, 3 and 4 observation files and
navigation message files, the standard text formats for exchanging GNSS
observations and broadcast ephemerides. It gives you:

- the header, every epoch and every satellite's observations, as the text
  in each record's columns;
- every navigation record (ephemerides of GPS, Galileo, GLONASS, BeiDou,
  QZSS, SBAS and NavIC, and the time offset, Earth orientation and
  ionosphere records of RINEX 4), with its values by the names of its
  table;
- a lossless round trip: `write(read(text)) == text` for every file `read`
  accepts;
- numeric fields as exact integers, without floating point.

It is part of [gnsswire](https://pypi.org/project/gnsswire/), codecs for
GNSS wire formats.

## Installation

```sh
$ pip install gnsswire-rinex
```

gnsswire-rinex requires Python 3.11+ and has no dependencies. `pip install
gnsswire` installs it with every other format.

## Usage

### Read an observation file

`read(text)` gives an `ObsFile`: the header, then each epoch with its
satellites' observations, in the order the header's SYS / # / OBS TYPES
gives (`obs_types`):

```python
from gnsswire import rinex

text = (
    "     3.05           OBSERVATION DATA    M                   RINEX VERSION / TYPE\n"
    "G    4 C1C L1C D1C S1C                                      SYS / # / OBS TYPES\n"
    "E    2 C1C L1C                                              SYS / # / OBS TYPES\n"
    "                                                            END OF HEADER\n"
    "> 2026 01 02 03 04  5.0000000  0  2\n"
    "G06  23629347.915   119876543.2107       -353.123          44.250\n"
    "E11  25112003.448   131967450.512\n"
)
obs = rinex.read(text)
types = rinex.obs_types(obs.header)

for epoch in obs.epochs:
    r = epoch.record
    print("epoch", r.year.strip(), r.month.strip(), r.day.strip(), "flag", r.flag.strip())
    for sat in epoch.satellites:
        print(sat.sat, {t: o.value.strip() for t, o in zip(types[sat.sat[0]], sat.obs)})
# epoch 2026 01 02 flag 0
# G06 {'C1C': '23629347.915', 'L1C': '119876543.210', 'D1C': '-353.123', 'S1C': '44.250'}
# E11 {'C1C': '25112003.448', 'L1C': '131967450.512'}
```

Every field is the text in the record's columns, leading blanks included,
so nothing is lost; each observation also keeps its loss-of-lock and
signal strength indicators (`lli`, `ssi`).

### Exact numbers

`number(field, decimals)` gives a numeric field as the integer of its
digits, without floating point:

```python
g06 = obs.epochs[0].satellites[0]
print(rinex.number(g06.obs[0].value, 3), "mm")     # 23629347915 mm
print(repr(g06.obs[1].lli))                         # '7'
```

### Write it back

`write(obs)` gives the text back, exactly as read:

```python
print(rinex.write(obs) == text)                     # True
```

### RINEX 2

RINEX 2 observation files have their own pair, `read2` and `write2`, as
lossless. The epoch record lists the satellites, each satellite's
observations follow five to a line, every satellite has the header's # /
TYPES OF OBSERV (`obs_types2`), and the year has two digits (`full_year`).
A satellite keeps its three columns of the list, where a blank system
identifier means GPS (`sat_name`):

```python
text2 = (
    "     2.11           OBSERVATION DATA    G (GPS)             RINEX VERSION / TYPE\n"
    "     4    C1    L1    D1    S1                              # / TYPES OF OBSERV\n"
    "                                                            END OF HEADER\n"
    " 26  1  2  3  4  5.0000000  0  2G06  9\n"
    "  23629347.915   119876543.2107       -353.123          44.250\n"
    "  25112003.448   131967450.512\n"
)
obs2 = rinex.read2(text2)
types2 = rinex.obs_types2(obs2.header)

for epoch in obs2.epochs:
    r = epoch.record
    print("epoch", rinex.full_year(r.year), r.month.strip(), r.day.strip(), "flag", r.flag.strip())
    for sat in epoch.satellites:
        print(rinex.sat_name(sat.sat), {t: o.value.strip() for t, o in zip(types2, sat.obs)})
# epoch 2026 1 2 flag 0
# G06 {'C1': '23629347.915', 'L1': '119876543.210', 'D1': '-353.123', 'S1': '44.250'}
# G09 {'C1': '25112003.448', 'L1': '131967450.512'}

print(repr(obs2.epochs[0].satellites[1].sat))       # '  9'
print(rinex.write2(obs2) == text2)                  # True
```

`read` raises `Unsupported` for a RINEX 2 file and `read2` for a RINEX 3 or
4 file; `ObsFile.version` and `ObsFile2.version` give the version read.

### Navigation files

`read_nav(text)` gives a `NavFile` of any of the three versions: the header
and the records, each a first line (`epoch`: the satellite, the epoch and
three values) and its BROADCAST ORBIT lines of four values, all as text. A
RINEX 4 record also has its header line (`type`). `nav_fields` gives the
values by the names of the record's table, in the table's order, and
`nav_type` what the record is:

```python
nav_text = (
    "     4.02           NAVIGATION DATA     M                   RINEX VERSION / TYPE\n"
    "    18                                                      LEAP SECONDS\n"
    "                                                            END OF HEADER\n"
    "> EPH G04 LNAV\n"
    "G04 2019 03 14 04 00 00 1.330170780420e-04 7.275957614183e-12 0.000000000000e+00\n"
    "     9.800000000000e+01-1.718750000000e+00 4.639836124941e-09 2.148941747752e+00\n"
    "    -1.881271600723e-07 3.355251392350e-04 8.245930075645e-06 5.153800453186e+03\n"
    "     3.600000000000e+05-1.676380634308e-08 5.171400020311e-01 1.490116119385e-08\n"
    "     9.601921900531e-01 2.187187500000e+02-1.736906885738e+00-8.044977962767e-09\n"
    "    -2.932264997750e-10 1.000000000000e+00 2.044000000000e+03 0.000000000000e+00\n"
    "     4.000000000000e+00 6.300000000000e+01-8.847564458847e-09 8.660000000000e+02\n"
    "     3.553500000000e+05 4.000000000000e+00\n"
    "> ION E13 IFNV\n"
    "    2021 07 05 00 11 04 5.450000000000e+01 3.593750000000e-01 1.358032226562e-02\n"
    "     0.000000000000e+00\n"
)
nav = rinex.read_nav(nav_text)

for record in nav.records:
    e = record.epoch
    print(rinex.nav_type(nav, record), repr(e.sat), e.year.strip(), e.month.strip(), e.day.strip())
# ('EPH', 'G', 'LNAV', '') 'G04' 2019 03 14
# ('ION', 'E', 'IFNV', '') '   ' 2021 07 05

eph = rinex.nav_fields(nav, nav.records[0])
print(list(eph)[:8])
# ['clock_bias', 'clock_drift', 'clock_drift_rate', 'iode', 'crs', 'delta_n', 'm0', 'cuc']
print(repr(eph["sqrt_a"]), repr(eph["toe"]))        # ' 5.153800453186e+03' ' 3.600000000000e+05'
print(rinex.nav_fields(nav, nav.records[1]))
# {'ai0': ' 5.450000000000e+01', 'ai1': ' 3.593750000000e-01', 'ai2': ' 1.358032226562e-02',
#  'disturbance_flags': ' 0.000000000000e+00'}
```

`real(field)` gives a floating point field exactly, as its digits and a
power of ten, whichever exponent letter (`D`, `E`, `d`, `e`) the file uses;
a blank field is `None`:

```python
print(rinex.real(eph["sqrt_a"]))                    # (5153800453186, -9)
print(rinex.real(eph["week"]), float(eph["week"]))  # (2044000000000, -9) 2044.0
print(rinex.real(" -.839701388031D-03"))            # (-839701388031, -15)
print(rinex.write_nav(nav) == nav_text)             # True
```

A RINEX 2 or 3 record has no header line (`record.type` is `None`); its
table is that of its satellite system (RINEX 3) or of the file's type
(RINEX 2). A RINEX 4 record of a type with no table is kept as it is and
written back, and `nav_fields` raises `Unsupported` for it.

### Errors

A file of a kind this codec does not read (meteorological, clock,
compressed; a navigation file or a RINEX 2 file given to `read`, an
observation file given to `read_nav`) raises `Unsupported`; text that does not follow the tables
raises `Invalid`. Both, and the error `number` raises for a field that is not a number of
its format, derive from `rinex.Error`, a `ValueError`.

## Records

| Record | Class | Source |
|---|---|---|
| Header record (content, label) | `HeaderRecord` | RINEX 3.05 and 4.02, Table A2 |
| SYS / # / OBS TYPES | `obs_types()` | same |
| EPOCH record | `EpochRecord` | Table A3 (`picoseconds`: 4.02 only) |
| OBSERVATION and cycle slip records | `SatelliteRecord`, `Observation` | Table A3, section 6.7 |
| Event records (flags 2 to 5) | `Epoch.special` | Table A3, section 5.3.2 |

Observation types redefined by a header event (flag 4) are applied to the
epochs after it; `obs_types(epoch.special, types)` gives the types after
such an event from those before it.

RINEX 2 observation files (`ObsFile2`, `Epoch2`), from RINEX 2.11:

| Record | Class | Source |
|---|---|---|
| Header record (content, label) | `HeaderRecord` | Table A1 |
| # / TYPES OF OBSERV | `obs_types2()` | Table A1 |
| EPOCH/SAT or EVENT FLAG record | `EpochRecord2` | Table A2 |
| Its continuation lines (more than 12 satellites) | `SatelliteList`, in `Epoch2.continuation` | Table A2, section 8.1.3 |
| OBSERVATIONS and cycle slip records | `SatelliteRecord`, `Observation` | Table A2 |
| Event records (flags 2 to 5) | `Epoch2.special` | Table A2, section 0.4 |
| Two-digit years, satellite numbers | `full_year()`, `sat_name()` | sections 6.5 and 5.1 |

A # / TYPES OF OBSERV record among the special records of any event (flags
2 to 5) is applied to the epochs after it.

Navigation message files (`NavFile`, `NavRecord`):

| Record | Class | Source |
|---|---|---|
| Header record (content, label) | `HeaderRecord` | RINEX 3.05 Table A5, 4.02 Table A7, 2.11 Tables A3, A10, A15 |
| Data record header line (`> EPH G01 LNAV`) | `NavType` | 4.02 section 5.4.1 |
| SV / EPOCH / SV CLK and the first line of STO, EOP and ION records | `NavEpoch` | 3.05 Table A6, 4.02 Tables A9, A33 to A35 |
| BROADCAST ORBIT and message lines | `NavLine` | same |
| PRN / EPOCH / SV CLK, BROADCAST ORBIT of RINEX 2 | `NavEpoch2`, `NavLine2` | 2.11 Table A4 |

The tables `nav_fields()` names the values by (`NavLayout`):

| Records | Source |
|---|---|
| RINEX 3: GPS, Galileo, GLONASS, QZSS, BDS, SBAS, NavIC/IRNSS | 3.05 Tables A6, A8, A10, A12, A14, A16, A18 |
| RINEX 4 EPH: GPS LNAV, CNAV, CNV2 | 4.02 Tables A9 to A11 |
| Galileo INAV, FNAV | Table A13 |
| GLONASS FDMA, L1OC, L3OC | Tables A15 to A17 |
| QZSS LNAV, CNAV, CNV2 | Tables A19 to A21 |
| BDS D1, D2, CNV1, CNV2, CNV3 | Tables A23 to A26 |
| SBAS; NavIC LNAV, L1NV | Tables A28, A30, A31 |
| RINEX 4 STO, EOP | Tables A33, A34 |
| RINEX 4 ION: Klobuchar, NeQuick-G, BDGIM, NavIC L1NV Klobuchar and NeQuick-N, GLONASS CDMA | Tables A35 to A40 |
| RINEX 2: GPS, GLONASS, GEO | 2.11 Tables A4, A11, A16 |

## Documentation

What gnsswire-rinex does not decode, what its tests rest on and the readings
it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-rinex) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request file types in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT. Notices for the third-party test data in the sdist are in
`tests/THIRD_PARTY_NOTICES.md`.
