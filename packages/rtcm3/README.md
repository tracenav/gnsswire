# gnsswire-rtcm3

RTCM 3 messages for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-rtcm3)](https://pypi.org/project/gnsswire-rtcm3/)

gnsswire-rtcm3 reads and writes RTCM 3, the format reference stations and
correction networks use to send observations and corrections to RTK
receivers. It decodes:

- MSM1 to MSM7 observations for GPS, GLONASS, Galileo, SBAS, QZSS and BeiDou;
- broadcast ephemerides (1019, 1020, 1042, 1044, 1045, 1046);
- station position, antenna and receiver (1005 to 1008, 1033, 1230);
- IGS SSR orbit, clock, bias, URA and ionosphere corrections (4076).

Every message decodes to a frozen dataclass of the integers on the wire and
encodes back to the same bytes. It is part of
[gnsswire](https://pypi.org/project/gnsswire/), codecs for GNSS wire
formats.

## Installation

```sh
$ pip install gnsswire-rtcm3
```

gnsswire-rtcm3 requires Python 3.11+ and depends on
[gnsswire-bits](https://pypi.org/project/gnsswire-bits/) only. `pip install
gnsswire` installs it with every other format.

## Usage

### Read a station's stream

`scan` finds every frame in a buffer, skipping noise and a frame cut off at
the end. `message_number` reads a frame's number without decoding it, and
`MESSAGES` lists the numbers with a table. Fields are the integers the
standard defines; here the station coordinates of 1005, in units of 0.1 mm:

```python
from gnsswire import rtcm3

stream = bytes.fromhex(
    "00"                                                    # noise
    "D300133ED7D30202980EDEEF34B4BD62AC0941986F33360B98"    # 1005, the example of RTCM 10403.3 4.2
    "D30013")                                               # cut off

for frame in rtcm3.scan(stream):
    if rtcm3.message_number(frame) in rtcm3.MESSAGES:
        station = rtcm3.decode(frame)

x, y, z = (v * 1e-4 for v in (station.x, station.y, station.z))
print(station.number, station.station, f"{x:.4f} {y:.4f} {z:.4f}")
# 1005 2003 1114104.5999 -4850729.7108 3975521.4643
```

### Observations (MSM)

One `Msm` class serves every MSM of every system. The masks say which
satellites and signals the message holds, one cell per pair present:

```python
msm = rtcm3.decode(rtcm3.parse(bytes.fromhex(
    "D300334357D35265C000000040080000000000002000000068C9801000C9F640335F9F8E"
    "0115C25AD0FFFFF93605805A1456F1F07D00F3B284")))

satellites = [n for n in range(1, 65) if msm.sat_mask >> (64 - n) & 1]
print(msm.number, msm.epoch, satellites)          # 1077 345600000 [1, 12]
for sat, ms, mod in zip(satellites, msm.rough_ms, msm.rough_mod):
    print(f"G{sat:02} rough range {(ms + mod / 1024) * 299_792.458:.3f} m")
# G01 rough range 21135368.289 m
# G12 rough range 22813503.415 m
```

Rows a level does not have are `None`. `fine_range`, `fine_phase`, `lock`
and `cnr` hold DF400 to DF403 at MSM1 to MSM5 and the wider DF405 to DF408
at MSM6 and MSM7, so the level (`number % 10`) says which resolution
applies. `MSM_TYPES` lists every MSM number.

### Antenna and receiver descriptors

The descriptors of 1007, 1008 and 1033 are `bytes`, kept as sent: the
standard names more than one character set for them, so turning them into
`str` is yours. Each follows its counter (`antenna_count` and so on), which
must equal its length:

```python
msg1008 = rtcm3.decode(rtcm3.parse(bytes.fromhex(
    "D300243F07D31454524D35393830302E3030202020202053434953000A35303030313132"
    "3334353A6441")))
print(msg1008.antenna.decode("latin-1"), msg1008.antenna_serial)
# TRM59800.00     SCIS b'5000112345'
```

### IGS SSR corrections (4076)

IGS SSR is the International GNSS Service's correction format for
real-time PPP. It travels in RTCM 3 frames as message 4076, so the same
`scan` and `decode` read it. Identifiers are kept as sent; the IGS SSR
mappings are data for you, such as `IGS_SIGNALS` (signal identifier to
RINEX code):

```python
bias = rtcm3.decode(rtcm3.parse(bytes.fromhex("D30010FEC232A8C004100000043103F8558390627F2D")))
system, igm = rtcm3.IGS_SUBTYPES[bias.subtype]
print(type(bias).__name__, system, igm, rtcm3.update_interval(bias.interval), "s")
# IgsCodeBias GPS IGM05 5 s
for sat in bias.satellites:
    for b in sat.biases:
        print(f"G{sat.satellite:02} C{rtcm3.IGS_SIGNALS[system][b.signal]} {b.bias * 0.01:+.2f} m")
# G03 C1C -1.23 m
# G03 C2W +4.56 m
```

### Write a message

Messages are frozen dataclasses; `encode` frames one, CRC included:

```python
from dataclasses import replace

moved = rtcm3.encode(replace(station, station=2004))
print(moved.hex().upper())
# D300133ED7D40202980EDEEF34B4BD62AC0941986F33E3C876
```

### Data after a table

RTCM 3 allows fill bits after a message and asks decoders to skip data a
later version appends, so `decode` keeps it in the message's `extension`
and `encode` writes it back. `strict=True` refuses anything but zero fill:

```python
longer = rtcm3.encode_frame(rtcm3.parse(stream, 1).payload + b"\x12\x34")
message = rtcm3.decode(rtcm3.parse(longer))
print(message.extension.bits, hex(message.extension.value), rtcm3.encode(message) == longer)
# 16 0x1234 True
try:
    rtcm3.decode(rtcm3.parse(longer), strict=True)
except rtcm3.FieldError as exc:
    print(exc)                            # Msg1005: 2 bytes left over
```

`parse(buf, offset)` answers for one offset only (`Frame`, `NeedMore` or
`Invalid`); `scan` searches. Every exception derives from `rtcm3.Error` (a
`ValueError`): `decode` raises `Unsupported` for a message number without a
table, `FieldError` (also a `gnsswire.bits.BitError`) when the message is
shorter than its table, and `NoFrame` when given anything but a `Frame`.
Any bytes-like object is accepted where bytes are.

The six reserved bits of the frame header are kept in `Frame.reserved`, so
`encode(frame)` gives the frame's bytes back; `encode(message)` writes them
as zeros. A sign-magnitude field (the GLONASS ephemeris of 1020) can carry
a negative zero; it decodes as `gnsswire.bits.NEGATIVE_ZERO`, an `int`
equal to 0 that encodes back with its sign bit.

## Messages

| Messages | Class | RTCM 10403.3 table |
|---|---|---|
| 1005 | `Msg1005` | 3.5-6 |
| 1006 | `Msg1006` | 3.5-7 |
| 1007 | `Msg1007` | 3.5-8 |
| 1008 | `Msg1008` | 3.5-9 |
| 1033 | `Msg1033` | 3.5-36 |
| 1230 | `Msg1230` | 3.5-109 |
| 1019 | `Msg1019` | 3.5-21 |
| 1020 | `Msg1020` | 3.5-22 |
| 1042 | `Msg1042` | 3.5-113 |
| 1044 | `Msg1044` | 3.5-112 |
| 1045, 1046 | `Msg1045`, `Msg1046` | 3.5-110, 3.5-111 |
| 1071 to 1077 (GPS), 1081 to 1087 (GLONASS), 1091 to 1097 (Galileo), 1101 to 1107 (SBAS), 1111 to 1117 (QZSS), 1121 to 1127 (BeiDou): MSM1 to MSM7 | `Msm` | 3.5-78 to 3.5-88 |

Fields are the raw DF integers; scale them with the resolutions of Table
3.4-1 or the system's interface document. The descriptor counters' range
of 0 to 31 is not enforced, as no range is; anything that fits a field's
bits round-trips.

### IGS SSR

Each 4076 message has the IGM/IM version (`version`) and the sub-type
(`subtype`, read from a payload by `igs_subtype`), which picks the table.
As with MSM, one class serves every system:

| Sub-types (GPS, GLONASS, Galileo, QZSS, BDS, SBAS) | Message | Class | IGS SSR tables |
|---|---|---|---|
| 21, 41, 61, 81, 101, 121 | IGM01 orbit correction | `IgsOrbit` (`IgsOrbitSat`) | 8, 9 |
| 22, 42, 62, 82, 102, 122 | IGM02 clock correction | `IgsClock` (`IgsClockSat`) | 10, 11 |
| 23, 43, 63, 83, 103, 123 | IGM03 combined orbit and clock | `IgsCombined` (`IgsCombinedSat`) | 12, 13 |
| 24, 44, 64, 84, 104, 124 | IGM04 high rate clock | `IgsHighRateClock` (`IgsHighRateClockSat`) | 14, 15 |
| 25, 45, 65, 85, 105, 125 | IGM05 code bias | `IgsCodeBias` (`IgsCodeBiasSat`, `IgsCodeBiasSignal`) | 16 to 18 |
| 26, 46, 66, 86, 106, 126 | IGM06 phase bias | `IgsPhaseBias` (`IgsPhaseBiasSat`, `IgsPhaseBiasSignal`) | 19 to 21 |
| 27, 47, 67, 87, 107, 127 | IGM07 URA | `IgsUra` (`IgsUraSat`) | 22, 23 |
| 201 | IM201 ionosphere VTEC spherical harmonics | `IgsVtec` (`IgsVtecLayer`) | 24 to 27 |

Reserved sub-types (NavIC's 141 to 160 among them) raise `Unsupported`.
`MESSAGES` does not hold 4076, which has a table per sub-type
(`IGS_MESSAGES`, `IGS_SUBTYPES`, `IGS_SYSTEMS`, `IGM_TYPES`). Fields are
the IDF integers of IGS SSR v1.00 Table 7, unscaled; counts must agree with
the tuples after them. `IGS_SATELLITES`, `IGS_SIGNALS` and
`IGS_UPDATE_INTERVALS` are Table 7's mappings. No correction is applied.

## Documentation

What gnsswire-rtcm3 does not decode, what its tests rest on and the readings
it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-rtcm3) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request messages in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT. Notices for the third-party test data in the sdist are in
`tests/THIRD_PARTY_NOTICES.md`.
