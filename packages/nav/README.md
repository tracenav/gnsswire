# gnsswire-nav

Broadcast navigation messages (GPS LNAV, Galileo I/NAV and F/NAV, BeiDou
D1 and D2, GLONASS strings) as integer fields, their integrity codes, and
their ephemerides, named and scaled as the RTCM 3 ephemeris messages.
Depends on `gnsswire-bits` only.

Import as `gnsswire.nav`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme) for the
version policy. Written from the published interface documents:
IS-GPS-200N with its change notices IRN-IS-200N-003 and IRN-IS-200N-004,
the Galileo OS SIS ICD issue 2.2, BDS-SIS-ICD-B1I-3.0 and the GLONASS ICD
edition 5.1; carrier layouts from the u-blox 8 / M8 Receiver
Description (UBX-13003221, chapter 10) and SkyTraq AN0039.

```python
from gnsswire import skytraq
from gnsswire.nav import beidou, carriers, from_skytraq, gps

# The GPS SUBFRAME example of SkyTraq AN0039 (0xE0): PRN 2, subframe 5.
frame = skytraq.parse(bytes.fromhex(
    "A0A10021E002058B0BB43F22B54F31CF4EFD81FD4D00A10C9879E70908D5C5F8ED03EBFFF4040D0A"), 0)
unit = from_skytraq(skytraq.decode(frame))
assert (unit.system, unit.satellite) == ("gps", 2)
assert (unit.message.preamble, unit.message.subframe) == (0x8B, 5)
words = gps.encode(unit.message)                  # the ten 30-bit words, parity computed
assert gps.decode(words) == unit.message          # parity checked (Table 20-XIV)

# Its BEIDOU2 D2 SUBFRAME example (0xE3): PRN 3, subframe 1 page 6, a GEO's sqrt(A).
frame = skytraq.parse(bytes.fromhex(
    "A0A1001FE3CB01E240473795A514C8CAEACFA500155555555555555555555555555555480D0A"), 0)
page = from_skytraq(skytraq.decode(frame)).message
assert type(page) is beidou.D2Page6 and page.pnum == 6
assert 6490 < page.sqrt_a * 2**-19 < 6496
assert beidou.decode(beidou.encode(page), d2=True) == page   # BCH coded and checked
```

A carrier message becomes a `Received` unit (`from_sfrbx`, `from_skytraq`)
and back (`carriers.sfrbx_fields`, `carriers.skytraq_fields`: the keyword
arguments of the carrier's own message class, so that the round trip is
exact). An `Assembler` takes units and returns each new complete
ephemeris; `rtcm_fields` of the system's module gives the keyword arguments
of the RTCM message:

```python
import dataclasses
from gnsswire import rtcm3, ubx
from gnsswire.nav import Assembler, from_sfrbx

# Three synthetic GPS subframes of one issue (IODE = the 8 LSBs of IODC), in UBX-RXM-SFRBX.
head = dict(preamble=0x8B, tlm=0, integrity=0, reserved_tlm=0, tow=1, alert=0,
            anti_spoof=1, t_how=0)
zero = lambda cls: {f.name: 0 for f in dataclasses.fields(cls) if f.name not in head}
sf1 = gps.Subframe1(**head, **{**zero(gps.Subframe1), "subframe": 1, "week": 352,
                               "iodc_msb": 1, "iodc_lsb": 0x2A, "toc": 2025})
sf2 = gps.Subframe2(**head, **{**zero(gps.Subframe2), "subframe": 2, "iode": 0x2A,
                               "toe": 2025, "sqrt_a": 2_702_000_000})
sf3 = gps.Subframe3(**head, **{**zero(gps.Subframe3), "subframe": 3, "iode": 0x2A})
assembler = Assembler()
for sf in (sf1, sf2, sf3):
    msg = ubx.RxmSfrbx(**carriers.to_sfrbx(carriers.GPS, 17, gps.solve_t(sf)))
    eph = assembler.push(from_sfrbx(msg))
assert (eph.satellite, eph.iodc, eph.iode, eph.toe) == (17, 0x12A, 0x2A, 2025)
msg1019 = rtcm3.Msg1019(**gps.rtcm_fields(eph))
assert msg1019.sqrt_a == 2_702_000_000 and eph.aodo == 0   # AODO is not in 1019
```

## Why a distribution of its own

