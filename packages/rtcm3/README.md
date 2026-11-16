# gnsswire-rtcm3

RTCM 10403.x framing, ephemeris, MSM and station messages, and the IGS SSR
messages (4076), as integer fields. Depends on `gnsswire-bits` only.

Import as `gnsswire.rtcm3`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme) for the
interface every codec shares and for the version policy. Written from RTCM
10403.3, which RTCM publishes for sale; it is not freely available. The IGS
SSR messages are written from the IGS SSR format version 1.00, which is.

```python
from gnsswire import rtcm3

# The 1005 example of RTCM 10403.3 section 4.2, behind a garbage byte.
example = bytes.fromhex("D3 00 13 3E D7 D3 02 02 98 0E DE EF 34 B4 BD 62"
                        "AC 09 41 98 6F 33 36 0B 98")
stream = b"\x00" + example

for frame in rtcm3.scan(stream):
    if rtcm3.message_number(frame) in rtcm3.MESSAGES:
        message = rtcm3.decode(frame)          # here a Msg1005
        assert rtcm3.encode(message) == stream[frame.offset:frame.offset + frame.length]

assert (message.station, message.gps, message.x) == (2003, 1, 11141045999)   # x in 0.0001 m
assert isinstance(rtcm3.parse(stream, 0), rtcm3.Invalid)    # parse never searches
assert isinstance(rtcm3.parse(example[:10], 0), rtcm3.NeedMore)
```

Every exception derives from `rtcm3.Error` (a `ValueError`). `decode`
raises `Unsupported` for a message number without a table, `FieldError`
(also a `gnsswire.bits.BitError`) when the message is shorter than its
table, and `NoFrame` when given anything but a `Frame`, such as the
`NeedMore` or `Invalid` that `parse` returns. `message_number(frame)` gives
a frame's DF002 without decoding it (`None` if the message is shorter than
12 bits) and also raises `NoFrame`. Any bytes-like object (`bytes`,
`bytearray`, `memoryview`) is accepted where bytes are.

