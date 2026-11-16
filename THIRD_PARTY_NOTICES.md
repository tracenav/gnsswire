# Third-party notices

All code in this repository is under the MIT licence (`LICENSE`). Some test
data is not only this project's work. It is never in a wheel; it is in the
repository and in the sdist of the distribution whose tests use it, together
with its notice:

| Data | Notice | Terms |
|---|---|---|
| `packages/rtcm3/tests/data/public.hex` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause; IGS data, attribution |
| `packages/rtcm3/tests/data/rtklib.hex` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause; IGS data, attribution |
| `packages/rtcm3/tests/data/rtklib-msm.hex` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause; IGS data, attribution |
| `packages/rtcm3/tests/data/rtklib-station.hex` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |
| `packages/rtcm3/tests/data/rtklib-igs.hex` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |
| `packages/rtcm3/tests/data/rtklib-igs-decoded.json` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |
| `packages/rtcm3/tests/data/rtklib-antenna.hex` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |
| `packages/rtcm3/tests/data/rtklib-antenna-decoded.json` | [packages/rtcm3/tests/THIRD_PARTY_NOTICES.md](packages/rtcm3/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |
| `packages/nmea/tests/data/gpsd-zed-f9p.nmea` | [packages/nmea/tests/THIRD_PARTY_NOTICES.md](packages/nmea/tests/THIRD_PARTY_NOTICES.md) | GPSD project, BSD 2-clause |
| `packages/skytraq/tests/data/rtklib-decoded.txt` | [packages/skytraq/tests/THIRD_PARTY_NOTICES.md](packages/skytraq/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |
| `packages/rinex/tests/data/rtklib-read.json` | [packages/rinex/tests/THIRD_PARTY_NOTICES.md](packages/rinex/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |
| `packages/nav/tests/data/rtklib-decoded.txt` | [packages/nav/tests/THIRD_PARTY_NOTICES.md](packages/nav/tests/THIRD_PARTY_NOTICES.md) | RTKLIB, BSD 2-clause |

Each notice file holds the upstream licence text unchanged, where it was
taken from, and the attribution the data's provider asks for.

The tests and READMEs also quote short passages of the specifications the
codecs are written from (example frames and sentences, test vectors, CRC
check values), each cited where it is used. Field tables are written from
the specifications, not copied as text.