UBX-RXM-SFRBX and the SkyTraq subframe messages carry the same units: GPS
subframes, Galileo pages, BeiDou subframes, GLONASS strings. Their tables
belong to the systems' ICDs, not to either receiver's protocol, so they are
written once, here, and each carrier is a thin presentation layer over them
(`carriers`). `gnsswire.ubx` and `gnsswire.skytraq` stay what they are,
codecs of their wire formats that keep the navigation words whole, and
need not depend on each other or on this; `gnsswire.nav` does not import
them either (it reads their messages' fields), nor `gnsswire.rtcm3` (it
gives keyword arguments). Only the bit-table interpreter of `gnsswire.bits`
is shared.

## Units, tables and checks

| System | Unit | Integrity check | Tables | Source |
|---|---|---|---|---|
| GPS LNAV | subframe: ten 30-bit words, 240 data bits | (32,26) Hamming parity, D30* inversion | subframes 1 to 3; subframe 4 pages 18 and 25 and subframe 5 page 25, of Data ID 2 | IS-GPS-200N with IRN-IS-200N-003 and IRN-IS-200N-004: 20.3, 20.3.3.5.1.1, 6.4.6.4, Figure 20-1, Tables 20-I, 20-III, 20-V, 20-IX, 20-X, 20-XIV |
| Galileo I/NAV | page: even and odd part, 120 bits each; 128-bit word | CRC-24Q over 196 bits | word types 0 to 6 and 10 | Galileo OS SIS ICD 2.2, 4.3, Tables 37 to 47, 51, 54; 5.1.9.4 |
| Galileo F/NAV | page of 244 bits | CRC-24Q over 214 bits | page types 1 to 4 | same, 4.2, Tables 28, 30 to 33 |
| BeiDou D1, D2 | subframe: ten 30-bit words, 224 information bits | BCH(15,11,1), interleaved | D1 subframes 1 to 3, subframe 5 pages 7, 8, 10; D2 subframe 1 pages 1 to 10, subframe 5 pages 35, 36, 102 | BDS-SIS-ICD-B1I-3.0, 5.1.3, 5.2, 5.3, Figures 5-8 to 5-11, 5-14, 5-18 |
| GLONASS | string of 85 bits | Hamming code, checksums C1 to C7 and CΣ | strings 1 to 5, almanac strings 6 to 15 | GLONASS ICD 5.1, 4.3 to 4.5, 4.7, Tables 4.5, 4.6, 4.9, 4.11 to 4.13 |

Any other subframe, word, page or string decodes to the system's `Other`
table (`OtherSubframe`, `InavOther`, `FnavOther`), its bits kept whole.
Fields are the ICD's integers: two's complement or sign-magnitude as the
ICD says, unscaled; a parameter split across words is one row when its
pieces are adjacent in the data bits, and two (`_msb`, `_lsb`) when they
are not (GPS IODC; BeiDou D2 pages). Decoding checks the code and does not
correct errors; encoding computes it (`gps.solve_t` also solves the `t`
bits that zero D29 and D30 of words 2 and 10, as a satellite does).

## Carriers

| Carrier | Systems | Presentation | Source |
|---|---|---|---|
| UBX-RXM-SFRBX | GPS L1C/A; Galileo E1, E5b (I/NAV); BeiDou B1I, B2I (D1, D2); GLONASS L1OF, L2OF | words with pad bits; GPS and BeiDou parity fields kept; GLONASS string left-aligned, frame number in word 4 | UBX-13003221 R28, 10.2 to 10.5; signal identifiers F9 HPG 1.51 and X20 HPG 2.11, 1.5.4 |
| SkyTraq 0xE0 | GPS | 24 source data bits per word, parity stripped | AN0039 1.4.42 |
| SkyTraq 0xE1 | GLONASS | string number and bits 80 to 9 | same |
| SkyTraq 0xE2, 0xE3 | BeiDou D1, D2 | 224 information bits | same |
| SkyTraq 0xE6 | Galileo E1, E5b | as UBX: even part, 8 pad bits, odd part, 8 pad bits | same |

Where a carrier strips a code, the receiver checked it; the unit is
completed from the ICD so that it decodes like any other. Other signals
raise `Unsupported` (see "Limitations").

## Ephemerides and RTCM

