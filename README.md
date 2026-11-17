# gnsswire

Small, dependency-free Python codecs for GNSS wire formats: NMEA 0183, u-blox
UBX, RTCM 3, SPARTN v2 and the SkyTraq binary protocol, and RINEX 3 and 4
observation files, and the IGS SSR corrections carried in RTCM 3 frames,
written from their published specifications. Each codec is its own
installable distribution under one shared import namespace, so a project
can depend on only the one it needs.

| Distribution | Import | Depends on | Contents |
|---|---|---|---|
| `gnsswire-bits` | `gnsswire.bits` | nothing | MSB-first bit reader and writer, CRCs, declarative field tables |
| `gnsswire-nmea` | `gnsswire.nmea` | nothing | sentence framing, GGA, ZDA |
| `gnsswire-ubx` | `gnsswire.ubx` | nothing | framing, RXM-PMP, RXM-RAWX, RXM-SFRBX, NAV-TIMELS |
| `gnsswire-rtcm3` | `gnsswire.rtcm3` | `bits` | framing, ephemerides, MSM1 to MSM7, 1005 to 1008, 1033, 1230; IGS SSR (4076) |
| `gnsswire-spartn` | `gnsswire.spartn` | `bits` | framing, OCB, HPAC, GAD, BPAC; AES-128-CTR decryption |
| `gnsswire-skytraq` | `gnsswire.skytraq` | nothing | framing, raw measurements, navigation data bits |
| `gnsswire-rinex` | `gnsswire.rinex` | nothing | RINEX 3 and 4 observation files, read and written losslessly |
| `gnsswire-nav` | `gnsswire.nav` | `bits` | broadcast navigation messages (GPS, Galileo, BeiDou, GLONASS) from UBX and SkyTraq words; ephemerides as RTCM fields |
| `gnsswire` | (none) | all of the above | installs every codec |

Pure Python, standard library only, Python 3.11 or later.

## Install

```sh
pip install gnsswire            # every codec
pip install gnsswire-rtcm3      # one codec (and gnsswire-bits, which it uses)
```

## Use

Every codec of a binary or sentence format has the same four functions
(RINEX files are read and written whole instead, with `read` and `write`;
see `packages/rinex/README.md`):

```text
parse(buf, offset) -> Frame | NeedMore | Invalid   # is there a valid frame here; never searches
scan(buf, offset)  -> Iterator[Frame]              # every valid frame, skipping bad bytes
decode(frame)      -> message                      # frozen dataclass of raw integer fields
encode(message)    -> bytes
```

```python
from gnsswire import rtcm3

# The 1005 example of RTCM 10403.3 section 4.2, behind a garbage byte.
stream = b"\x00" + bytes.fromhex("D300133ED7D30202980EDEEF34B4BD62AC0941986F33360B98")

for frame in rtcm3.scan(stream):
    message = rtcm3.decode(frame)                 # a Msg1005
    assert rtcm3.encode(message) == stream[frame.offset:frame.offset + frame.length]

assert (message.station, message.x) == (2003, 11141045999)    # x in units of 0.0001 m
```

Messages hold the integers that are on the wire (NMEA fields stay strings).
Scaling to metres, seconds or degrees is the caller's job, which keeps every
codec lossless: `encode(decode(frame))` gives back the frame's bytes,
including data a newer version of the specification may append to a message
(kept as `extension`), for every frame a conforming transmitter can send.
A receiver is asked to accept a little more than that: RTCM header bits
"not defined" but not guaranteed to be zero, and in NMEA lowercase
checksum digits or a line ending other than CR LF. Those belong to the
frame, not the message, so `encode(frame)` keeps them while
`encode(decode(frame))` writes what the specification asks a transmitter to
send. Each distribution's README lists its messages, with the specification
table each is written from, and has examples.

