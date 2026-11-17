# gnsswire-rinex

RINEX observation files for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-rinex)](https://pypi.org/project/gnsswire-rinex/)

gnsswire-rinex reads and writes RINEX 3 and 4 observation files, the
standard text format for exchanging GNSS observations. It gives you:

- the header, every epoch and every satellite's observations, as the text
  in each record's columns;
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

A file of a kind this codec does not read (RINEX 2, navigation, compressed)
raises `Unsupported`; text that does not follow the tables raises `Invalid`.
Both, and the error `number` raises for a field that is not a number of
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