| System | Assembled from | Issue rule | RTCM | The broadcast has, 1019 to 1046 do not | The RTCM message has, the broadcast does not |
|---|---|---|---|---|---|
| GPS | subframes 1, 2, 3 | IODE (2, 3) = 8 LSBs of IODC (1), 20.3.4.4 | 1019 | AODO (kept in `Ephemeris`) | nothing |
| Galileo I/NAV | words 1 to 5 | IODnav of words 1 to 4 equal, 5.1.9.2; latest word 5 | 1046 | ionosphere, GST, GST-UTC (in the word tables) | DF001 reserved (set 0) |
| Galileo F/NAV | page types 1 to 4 | IODnav equal | 1045 | ionosphere, GST, GST-UTC, GST-GPS (in the page tables) | DF001 reserved (set 0) |
| BeiDou | D1 subframes 1, 2, 3 of one frame; D2 subframe 1 pages 1 to 10 of consecutive frames | SOW chain (ICD gives no issue of data across subframes) | 1042 | ionosphere alpha and beta (in the tables) | nothing |
| GLONASS | strings 1 to 5 of one frame, in a row | consecutive strings 1 to 5 | 1020 | the 2 LSBs of Bn (`bn`), reserved bits | DF040 channel (the carrier's: UBX freqId), DF104 and DF105 almanac health (another string's Cn: an argument), DF131 (set 1) |

Field names are the RTCM message's: `rtcm_fields(eph)` (GLONASS:
`rtcm_fields(eph, channel=..., almanac_health=...)`) returns its keyword
arguments with `number` included. QZSS (1044) has no tables here.

Errors: every exception is a `nav.Error` (a `ValueError`): `ParityError`
for a failed integrity check, `FieldError` (also a
`gnsswire.bits.BitError`) for a value that does not fit
its table or units of different issues, `Unsupported` for a signal or
carrier presentation the documents above do not describe.

## Limitations

- Not decoded (`Unsupported`): GPS L2C and L5 (CNAV), Galileo E5a
  (F/NAV) in UBX-RXM-SFRBX, BeiDou B1C and B2a, QZSS, SBAS, IMES and
  NavIC, the UBX signals the u-blox F9 HPG 1.51 description lists and
  1.32 did not (Galileo E6, BeiDou B3I, the B1C and B2a data components)
  and QZSS L1C/B, which X20 HPG 2.11 adds (no staged document lays out
  their words), and SkyTraq 0xE6 for anything but Galileo E1 and E5b. (F/NAV
  pages obtained some other way do decode.) QZSS ephemerides (1044) are
  not assembled.
- Galileo I/NAV word types other than 0 to 6 and 10, and F/NAV page types
  5 and 6, are kept whole (`InavOther`, `FnavOther`).
- GPS subframe 4 and 5 pages whose Data ID is not 2 (binary 01) are kept
  whole (`OtherSubframe`): IRN-IS-200N-003 reserves the other Data IDs for
  future data structures and asks users to check the Data ID before
  decoding (IS-GPS-200N 6.4.6.4 as it amends it).
- Errors are detected, never corrected.
- Tested on synthetic frames, on RTKLIB's decoding of synthetic
  UBX-RXM-SFRBX frames (GPS, Galileo, BeiDou D1 and D2, GLONASS) and on the
  five navigation data examples of SkyTraq AN0039; the test data holds no
  receiver capture.
- Galileo E5b, in UBX-RXM-SFRBX and SkyTraq 0xE6, is taken to be laid out
  as E1, the only one the documents draw; UBX sigId 0 and 1 (E1) and 5
  and 6 (E5b) are all read as I/NAV.
- UBX GPS words: the parity bits are taken to be complemented with the
  data, the whole 30-bit word when the previous word's D30 is 1.
- UBX BeiDou words: parity fields of all zeros, which receivers send, are
  accepted unchecked; any other value is read as P1(1) to P1(4) then P2(1)
  to P2(4) and must equal the BCH code, so a receiver sending another order
  would get `ParityError`.
- BeiDou issues: the ICD ties no issue across subframes, so the assembler
  ties D1 subframes 2 and 3 to subframe 1 by SOW within one frame, and D2
  pages 1 to 10 by SOW over ten consecutive frames.
- Galileo word 5 has no IODnav: the latest one is taken, so a change in it
  gives a new ephemeris of the same issue.
- GLONASS strings do not hold their frame number, so strings 14 and 15 of
  frame 5 decode as almanac unless it is given (`decode(..., frame=5)`).

## Licence

Released under the MIT licence. The sdist (not the wheel) also holds
`tests/data/rtklib-decoded.txt`, this project's synthetic UBX-RXM-SFRBX
frames with the ephemerides RTKLIB decoded from them, under RTKLIB's BSD
2-clause licence; its notice is in `tests/THIRD_PARTY_NOTICES.md`, and how
it was made in `tests/make_data/README.md`.