Every exception a codec raises derives from its `Error` (a `ValueError`),
and `decode` given anything but a `Frame` (such as the `NeedMore` or
`Invalid` that `parse` returns) raises its `NoFrame`, also a `TypeError`;
`Unsupported`, where a codec has it, is also a `LookupError`. Every function that
takes bytes takes any bytes-like object, a `memoryview` or `bytearray`
included.

## What is implemented

- **NMEA 0183**: framing and checksum; GGA and ZDA from any talker.
- **UBX**: framing and checksum; RXM-PMP (versions 0 and 1), RXM-RAWX
  (version 1; floating-point fields as the integers of their bits),
  RXM-SFRBX (the navigation words as integers) and NAV-TIMELS.
- **RTCM 3**: framing and CRC-24Q; the station and antenna messages 1005,
  1006, 1007, 1008 and 1033; 1230; the ephemerides 1019
  (GPS), 1020 (GLONASS), 1042 (BeiDou), 1044 (QZSS), 1045 and 1046
  (Galileo); MSM1 to MSM7 for GPS, GLONASS, Galileo, SBAS, QZSS and BeiDou
  (1071 to 1127), on one shared table. IGS SSR, the proprietary message
  4076 of the IGS, from IGS SSR v1.00: orbit, clock, combined, high rate
  clock, code bias, phase bias and URA messages for GPS, GLONASS, Galileo,
  QZSS, BeiDou and SBAS, and the VTEC spherical harmonics message, chosen
  by sub-type. It is part of `gnsswire-rtcm3`, not a distribution of its
  own, because it travels in RTCM 3 frames among standard messages and is
  known only by its message number (`packages/rtcm3/README.md`, "IGS
  SSR").
- **SPARTN v2**: framing of TF001 to TF018 with both time tag widths and all
  four CRC types; OCB and HPAC for GPS, GLONASS, Galileo, BeiDou and QZSS,
  GAD and BPAC; the OCB header of any subtype; and, for encrypted services,
  AES-128-CTR decryption and encryption with a key the caller supplies.
- **SkyTraq binary protocol**: framing and checksum; MEAS_TIME (0xDC),
  RAW_MEAS (0xDD), EXT_RAW_MEAS version 1 (0xE5), and the navigation data
  messages 0xE0 to 0xE3 (GPS, GLONASS, BeiDou D1 and D2) and GENERAL
  SUBFRAME version 1 (0xE6), from SkyTraq AN0039.
- **RINEX 3 and 4 observation files**: `read` and `write` (not the four
  functions of the binary codecs), lossless; every record as the text of
  its columns, observation types from SYS / # / OBS TYPES, event records,
  RINEX 4's picosecond field.

Not implemented (decoding raises `Unsupported`): other NMEA sentences, other
UBX messages, the standard RTCM SSR messages (1057 to 1068 and 1240 to
1270; IGS SSR is decoded), RTCM 1041 and 1043 and NavIC MSM (not in RTCM
10403.3), other RTCM messages, other SkyTraq messages, RINEX 2 and RINEX
navigation, meteorological and clock files, the SPARTN dynamic key and
group authentication messages, ciphers other than AES-128, and
verification of SPARTN embedded authentication. "Limitations", below,
lists for each distribution what its codec does not decode, what its tests
rest on, and the reading it takes where its specification is ambiguous.

What is planned next, and what is not planned, is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Limitations

What each distribution does not decode, what its tests rest on, and the
reading it takes where its specification is ambiguous.

### gnsswire-nmea

- Only GGA and ZDA are decoded. Other sentences (RMC, GNS, GSA, GSV and
  the rest) and proprietary ones (`PUBX`, or any address starting with
  `P`) raise `Unsupported`.
- A talker is any two uppercase letters not starting with `P`; written
  from the u-blox description, this rule is not checked against NMEA 0183.
- TAG blocks (`\s:1*78\` before the `$`) and `!`-led encapsulation
  sentences (AIS and similar) are not framed: `scan` yields the sentence
  after a TAG block (the block ends at `frame.offset`) and skips `!`
  sentences.
- A bare CR is not a line ending. A sentence longer than `MAX_LENGTH`
  (4096 bytes, a bound for resynchronising, not the standard's 82
  characters) is `Invalid`.
- GGA and ZDA are tested on a receiver's log (from the GPSD project); the
  lenient forms (lowercase checksum digits, LF endings, missing or extra
  fields) only on sentences built for the tests.

### gnsswire-ubx

- Only the messages and versions its README lists are decoded. Other
  messages raise `Unsupported`, among them the security and trusted time
  messages (SEC-OSNMA, SEC-SIG, SEC-SIGLOG and NAV-TIMETRUSTED), and so
  does a version byte no table has, such as RXM-RAWX version 0 or an
  RXM-SFRBX version other than 2.
- RXM-SFRBX navigation words are kept whole; `gnsswire-nav` reads them.
- Every message is tested on frames built from its table and on frames
  made by pyubx2; the test data holds no receiver capture.

### gnsswire-rtcm3

- Not decoded (`decode` raises `Unsupported`): the standard RTCM SSR
  messages, 1057 to 1068 and 1240 to 1270 (IGS SSR, 4076, is decoded);
  1041 (NavIC) and 1043 (SBAS) ephemerides and NavIC MSM (1131 to 1137),
  which RTCM 10403.3 does not define; every other message number not in
  its README's tables, such as 1001 to 1004 and 1009 to 1012; and the IGS SSR
  sub-types Table 5 reserves (NavIC's 141 to 160, and 202 to 254, among
  them).
- Tested on receiver data: 1005, 1019, 1020, 1033 and the MSM7 of GPS,
  GLONASS, QZSS and BeiDou, from public reference station captures. Every
  other message (1006 to 1008, 1230, 1042, 1044 to 1046, MSM1 to MSM6, the
  MSM of Galileo and SBAS, and IGS SSR) is tested only on frames built
  from the tables and frames made by RTKLIB's encoder, and compared with
  pyrtcm; data after a table only on frames built for the tests.
- MSM: the four extended satellite information bits (Table 3.5-81: DF419
  for GLONASS, reserved for the other systems) are kept in `extended_info`
  for every system.
- IGS SSR Table 9 prints the orbit message's fifth and sixth rows with
  swapped IDF numbers; the names and widths printed are followed:
  cross-track (int20), then radial rate (int21), as in Table 13.
- IGS SSR IM201 with an order above its degree (M > N, which section 4.5.1
  rules out): the coefficients are counted by section 8.4.1's loops, with M
  taken as min(M, N).
- IGS SSR: the tables of v1.00 are applied whatever the IGM/IM version
  (IDF001, kept as `version`); v1.00 does not say whether a version changes
  a table.
- `IGS_SIGNALS` is Table 7 as printed; GLONASS 10 and BDS 19, which it
  leaves unstated, are absent. Signal identifiers are kept as sent.

### gnsswire-spartn

**Data after a table.** Section 8.4 item 4: "decoder implementations should
not use payload length to indicate where they stop decoding", so that
fields can be added to a message later. `decode` keeps whatever follows the
table in the body's `extension`: `None` for nothing but zero fill bits,
otherwise a `gnsswire.bits.Extension` that `encode` writes back, so the
frame round-trips. `decode(frame, strict=True)` refuses such a payload with
`FieldError`.

**OCB header of any subtype.** Section 8.4 item 5 asks decoders to read
the end-of-set flag (SF010) of every OCB message "even though they may not
understand the data". `decode_ocb_header(frame)` reads the header block of
Table 6.3 for every subtype, 0 to 15; `ephemeris_type`, `mask_size` and
`mask` are `None` for subtypes without a table (their widths depend on the
constellation).

**Do-not-use satellites (AMBIGUOUS).** Table 6.2 says a satellite with SF013
(DNU) set carries no other data; Table 8.2 sizes its block as SF013, SF014
and SF015. This codec follows Table 6.2: SF013 is defined there twice in the
same words, Table 8.2 only gives "nominal" sizes, and its OCB header length
does not hold for every constellation either. Where a payload fits only the
Table 8.2 reading, the tolerant `decode` returns that reading instead, and
`spartn.dnu_reading(message.body)` reports which one it is
(`DNU_TABLE_6_2` or `DNU_TABLE_8_2`); `encode` writes a message back with
the reading it was decoded with. `strict=True` accepts Table 6.2 only.

**BPAC VTEC blocks (AMBIGUOUS).** Table 6.26 repeats the VTEC block "for each
grid point", while SF079 is a mask of the grid points present and Table 8.2
counts the blocks as the number of points present. The codec follows the
mask: one `BpacGridPoint` per set bit of `present`.

**Time tags and the IV.** A frame with the 16-bit time tag (seconds within
a half day of the constellation's time) needs the caller to supply the full
32-bit tag for the IV (`decrypt(frame, key, time_tag)`): section 8.15.1
does not say how to expand it. `iv`, `decrypt` and `encrypt` raise
`TimeTagError` when the full tag supplied does not reduce to the frame's
16-bit tag (`time_tag % HALF_DAY`), or when a frame with a 32-bit tag is
given another one.

- Not decoded (`Unsupported`): the dynamic key message (SM 4-0, which
  `decrypt` and `encrypt` refuse too), group authentication (SM 4-1),
  proprietary messages, and any other type or subtype without a table
  in its README; `decode_ocb_header` still reads the header of every OCB subtype.
- Decryption is AES-128-CTR with a 16-byte key only: the other key lengths
  of SF087 and the ChaCha12 and ChaCha20 ciphers of SF085 are not
  implemented. Embedded authentication data (TF017) is kept, not verified.
- Tested only on frames generated from the tables, compared with pyspartn,
  and decryption against the `cryptography` package; the test data holds
  no frame from a correction service. pyspartn refuses OCB frames with an
  extended bias mask, so those are checked by round trips and Table 8.2's
  sizes only.
- The message CRCs (TF018) are taken unreflected, as Table 7.2 prints
  them: CRC-8/SMBUS, CRC-16/XMODEM, CRC-24/LTE-A and CRC-32/BZIP2.
  TF006's CRC-4 is the reflected one of Table 7.1.
- TF017 is read whenever TF014 is above 1, with the lengths Table 7.1
  gives every TF015 value.
- Do-not-use satellites, BPAC blocks and 16-bit time tags: the readings
  taken are in the sections above.

### gnsswire-skytraq

- Only the eight messages its README lists are decoded. Other messages, such as
  SV_CH_STATUS (0xDE), RCV_STATE (0xDF) and the rest of AN0037, raise
  `Unsupported`, and so do EXT_RAW_MEAS (0xE5) and GENERAL SUBFRAME (0xE6)
  of a version other than 1.
- The checksum is the XOR of the PL payload bytes, from the message ID, as
  AN0039's prose says; its pseudo-code, read literally, would take one
  byte more.
- SVIDs are kept as sent; AN0039's numbering (GLONASS slot + 64, BeiDou
  SVID + 200, IRNSS SVID + 240) is the caller's to apply.
- Tested on AN0039's example frame of each message and on synthetic
  frames, with RTKLIB's decoding of synthetic 0xDC, 0xDD and 0xE5 frames
  as a cross-check; the test data holds no receiver capture.

### gnsswire-rinex

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

### gnsswire-nav

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

### gnsswire-bits

- Bits are read and written most significant first. Byte-oriented
  layouts, such as UBX's little-endian and SkyTraq's big-endian fields,
  are not described with these tables: `gnsswire.ubx` and
  `gnsswire.skytraq` read their own.
- A value is checked against its field's width only. A narrower range a
  specification gives (such as 0 to 31 for an 8-bit RTCM counter) is the
  caller's to check.
- SPARTN's message CRCs: both readings are provided (its README lists them);
  `gnsswire-spartn` uses the unreflected one of each.

## Versions

Each distribution has its own version, in its `pyproject.toml`, and is
released on its own: a release of one does not move the others. Each
release, with the versions of the distributions it covers, is listed in
[RELEASES.md](RELEASES.md). `tests/test_build.py` enforces the mechanical
parts of this policy.

- Versions are `MAJOR.MINOR.PATCH`. Before 1.0, `MINOR` is the
  compatibility number: `0.MINOR.x` releases are compatible with each other,
  and a change of `MINOR` may break. From 1.0, `MAJOR` takes that role. A
  new distribution starts at 0.1.0.
- **Breaking** (new compatibility number): removing or renaming a public name,
  a dataclass field or a function parameter; adding, removing or reordering a
  dataclass field (messages are constructed positionally); changing what any
  frame decodes to, or what any message encodes to, even to correct a field
  table against its specification, because a consumer may have stored the
  old values; refusing a frame or message that was accepted; raising
  `requires-python`.
- **Compatible** (new `MINOR`, or new `PATCH` before 1.0): a new message
  table, a new message version, or a new constellation, so that a frame that
  raised `Unsupported` now decodes; new public names; documentation and
  tests.
- **Patch**: a fix that changes no decoded value and no encoded byte for any
  input that was accepted, such as a wrong exception type or message.
- A distribution that uses another `gnsswire` distribution requires the
  compatible range of the version it is tested with, `>=` that version and
  `<` the next compatibility number (`gnsswire-bits>=0.2.0,<0.3` now), so
  that a breaking release cannot be installed under it unnoticed. The range
  moves when the dependency takes a new compatibility number; within one,
  its lower bound moves when the dependent needs the newer release. The
  `gnsswire` distribution requires the compatible range of every codec in
  the same way, and takes a new compatibility number whenever one of those
  ranges moves.
- Every distribution declares the same `requires-python`.
- A release is tagged `<distribution>-<version>`, for example
  `gnsswire-rtcm3-0.2.0`.

## Contribute

```sh
uv sync
uv run pytest
```

`uv run pytest` is the gate, and CI runs it on Linux, macOS and Windows for
every supported Python version. Besides each codec's tests it runs every
```` ```python ```` block of the READMEs (`tests/test_readmes.py`), checks the
workspace rules (`tests/test_layout.py`), and builds every wheel and sdist
offline to check what each contains (`tests/test_build.py`). The build uses
the copy of hatchling pinned in the dev group, so after `uv sync` nothing is
downloaded.

A change keeps to these rules:

- Every field table and framing rule is written from a published
  specification and cites it by document and section or table; nothing is
  taken from a vendor's library, SDK or binary or from another decoder.
  Where a specification is ambiguous, the code says so and "Limitations"
  in this README gives the reading taken.
- A message is a frozen dataclass of the integers on the wire (text for
  NMEA and RINEX), unscaled, and `encode(decode(frame))` gives back the
  frame's bytes. A new message is a new declarative table, tested on frames
  built from the specification and, where one exists, against an
  independent open-source decoder (pyrtcm, pyubx2, pynmeagps, pyspartn;
  dev dependencies only).
- Test data is public or synthetic. A file that is not wholly this
  project's work goes in the package's `tests/data/`, is listed in
  `THIRD_PARTY` in `tests/test_build.py` and in
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and has its upstream
  licence and attribution in the package's `tests/THIRD_PARTY_NOTICES.md`.
- No recording from a paid correction service, and no key, is committed.
  Some tests also read recordings from `build/private/` (gitignored) when
  it exists, and skip without it.

## Licence

MIT, for every distribution ([LICENSE](LICENSE)). Some test data, shipped in
the repository and in the `gnsswire-rtcm3`, `gnsswire-nmea`,
`gnsswire-skytraq`, `gnsswire-rinex` and `gnsswire-nav` sdists but never in
a wheel, comes from RTKLIB, the GPSD project and the IGS; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
