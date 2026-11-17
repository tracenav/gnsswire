# gnsswire-skytraq

SkyTraq binary messages for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-skytraq)](https://pypi.org/project/gnsswire-skytraq/)

gnsswire-skytraq reads and writes the binary protocol of SkyTraq GNSS
receivers. It gives you SkyTraq framing, with a scanner that resynchronises
through garbage, and these messages:

- raw measurements: MEAS_TIME, RAW_MEAS and EXT_RAW_MEAS (pseudorange,
  carrier phase, Doppler);
- navigation data: the GPS, GLONASS, BeiDou and Galileo subframes the
  satellites broadcast.

Every message decodes to a frozen dataclass of the integers on the wire and
encodes back to the same bytes. It is part of
[gnsswire](https://pypi.org/project/gnsswire/), codecs for GNSS wire
formats.

## Installation

```sh
$ pip install gnsswire-skytraq
```

gnsswire-skytraq requires Python 3.11+ and has no dependencies. `pip
install gnsswire` installs it with every other format.

## Usage

### Read messages from a stream

`scan` finds every frame in a buffer, skipping noise and a frame cut off at
the end; `decode` gives its fields. Here the MEAS_TIME example of SkyTraq
AN0039:

```python
from gnsswire import skytraq

stream = bytes.fromhex(
    "00"                                          # noise
    "A0A1000ADC3D06ED0B0CBC4003E81A0D0A"          # MEAS_TIME (0xDC)
    "A0A1000A")                                   # cut off

for frame in skytraq.scan(stream):
    epoch = skytraq.decode(frame)
    print(f"{frame.msg_id:#x}", type(epoch).__name__, epoch.week, epoch.tow, epoch.period)
# 0xdc MeasTime 1773 185384000 1000
```

### Pseudoranges from EXT_RAW_MEAS

Floating-point values (pseudorange, carrier phase, Doppler) are kept as the
integers of their IEEE 754 bits, so frames round-trip exactly; `struct`
turns them into numbers:

```python
import struct

frame = skytraq.parse(bytes.fromhex(
    "A0A1004CE5010D077C06AC408003E8000002000DE0324173931894CCCCCDC199B7B10200"
    "0000C49A5000000000000700000207E02D4176B6CB28F5C28F419DD72D73000000444B10"
    "0000000000070000240D0A"))

def f8(bits): return struct.unpack(">d", bits.to_bytes(8, "big"))[0]
def f4(bits): return struct.unpack(">f", bits.to_bytes(4, "big"))[0]

for m in skytraq.decode(frame).meas:
    print(m.gnss_signal, m.svid, f"{f8(m.pseudorange):.2f} m", f"{f4(m.doppler):.2f} Hz", m.cn0)
# 0 13 20525449.30 m -1234.50 Hz 50
# 2 7 23817394.56 m 812.25 Hz 45
```

SVIDs are kept as sent. The navigation data messages (0xE0 to 0xE3, 0xE6)
keep their words whole;
[gnsswire-nav](https://pypi.org/project/gnsswire-nav/) reads them into
ephemerides.

### Write a message

Messages are frozen dataclasses; `encode` frames one, checksum included:

```python
from dataclasses import replace

print(skytraq.encode(replace(epoch, period=500)).hex().upper())
# A0A1000ADC3D06ED0B0CBC4001F4040D0A
```

`parse(buf, offset)` answers for one offset only (`Frame`, `NeedMore` or
`Invalid`); `scan` searches. `decode` picks the table by message ID, and
raises `Unsupported` for a message ID without a table or, for 0xE5 and
0xE6, a version no table describes, `FieldError` when the body does not
fit the table, and `NoFrame` when given anything but a `Frame`; all three
derive from `skytraq.Error`, a `ValueError`. `parse`, `scan` and
`encode_frame` take any bytes-like object.

## Messages

| Message | Class |
|---|---|
| MEAS_TIME (0xDC) | `MeasTime` |
| RAW_MEAS (0xDD) | `RawMeas`, `RawMeasChannel` |
| GPS SUBFRAME (0xE0) | `GpsSubframe` |
| GLONASS STRING (0xE1) | `GlonassString` |
| BEIDOU2 D1 SUBFRAME (0xE2) | `BeidouD1Subframe` |
| BEIDOU2 D2 SUBFRAME (0xE3) | `BeidouD2Subframe` |
| EXT_RAW_MEAS version 1 (0xE5) | `ExtRawMeas`, `ExtRawMeasChannel` |
| GENERAL SUBFRAME version 1 (0xE6) | `GeneralSubframe` |

Tables are those of SkyTraq application note AN0039, version 1.4.42.
Values are the integers on the wire, big-endian: SPFP and
DPFP values (pseudorange, carrier phase, Doppler) as the unsigned integers
of their IEEE 754 bits, navigation words and bitfields whole. Scaling and
subframe interpretation are the caller's.

## Documentation

What gnsswire-skytraq does not decode, what its tests rest on and the readings
it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-skytraq) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request messages in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT. Notices for the third-party test data in the sdist are in
`tests/THIRD_PARTY_NOTICES.md`.
