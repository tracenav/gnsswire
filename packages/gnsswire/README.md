# gnsswire

Codecs for GNSS wire formats

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire)](https://pypi.org/project/gnsswire/)

gnsswire reads and writes the bytes that GNSS receivers, reference stations
and correction services send, for logging a receiver, building a correction
pipeline or looking inside a stream. Every message decodes to a frozen
dataclass of the integers on the wire and encodes back to exactly the same
bytes.

## Installation

Install every format with pip:

```sh
$ pip install gnsswire
```

Or only the format you need:

```sh
$ pip install gnsswire-rtcm3
```

gnsswire requires Python 3.11+ and has no third-party dependencies.

## Formats

Each format is a distribution of its own, imported from the `gnsswire`
namespace; its page describes it and lists its messages.

| Format | Import | Covers |
|---|---|---|
| [NMEA 0183](https://pypi.org/project/gnsswire-nmea/) | `gnsswire.nmea` | GGA and ZDA sentences |
| [UBX](https://pypi.org/project/gnsswire-ubx/) | `gnsswire.ubx` | u-blox raw measurements, navigation words, L-band corrections, leap seconds |
| [RTCM 3](https://pypi.org/project/gnsswire-rtcm3/) | `gnsswire.rtcm3` | MSM observations, ephemerides, station data, IGS SSR corrections |
| [SPARTN](https://pypi.org/project/gnsswire-spartn/) | `gnsswire.spartn` | SPARTN v2 orbit, clock, bias and atmosphere corrections |
| [SkyTraq](https://pypi.org/project/gnsswire-skytraq/) | `gnsswire.skytraq` | SkyTraq raw measurements and navigation data |
| [RINEX](https://pypi.org/project/gnsswire-rinex/) | `gnsswire.rinex` | RINEX observation and navigation files |
| [ANTEX](https://pypi.org/project/gnsswire-antex/) | `gnsswire.antex` | ANTEX 1.4 antenna phase centre offsets and variations |
| [Navigation messages](https://pypi.org/project/gnsswire-nav/) | `gnsswire.nav` | GPS, Galileo, BeiDou and GLONASS broadcast messages, assembled into ephemerides |
| [Bits](https://pypi.org/project/gnsswire-bits/) | `gnsswire.bits` | the bit reader, writer, CRCs and field tables the others are built on |

## Usage

### Every format works the same way

Each binary or sentence format has the same four functions (RINEX and ANTEX
files are read and written whole, with `read` and `write`):

```text
parse(buf, offset) -> Frame | NeedMore | Invalid   # is there a frame here? never searches
scan(buf, offset)  -> Iterator[Frame]              # every frame, skipping bad bytes
decode(frame)      -> message                      # frozen dataclass of the fields
encode(message)    -> bytes
```

So the loop that reads one format reads them all:

```python
from dataclasses import replace
from gnsswire import nmea, rtcm3

streams = {
    rtcm3: b"\x00" + bytes.fromhex("D300133ED7D30202980EDEEF34B4BD62AC0941986F33360B98"),
    nmea: b"noise$GPZDA,082710.00,16,09,2002,00,00*64\r\n$GPZDA,0827",   # the last one is cut off
}
for codec, stream in streams.items():
    for frame in codec.scan(stream):
        message = codec.decode(frame)
        print(type(message).__name__)                          # Msg1005, then Zda
        assert codec.encode(message) == stream[frame.offset:frame.offset + frame.length]

# Messages are frozen: change a field with replace(), and encode() recomputes the checksum.
print(nmea.encode(replace(message, talker="GN")))   # b'$GNZDA,082710.00,16,09,2002,00,00*7A\r\n'
```

### A reference station's position (RTCM 3)

Fields are the integers the specification defines; scaling is yours. Here
the station coordinates of message 1005, in units of 0.1 mm:

```python
from gnsswire import rtcm3

frame = rtcm3.parse(bytes.fromhex("D300133ED7D30202980EDEEF34B4BD62AC0941986F33360B98"))
station = rtcm3.decode(frame)
x, y, z = (v * 1e-4 for v in (station.x, station.y, station.z))
print(station.station, f"{x:.4f} {y:.4f} {z:.4f}")   # 2003 1114104.5999 -4850729.7108 3975521.4643
```

[More on RTCM 3](https://pypi.org/project/gnsswire-rtcm3/): MSM
observations, ephemerides, IGS SSR.

### Corrections from a SPARTN stream

A SPARTN message holds the frame's transport fields, with the message
table in `body`; here the areas a correction service covers:

```python
from gnsswire import spartn

frame = spartn.parse(bytes.fromhex("730404A1083ADE68A8100388002FA1F41C29802A1F5E"))
message = spartn.decode(frame)
print(type(message.body).__name__, message.description.time_tag,
      [area.area_id for area in message.body.areas])        # Gad 123456789 [1]
```

[More on SPARTN](https://pypi.org/project/gnsswire-spartn/): orbit, clock,
bias and atmosphere corrections, and decryption for encrypted services.

### Pseudoranges from a u-blox receiver (UBX)

RXM-RAWX keeps its floating-point fields as the integers of their IEEE 754
bits, so frames round-trip exactly; `struct` turns them into numbers:

```python
import struct
from gnsswire import ubx

frame = ubx.parse(bytes.fromhex(
    "B56202155000000000000018154160091202010100001F85EB517976744100000045FAE19A41"
    "00509AC4000C0000F4FB2F04030207008FC2F528CBB67641000000732DD79D4100104B440207"
    "0000F4FB2C04030207008935"))
for m in ubx.decode(frame).meas:
    pseudorange = struct.unpack("<d", m.pr_mes.to_bytes(8, "little"))[0]
    print(m.gnss_id, m.sv_id, f"{pseudorange:.2f} m")       # 0 12 21456789.12 m, 2 7 ...
```

[More on UBX](https://pypi.org/project/gnsswire-ubx/), and on reading the
navigation words of RXM-SFRBX into ephemerides with
[gnsswire-nav](https://pypi.org/project/gnsswire-nav/).

## Documentation

Each format's page, linked above, has its messages and examples. The shared interface, errors and version policy are in the
[repository README](https://github.com/tracenav/gnsswire#readme), and the
release notes in
[RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request formats in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT.