Data after a message's table is kept, not refused. The standard asks
receivers to accept it: "a message may contain fill bits ... to the next
byte boundary" (note to Table 3.2-1), and a decoder "shall skip" data
appended by a later version (sections 3.5.16.3.4 and 3.5.17). Every
message class ends with an `extension` field: `None` when what follows the
table is fill bits of zero, otherwise a `gnsswire.bits.Extension` holding
the leftover bits (`bits` of them, fill included, MSB first as `value`;
`whole_bytes` counts the bytes after the table's last byte), which `encode`
writes back so the frame round-trips. `decode(frame, strict=True)` refuses
anything but zero fill instead.

```python
from gnsswire import rtcm3

example = bytes.fromhex("D3 00 13 3E D7 D3 02 02 98 0E DE EF 34 B4 BD 62"
                        "AC 09 41 98 6F 33 36 0B 98")
longer = rtcm3.encode_frame(rtcm3.parse(example).payload + b"\x12\x34")
message = rtcm3.decode(rtcm3.parse(longer))
assert (message.extension.bits, message.extension.value) == (16, 0x1234)
assert rtcm3.encode(message) == longer
try:
    rtcm3.decode(rtcm3.parse(longer), strict=True)
except rtcm3.FieldError as exc:
    print(exc)                            # Msg1005: 2 bytes left over
```

The six reserved bits of the frame header are "not defined" but a receiver
"should ignore these bits and not assume they will always be set to zero"
(section 4.1). `parse` accepts any value and `Frame.reserved` keeps it, so
`encode(frame)` gives the frame's bytes back. They are not part of the
message, so `encode(message)` writes zeros, as the standard asks of a
transmitter.

A sign-magnitude field (the GLONASS ephemeris fields of 1020, Table 3.5-22)
can carry a negative zero; it decodes as `gnsswire.bits.NEGATIVE_ZERO`, an
`int` equal to 0 that encodes back with its sign bit.

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

Fields are the raw DF integers; scale them with the resolutions of Table 3.4-1
or the system's interface document. One `Msm` class serves every MSM
(`MSM_TYPES` lists their message numbers): rows a
level does not have are `None`, and `fine_range`, `fine_phase`, `lock` and
`cnr` hold DF400 to DF403 at MSM1 to MSM5 and the wider DF405 to DF408 at
MSM6 and MSM7, so the level (`number % 10`) says which resolution applies.

```python
from dataclasses import replace
from gnsswire import rtcm3

msm7 = rtcm3.Msm(number=1077, station=0, epoch=345_600_000, glonass_day=None,
                 glonass_epoch=None, multiple=0, iods=0, reserved=0, clock_steering=0,
                 external_clock=0, smoothing=0, smoothing_interval=0,
                 sat_mask=1 << 63, sig_mask=1 << 30, cell_mask=1,
                 rough_ms=(70,), extended_info=(0,), rough_mod=(512,), rough_rate=(-312,),
                 fine_range=(-12_345,), fine_phase=(1_234_567,), lock=(704,),
                 half_cycle=(0,), cnr=(720,), fine_rate=(-4_321,))
frame = rtcm3.parse(rtcm3.encode(msm7))
assert rtcm3.decode(frame) == msm7

# The same satellite as MSM4: no rates or extended information, narrower fields.
msm4 = replace(msm7, number=1074, extended_info=None, rough_rate=None, fine_rate=None,
               fine_range=(-386,), fine_phase=(38_580,), lock=(15,), cnr=(45,))
assert len(rtcm3.encode(msm4)) < len(rtcm3.encode(msm7))
assert rtcm3.decode(rtcm3.parse(rtcm3.encode(msm4))) == msm4
```

The antenna and receiver descriptors of 1007, 1008 and 1033 are `bytes`,
one byte per character, each after its counter (`antenna_count` and so on),
which must equal its length. They are kept as sent and never decoded to
text: the standard calls them ISO 8859-1 characters in one place and ASCII
or "alphanumeric" in others (`_station.py`), so turning them into `str` is
the caller's choice. The counters' range of 0 to 31 (Table 3.4-1) is not
enforced, as no range is; anything that fits their eight bits round-trips.

```python
from gnsswire import rtcm3

antenna, serial = b"TRM59800.00     SCIS", b"5000112345"
msg1008 = rtcm3.Msg1008(number=1008, station=2003, antenna_count=len(antenna),
                        antenna=antenna, antenna_setup=0,
                        antenna_serial_count=len(serial), antenna_serial=serial)
frame = rtcm3.parse(rtcm3.encode(msg1008))
assert len(frame.payload) == (48 + 8 * (len(antenna) + len(serial))) // 8   # Table 3.5-9
message = rtcm3.decode(frame)
assert message == msg1008 and message.antenna.decode("latin-1") == "TRM59800.00     SCIS"

# 1007 is 1008 without the serial number (Tables 3.5-8 and 3.5-9).
msg1007 = rtcm3.Msg1007(1007, message.station, message.antenna_count, message.antenna,
                        message.antenna_setup)
assert rtcm3.decode(rtcm3.parse(rtcm3.encode(msg1007))) == msg1007
```

## IGS SSR (message 4076)

The IGS State Space Representation format, version 1.00 (IGS, 2020-10-05;
free from igs.org), is the proprietary RTCM message 4076 of the
International GNSS Service: orbit, clock, code and phase bias, URA and
ionosphere corrections for real-time PPP. It is here, in `gnsswire-rtcm3`,
rather than in a distribution of its own because it travels in ordinary
RTCM 3 frames and is told apart only by its message number (IGS SSR section
2: "uses the basic structure of RTCM3"). A stream mixes it with standard
messages (1019, 1020, 1033 ...), so one `scan` and one `decode` should
handle both; a separate codec would have to import this one, which the
workspace rules do not allow (codecs import only `gnsswire.bits`), or
duplicate its framing.

After DF002 = 4076 (`IGS_SSR`) each message has the IGM/IM version
(IDF001) and the sub-type (IDF002, read from a payload by `igs_subtype`),
which picks the table (`IGS_MESSAGES`, `IGS_SUBTYPES`, IGS SSR Table 5;
`IGS_SYSTEMS` gives each system's first sub-type and `IGM_TYPES` the seven
message types). As with MSM, one class serves every system:

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
`MESSAGES` lists message numbers with one table each, so it does not hold
4076; `decode` and `encode` take both. Fields are the IDF integers of IGS
SSR Table 7, unscaled; each row's resolution is noted in `_igs.py`. The
header fields are `version`, `subtype`, `epoch` (IDF003, seconds of the
week), `interval` (IDF004), `multiple` (IDF005, the multiple message
indicator), `iod_ssr` (IDF007), `provider` (IDF008) and `solution`
(IDF009). Counts (IDF010, IDF023, IDF035, IDF037, IDF038) are fields as
sent and must agree with the tuples after them. Identifiers are kept as
sent; Table 7's mappings are data for the caller: `IGS_SATELLITES` (IDF011
to the system's satellite number, QZSS 1 to 193 and so on),
`IGS_SIGNALS` (IDF024 to the RINEX band and attribute, such as `"1C"`), and
`update_interval` / `IGS_UPDATE_INTERVALS` (IDF004 to seconds). Nothing
else is interpreted: no correction is applied.

```python
from gnsswire import rtcm3

sat = rtcm3.IgsCodeBiasSat(satellite=3, bias_count=2, biases=(
    rtcm3.IgsCodeBiasSignal(signal=0, bias=-123),      # IDF025 in 0.01 m
    rtcm3.IgsCodeBiasSignal(signal=11, bias=456)))
message = rtcm3.IgsCodeBias(number=4076, version=1, subtype=25, epoch=345_600, interval=2,
                            multiple=0, iod_ssr=1, provider=0, solution=0,
                            satellite_count=1, satellites=(sat,))
frame = rtcm3.parse(rtcm3.encode(message))
assert rtcm3.decode(frame) == message
system, igm = rtcm3.IGS_SUBTYPES[message.subtype]                   # ("GPS", "IGM05")
codes = ["C" + rtcm3.IGS_SIGNALS[system][b.signal] for b in sat.biases]
assert codes == ["C1C", "C2W"] and rtcm3.update_interval(message.interval) == 5
```

## Limitations

- Not decoded (`decode` raises `Unsupported`): the standard RTCM SSR
  messages, 1057 to 1068 and 1240 to 1270 (IGS SSR, 4076, is decoded);
  1041 (NavIC) and 1043 (SBAS) ephemerides and NavIC MSM (1131 to 1137),
  which RTCM 10403.3 does not define; every other message number not in
  the tables above, such as 1001 to 1004 and 1009 to 1012; and the IGS SSR
  sub-types Table 5 reserves (NavIC's 141 to 160, and 202 to 254, among
  them).
- Tested on receiver data: 1005, 1019, 1020, 1033 and the MSM7 of GPS,
  GLONASS, QZSS and BeiDou, from public reference station captures. Every
  other message (1006 to 1008, 1230, 1042, 1044 to 1046, MSM1 to MSM6, the
  MSM of Galileo and SBAS, and IGS SSR) is tested only on frames built
  from the tables and frames made by RTKLIB's encoder, and compared with
  pyrtcm; data after a table only on frames built for the tests.
- rtcm-rs 0.11.0 (through rtcm-json) was run, outside the tests, on every
  committed frame and every frame the tests build. It agrees on every
  integer field of the messages both decode. Where it differs, RTCM 10403.3
  supports the codec: the bias list of 1230 (Table 3.5-109, DF422), MSM
  cells of reserved signal IDs (DF395), MSM with empty masks, and
  descriptors holding control characters or bytes above 0x7F.
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

## Licence

Released under the MIT licence. The sdist (not the wheel) also holds test
data: `tests/data/public.hex`, frames copied from RTKLIB's test data;
`tests/data/rtklib.hex`, `tests/data/rtklib-msm.hex` and
`tests/data/rtklib-station.hex`, frames made with RTKLIB's encoder;
`tests/data/rtklib-igs.hex` and `tests/data/rtklib-igs-decoded.json`, IGS
SSR frames and RTKLIB's decoding of them; and `tests/data/rtklib-antenna.hex`
and `tests/data/rtklib-antenna-decoded.json`, antenna and receiver
descriptor frames made with RTKLIB's encoder, with what it was given and
what its decoder read. All are under RTKLIB's BSD 2-clause licence, and the
first three hold IGS data; their notices and attribution are in
`tests/THIRD_PARTY_NOTICES.md`, and how they were made in
`tests/make_data/README.md`.
