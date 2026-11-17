# gnsswire-nav

GNSS navigation messages and ephemerides for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-nav)](https://pypi.org/project/gnsswire-nav/)

gnsswire-nav decodes the navigation messages GNSS satellites broadcast, as
a receiver reports them, and assembles them into ephemerides. It gives you:

- GPS LNAV subframes, Galileo I/NAV and F/NAV pages, BeiDou D1 and D2
  subframes and GLONASS strings, as integer fields, with their parity and
  CRC checks;
- readers for the navigation words in u-blox UBX-RXM-SFRBX and the SkyTraq
  subframe messages;
- ephemeris assembly, giving the fields of the matching RTCM 3 ephemeris
  message (1019, 1020, 1042, 1045, 1046).

It is part of [gnsswire](https://pypi.org/project/gnsswire/), codecs for
GNSS wire formats.

## Installation

```sh
$ pip install gnsswire-nav
```

gnsswire-nav requires Python 3.11+ and depends on
[gnsswire-bits](https://pypi.org/project/gnsswire-bits/) only. It reads the
fields of UBX and SkyTraq messages and gives the fields of RTCM 3 ones, so
install [gnsswire](https://pypi.org/project/gnsswire/) (every format) to
go from bytes to bytes.

## Usage

### Decode a receiver's navigation data

`from_sfrbx` (UBX-RXM-SFRBX) and `from_skytraq` (SkyTraq 0xE0 to 0xE3,
0xE6) turn a receiver's message into a `Received` unit: the system, the
satellite and the decoded subframe, page or string. Here two navigation
data examples of SkyTraq AN0039:

```python
from gnsswire import skytraq
from gnsswire.nav import from_skytraq

for hex_frame in (
    "A0A10021E002058B0BB43F22B54F31CF4EFD81FD4D00A10C9879E70908D5C5F8ED03EBFFF4040D0A",
    "A0A1001FE3CB01E240473795A514C8CAEACFA500155555555555555555555555555555480D0A",
):
    unit = from_skytraq(skytraq.decode(skytraq.parse(bytes.fromhex(hex_frame))))
    print(unit.system, unit.satellite, type(unit.message).__name__)
# gps 2 OtherSubframe
# beidou-d2 3 D2Page6

print(f"semi-major axis {(unit.message.sqrt_a * 2**-19) ** 2 / 1000:.0f} km")   # semi-major axis 42164 km
```

Fields are the ICD's integers, unscaled (`sqrt_a` above is in units of
2^-19 m^1/2). A subframe or page without a table, such as the GPS subframe 5
page above, decodes to the system's `Other` table, its bits kept whole.

### Assemble an ephemeris

An `Assembler` takes units and returns each new complete ephemeris;
`rtcm_fields` gives the keyword arguments of the RTCM 3 message for it.
Here GPS subframes 1 to 3 of satellite 17, in UBX-RXM-SFRBX:

```python
from gnsswire import rtcm3, ubx
from gnsswire.nav import Assembler, from_sfrbx, gps

frames = (
    "B56202133000001100000A0002001200C022B8290000540000160000000000000000000000"
    "000000000069FA810A290000008C00000044F5",
    "B56202133000001100000A0002001200C022002A00000E00800A290000002900000029000000"
    "290000004528000001E04F037C40FA011358",
    "B56202133000001100000A0002001200C022582B000000000000000000000000000000000000"
    "000000000000000000000000F800800A5B21",
)
assembler = Assembler()
for hex_frame in frames:
    eph = assembler.push(from_sfrbx(ubx.decode(ubx.parse(bytes.fromhex(hex_frame)))))

print(eph.satellite, eph.week, eph.iodc, eph.iode, eph.toe)    # 17 352 298 42 2025
msg1019 = rtcm3.Msg1019(**gps.rtcm_fields(eph))
print(len(rtcm3.encode(msg1019)), "bytes of RTCM 1019")      # 67 bytes of RTCM 1019
```

`push` returns `None` until a new ephemeris is complete.

### Check and compute parity

Decoding checks each system's code (parity, CRC or BCH) and raises
`ParityError` when it fails; encoding computes it:

```python
from dataclasses import replace
from gnsswire.nav import ParityError

subframe = from_sfrbx(ubx.decode(ubx.parse(bytes.fromhex(frames[1])))).message
words = gps.encode(replace(subframe, toe=2026))      # ten 30-bit words, parity computed
print(gps.decode(words).toe)                         # 2026
try:
    gps.decode((words[0] ^ 1,) + tuple(words[1:]))
except ParityError as exc:
    print(type(exc).__name__)                        # ParityError
```

Carrier messages go back the other way too: `carriers.sfrbx_fields` and
`carriers.skytraq_fields` give the keyword arguments of the carrier's own
message class, so the round trip is exact.

## Messages

| System | Unit | Integrity check | Decoded |
|---|---|---|---|
| GPS LNAV | subframe: ten 30-bit words | (32,26) Hamming parity | subframes 1 to 3; subframe 4 pages 18 and 25 and subframe 5 page 25 of Data ID 2 |
| Galileo I/NAV | page: even and odd part, 120 bits each | CRC-24Q | word types 0 to 6 and 10 |
| Galileo F/NAV | page of 244 bits | CRC-24Q | page types 1 to 4 |
| BeiDou D1, D2 | subframe: ten 30-bit words | BCH(15,11,1) | D1 subframes 1 to 3, subframe 5 pages 7, 8, 10; D2 subframe 1 pages 1 to 10, subframe 5 pages 35, 36, 102 |
| GLONASS | string of 85 bits | Hamming code | strings 1 to 5, almanac strings 6 to 15 |

Tables are those of IS-GPS-200N, the Galileo OS SIS ICD 2.2,
BDS-SIS-ICD-B1I-3.0 and the GLONASS ICD 5.1. Any other subframe, word, page
or string decodes to the system's `Other` table (`OtherSubframe`,
`InavOther`, `FnavOther`), its bits kept whole. Fields are the ICD's
integers, unscaled; a parameter split across words is one row when its
pieces are adjacent in the data bits, and two (`_msb`, `_lsb`) when they
are not (GPS IODC; BeiDou D2 pages). Decoding checks the code and does not
correct errors; encoding computes it (`gps.solve_t` also solves the `t`
bits that zero D29 and D30 of words 2 and 10, as a satellite does).

## Receivers

| Carrier | Systems |
|---|---|
| UBX-RXM-SFRBX | GPS L1C/A; Galileo E1, E5b (I/NAV); BeiDou B1I, B2I (D1, D2); GLONASS L1OF, L2OF |
| SkyTraq 0xE0 | GPS |
| SkyTraq 0xE1 | GLONASS |
| SkyTraq 0xE2, 0xE3 | BeiDou D1, D2 |
| SkyTraq 0xE6 | Galileo E1, E5b |

`from_sfrbx` and `from_skytraq` read the carrier's message fields, so
gnsswire-nav does not import `gnsswire.ubx` or `gnsswire.skytraq`. Where a
carrier strips a code, the receiver checked it; the unit is completed so
that it decodes like any other. Other signals raise `Unsupported`.

## Ephemerides

| System | Assembled from | RTCM 3 |
|---|---|---|
| GPS | subframes 1, 2, 3 of one issue (IODE = 8 LSBs of IODC) | 1019 |
| Galileo I/NAV | words 1 to 4 of one IODnav, and the latest word 5 | 1046 |
| Galileo F/NAV | page types 1 to 4 of one IODnav | 1045 |
| BeiDou | D1 subframes 1, 2, 3 of one frame; D2 subframe 1 pages 1 to 10 of consecutive frames | 1042 |
| GLONASS | strings 1 to 5 of one frame, in a row | 1020 |

`rtcm_fields(eph)` returns the RTCM message's keyword arguments, `number`
included. For GLONASS, 1020 also needs the frequency channel and the
almanac health of another string: `rtcm_fields(eph, channel=...,
almanac_health=...)`. What the broadcast has and the RTCM message does not
(GPS AODO, Galileo and BeiDou ionosphere, GLONASS reserved bits) stays in
the ephemeris or the decoded tables.

Every exception is a `nav.Error` (a `ValueError`): `ParityError` for a
failed integrity check, `FieldError` (also a `gnsswire.bits.BitError`) for
a value that does not fit its table or units of different issues,
`Unsupported` for a signal or carrier presentation not described above.

## Documentation

What gnsswire-nav does not decode, what its tests rest on and the readings
it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-nav) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request signals in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT. Notices for the third-party test data in the sdist are in
`tests/THIRD_PARTY_NOTICES.md`.
