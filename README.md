# gnsswire

Small, dependency-free Python codecs for GNSS wire formats: NMEA 0183, u-blox
UBX, RTCM 3, SPARTN v2 and the SkyTraq binary protocol, and RINEX 3 and 4
observation files, and the IGS SSR corrections carried in RTCM 3 frames,
written from their published specifications (most are freely available;
RTCM 10403.3 is sold by RTCM). Each codec
is its own installable distribution under one shared import namespace, so a
project can depend on only the one it needs.

| Distribution | Import | Depends on | Contents |
|---|---|---|---|
| `gnsswire-bits` | `gnsswire.bits` | nothing | MSB-first bit reader and writer, CRCs, declarative field tables |
| `gnsswire-nmea` | `gnsswire.nmea` | nothing | sentence framing, GGA, ZDA |
| `gnsswire-ubx` | `gnsswire.ubx` | nothing | framing, RXM-PMP, RXM-RAWX, RXM-SFRBX, NAV-TIMELS |
| `gnsswire-rtcm3` | `gnsswire.rtcm3` | `bits` | framing, ephemerides, MSM1 to MSM7, 1005 to 1008, 1033, 1230; IGS SSR (4076) |
| `gnsswire-spartn` | `gnsswire.spartn` | `bits` | framing, AES-128-CTR, OCB, HPAC, GAD, BPAC |
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
  four CRC types; AES-128-CTR decryption and encryption with a key the caller
  supplies; GAD, BPAC, and OCB and HPAC for GPS, GLONASS, Galileo, BeiDou
  and QZSS; the OCB header of any subtype.
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
verification of SPARTN embedded authentication. The "Limitations" section
of each distribution's README lists what its codec does not decode, what
its tests rest on, and the reading it takes where its specification is
ambiguous.

What is planned next, and what is not planned, is in [docs/ROADMAP.md](docs/ROADMAP.md).

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
  Where a specification is ambiguous, the code says so and the README's
  "Limitations" gives the reading taken.
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
