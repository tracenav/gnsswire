# gnsswire-antex

ANTEX antenna calibration files for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-antex)](https://pypi.org/project/gnsswire-antex/)

gnsswire-antex reads and writes ANTEX 1.4 files, the text format in which
the phase centre offsets and phase centre variations of GNSS receiver and
satellite antennas are exchanged (the IGS models `igs14.atx` and
`igs20.atx`, for example). It gives you:

- the header and every antenna: its type and serial number, its grid, its
  validity, and per frequency the offsets and the pattern rows, with the
  optional rms sections;
- a lossless round trip: `write(read(text)) == text` for every file `read`
  accepts;
- every field as the text in its columns, and numeric fields as exact
  integers on request, without floating point.

It is part of [gnsswire](https://pypi.org/project/gnsswire/), codecs for
GNSS wire formats.

## Installation

```sh
$ pip install gnsswire-antex
```

gnsswire-antex requires Python 3.11+ and has no dependencies. `pip install
gnsswire` installs it with every other format.

## Usage

### Read a file

`read(text)` gives an `AntexFile`: the header records, then each antenna.
The text is the file's, decoded (ANTEX files are ASCII; `encoding="latin-1"`
reads any of them):

```python
from gnsswire import antex

text = (
    "     1.4            M                                       ANTEX VERSION / SYST\n"
    "A                                                           PCV TYPE / REFANT\n"
    "                                                            END OF HEADER\n"
    "                                                            START OF ANTENNA\n"
    "EXAMPLE_ANT     NONE                                        TYPE / SERIAL NO\n"
    "ROBOT               Example Agency           2    17-NOV-26 METH / BY / # / DATE\n"
    "   120.0                                                    DAZI\n"
    "     0.0  90.0  45.0                                        ZEN1 / ZEN2 / DZEN\n"
    "     1                                                      # OF FREQUENCIES\n"
    "   G01                                                      START OF FREQUENCY\n"
    "      0.58     -0.37     91.25                              NORTH / EAST / UP\n"
    "   NOAZI    0.00   -1.52    3.10\n"
    "     0.0    0.00   -1.40    3.31\n"
    "   120.0    0.00   -1.66    2.87\n"
    "   240.0    0.00   -1.49    3.12\n"
    "   360.0    0.00   -1.40    3.31\n"
    "   G01                                                      END OF FREQUENCY\n"
    "                                                            END OF ANTENNA\n"
)
file = antex.read(text)          # for a file: antex.read(open(path, encoding="latin-1", newline="").read())
print(file.version, file.system, file.pcv_type.pcv_type.strip())    # 1.4 M A

antenna = file.antennas[0]
print(repr(antenna.type), repr(antenna.serial.strip()))    # 'EXAMPLE_ANT     NONE' ''
print(antenna.grid.zen1, antenna.grid.zen2, antenna.grid.dzen, antenna.dazi)
#      0.0   90.0   45.0    120.0
print(antenna.zeniths, antenna.azimuths)    # (0, 450, 900) (0, 1200, 2400, 3600), in 0.1 degree
```

A blank serial number means every antenna of the type. A satellite
antenna has the same records: its `serial` is the satellite code (`G05`),
and `antenna.type_serial` also holds its `svn` and `cospar` fields;
`antenna.valid_from` and `antenna.valid_until` give its validity period,
`antenna.sinex_code` and `antenna.comments` the rest.

### Offsets and pattern of a frequency

`antenna.frequencies` holds the frequency sections by code. Each has the
NORTH / EAST / UP fields (`offset`), the non-azimuth-dependent row
(`noazi`) and one row per azimuth (`rows`; none when DAZI is 0.0), whose
values run from ZEN1 to ZEN2:

```python
g01 = antenna.frequencies["G01"]
print(g01.offset.north, g01.offset.east, g01.offset.up)    #       0.58      -0.37      91.25
print(g01.noazi.values)                     # ('    0.00', '   -1.52', '    3.10')
for row in g01.rows:
    print(row.azimuth, row.values)          #    120.0 ('    0.00', '   -1.66', '    2.87'), ...
print(antenna.rms)                          # {}: this antenna has no rms sections
```

For a satellite antenna the three offset fields are X, Y and Z, and the
grid is in nadir angle. rms sections (START OF FREQ RMS), where a file has
them, are in `antenna.rms`, by the same codes and with the same layout.

### Exact numbers

Every field is the text in the record's columns, blanks included, so
nothing is lost. `number(field, decimals)` gives a numeric field as the
integer of its digits, without floating point. Offsets and pattern values
are millimetres with two decimals, so in units of 0.01 mm:

```python
print(antex.number(g01.offset.up, 2))                        # 9125
print([antex.number(v, 2) for v in g01.rows[1].values])      # [0, -166, 287]
print(antex.number(antenna.method.count))                    # 2 antennas calibrated
```

Nothing is scaled or given a sign here; how the values are applied is
section 3 of the ANTEX document.

### Write it back

`write(file)` gives the text back, exactly as read:

```python
print(antex.write(file) == text)                     # True
```

Every labelled line is a `Record` (its 60 columns of content and its
label); `fields(record)` gives the content as the dataclass of its columns
and `record(label, fields)` builds a record from one, for a file made or
changed in Python:

```python
from dataclasses import replace

dazi = antenna.records[3]
print(antex.fields(dazi))               # Dazi(dazi='   120.0', blank='   ...   ')
print(antex.record("DAZI", antex.Dazi("   120.0")) == dazi)   # True

# Records are frozen: change one with replace(). write() checks the result as read() does.
renamed = replace(antenna, records=(
    *antenna.records[:1],
    antex.record("TYPE / SERIAL NO", antex.TypeSerial(
        "EXAMPLE_ANT     NONE", "SN 0042".ljust(20), " " * 10, " " * 10)),
    *antenna.records[2:]))
print(antex.read(antex.write(replace(file, antennas=(renamed,)))).antennas[0].serial.strip())
# SN 0042
```

A file of another format version raises `Unsupported`; text that does not
follow the format (records out of order, a row that disagrees with the
grid) raises `Invalid`. Both, and the error `number` raises for a field
that is not a number of its format, derive from `antex.Error`, a
`ValueError`.

### Large files

Reading is one pass over the lines. The IGS model `igs20.atx` (62 MB,
934 antennas, 350,000 pattern rows) reads in a little over a second and
writes in about three (CPython 3.14, a 2020s laptop); `write` takes longer
because it reads its own output back to check it.

## Records

Every record of section 4 of "ANTEX: The Antenna Exchange Format, Version
1.4" (Rothacher and Schmid, 15 September 2010):

| Record | Class | Where |
|---|---|---|
| ANTEX VERSION / SYST | `Version` | `AntexFile.header`, `.version`, `.system` |
| PCV TYPE / REFANT | `PcvType` | `AntexFile.pcv_type` |
| COMMENT | `Comment` | `AntexFile.comments`, `Antenna.comments` |
| END OF HEADER, START OF ANTENNA, END OF ANTENNA | `Blank` | `AntexFile.header`, `Antenna.records`, `Antenna.end` |
| TYPE / SERIAL NO | `TypeSerial` | `Antenna.type_serial`, `.type`, `.serial` |
| METH / BY / # / DATE | `Method` | `Antenna.method` |
| DAZI | `Dazi` | `Antenna.dazi`, `.azimuths` |
| ZEN1 / ZEN2 / DZEN | `Grid` | `Antenna.grid`, `.zeniths` |
| # OF FREQUENCIES | `Frequencies` | `Antenna.records` |
| VALID FROM, VALID UNTIL | `Epoch` | `Antenna.valid_from`, `.valid_until` |
| SINEX CODE | `SinexCode` | `Antenna.sinex_code` |
| START OF FREQUENCY, END OF FREQUENCY | `FrequencyCode` | `Pattern.start`, `.end`, `.code`; `Antenna.frequencies` |
| NORTH / EAST / UP | `Offset` | `Pattern.neu`, `.offset` |
| NOAZI row, azimuth rows | `Row` | `Pattern.noazi`, `.rows` |
| START OF FREQ RMS, END OF FREQ RMS | `FrequencyCode` | `Pattern.rms`; `Antenna.rms` |

`TABLE` maps each label to its class, and `FREQUENCIES` lists the
frequency codes the document names (`G01` is L1, `E05` is E5a, and so on);
other codes, which later RINEX versions define, are read the same way.

## Documentation

What gnsswire-antex checks and does not check, what its tests rest on and
the readings it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-antex) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request formats in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT.
