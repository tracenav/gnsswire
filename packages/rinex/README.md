# gnsswire-rinex

RINEX 3 and 4 observation files, read and written losslessly. Standard
library only.

Import as `gnsswire.rinex`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme) for the
version policy. Written from the freely available RINEX 3.05 and 4.02
documents of the IGS/RTCM RINEX working group.

Unlike the binary codecs, a RINEX file is text read whole: `read(text)`
gives an `ObsFile`, `write(obs)` gives the text back, and
`write(read(text)) == text` for every file `read` accepts. Every record is a
frozen dataclass whose fields are the text in the record's columns, leading
blanks included, as the RINEX tables lay them out (as `gnsswire.nmea` keeps
its fields as strings). `number(field, decimals)` gives a numeric field as
the integer of its digits, without floating point.

```python
from gnsswire import rinex

text = (
    "     3.05           OBSERVATION DATA    G                   RINEX VERSION / TYPE\n"
    "G    4 C1C L1C D1C S1C                                      SYS / # / OBS TYPES\n"
    "                                                            END OF HEADER\n"
    "> 2026 01 02 03 04  5.0000000  0  1\n"
    "G06  23629347.915   119876543.2107       -353.123          44.250\n"
)
obs = rinex.read(text)
assert rinex.write(obs) == text
assert rinex.obs_types(obs.header) == {"G": ("C1C", "L1C", "D1C", "S1C")}

epoch = obs.epochs[0]
assert (epoch.record.year, epoch.record.flag, epoch.record.count) == (" 2026", "  0", "  1")
g06 = epoch.satellites[0]
assert g06.sat == "G06"
assert rinex.number(g06.obs[0].value, 3) == 23_629_347_915     # C1C in mm
assert (g06.obs[1].value, g06.obs[1].lli, g06.obs[1].ssi) == (" 119876543.210", "7", " ")
# S1C ends the line: its LLI and SSI columns were truncated with the blanks.
assert (g06.obs[3].value, g06.obs[3].lli, g06.obs[3].ssi) == ("        44.250", "", "")
```

| Record | Class | Source |
|---|---|---|
| Header record (content, label) | `HeaderRecord` | RINEX 3.05 and 4.02, Table A2 |
| SYS / # / OBS TYPES | `obs_types()` | same |
| EPOCH record | `EpochRecord` | Table A3 (`picoseconds`: 4.02 only) |
| OBSERVATION and cycle slip records | `SatelliteRecord`, `Observation` | Table A3, section 6.7 |
| Event records (flags 2 to 5) | `Epoch.special` | Table A3, section 5.3.2 |

Observation types redefined by a header event (flag 4) are applied to the
epochs after it; `obs_types(epoch.special, types)` gives the types after
such an event from those before it. A file of a kind this codec does not
read raises `Unsupported` (see "Limitations"); text that does not follow
the tables raises `Invalid`.
Both, and the error `number` raises for a field that is not a number of
its format, derive from `rinex.Error`, a `ValueError`.

## Limitations

- RINEX 2 files, and navigation, meteorological and clock files, raise
  `Unsupported`. Compressed files (Hatanaka CRINEX, gzip) must be expanded
  first.
- Header records other than RINEX VERSION / TYPE, SYS / # / OBS TYPES and
  END OF HEADER are kept as text, unread: SYS / SCALE FACTOR in particular
  is not applied, and values stay as written.
- Fields are cut at the tables' columns. A field written out of place is
  read as the text in those columns, not refused, unless it breaks a rule
  the reader checks (such as the epoch flag, a record count or a
  satellite number); numeric formats are checked only by `number`.
- Tested on files built from the tables' formats, generated files and
  RTKLIB's reading of a synthetic file; the test data holds no file from
  a receiver or an IGS station.

## Licence

Released under the MIT licence. The sdist (not the wheel) also holds
`tests/data/rtklib-read.json`, a synthetic observation file of this project
with the observations RTKLIB read from it, under RTKLIB's BSD 2-clause
licence; its notice is in `tests/THIRD_PARTY_NOTICES.md`, and how it was
made in `tests/make_data/README.md`.
