# gnsswire-ubx

u-blox UBX messages for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-ubx)](https://pypi.org/project/gnsswire-ubx/)

gnsswire-ubx reads and writes UBX, the binary protocol of u-blox GNSS
receivers. It gives you UBX framing, with a scanner that resynchronises
through garbage, and these messages:

- RXM-RAWX: raw measurements (pseudorange, carrier phase, Doppler);
- RXM-SFRBX: the satellites' navigation data words;
- RXM-PMP: SPARTN corrections received over L-band;
- NAV-TIMELS: leap seconds.

Every message decodes to a frozen dataclass of the integers on the wire and
encodes back to the same bytes. It is part of
[gnsswire](https://pypi.org/project/gnsswire/), codecs for GNSS wire
formats.

## Installation

```sh
$ pip install gnsswire-ubx
```

gnsswire-ubx requires Python 3.11+ and has no dependencies. `pip install
gnsswire` installs it with every other format.

## Usage

### Read messages from a stream

`scan` finds every frame in a buffer, skipping noise and a frame cut off at
the end; `decode` gives its fields:

```python
from gnsswire import ubx

stream = bytes.fromhex(
    "00B5"                                                       # noise
    "B5620126180000709914000000000212020000000000000000000000000375B5"  # NAV-TIMELS
    "B5620213100000050000020302000000C022341200005979"           # RXM-SFRBX
    "B56202131000")                                              # cut off

for frame in ubx.scan(stream):
    print(f"{frame.msg_class:#04x} {frame.msg_id:#04x}", type(ubx.decode(frame)).__name__)
# 0x01 0x26 NavTimels
# 0x02 0x13 RxmSfrbx

leap, words = (ubx.decode(frame) for frame in ubx.scan(stream))
print(leap.curr_ls, words.sv_id, [hex(w) for w in words.dwrd])   # 18 5 ['0x22c00000', '0x1234']
```

Fields keep the interface description's names in snake case. Bitfields are
kept whole as unsigned integers, and RXM-SFRBX data words as the integers
on the wire; [gnsswire-nav](https://pypi.org/project/gnsswire-nav/) reads
those words into ephemerides.

### Pseudoranges from RXM-RAWX

RXM-RAWX keeps its floating-point fields (pseudorange, carrier phase,
Doppler, receiver time of week) as the integers of their IEEE 754 bits, so
frames round-trip exactly; `struct` turns them into numbers:

```python
import struct

frame = ubx.parse(bytes.fromhex(
    "B56202155000000000000018154160091202010100001F85EB517976744100000045FAE19A41"
    "00509AC4000C0000F4FB2F04030207008FC2F528CBB67641000000732DD79D4100104B440207"
    "0000F4FB2C04030207008935"))

def f8(bits): return struct.unpack("<d", bits.to_bytes(8, "little"))[0]
def f4(bits): return struct.unpack("<f", bits.to_bytes(4, "little"))[0]

for m in ubx.decode(frame).meas:
    print(m.gnss_id, m.sv_id, f"{f8(m.pr_mes):.2f} m", f"{f4(m.do_mes):.2f} Hz", m.cno)
# 0 12 21456789.12 m -1234.50 Hz 47
# 2 7 23817394.56 m 812.25 Hz 44
```

### Write a message

Messages are frozen dataclasses; `encode` frames one, checksum included:

```python
from dataclasses import replace

print(ubx.encode(replace(leap, curr_ls=19)).hex())
# b5620126180000709914000000000213020000000000000000000000000376c4
```

`decode` picks the table by class, ID and version byte, and raises
`Unsupported` for a message or version without a table, `FieldError` when
the payload does not fit the table, and `NoFrame` when given anything but a
`Frame` (such as the `NeedMore` or `Invalid` that `parse` returns); all
three derive from `ubx.Error`, a `ValueError`. `parse`, `scan` and
`encode_frame` take any bytes-like object.

## Messages

| Message | Class | Version | Interface description |
|---|---|---|---|
| UBX-RXM-PMP (0x02 0x72) | `RxmPmpV0` | 0 | D9 PMP 1.04, section 2.13.1.1 |
| UBX-RXM-PMP (0x02 0x72) | `RxmPmp` | 1 | F9 HPG 1.51, section 3.17.3.1 |
| UBX-RXM-RAWX (0x02 0x15) | `RxmRawx`, `RxmRawxMeas` | 1 | F9 HPG 1.51, section 3.17.6.1 |
| UBX-RXM-SFRBX (0x02 0x13) | `RxmSfrbx` | 2 | F9 HPG 1.51, section 3.17.9.1 |
| UBX-NAV-TIMELS (0x01 0x26) | `NavTimels` | 0 | F9 HPG 1.51, section 3.15.26.1 |

The X20 HPG 2.11 description prints the same tables.

## Documentation

What gnsswire-ubx does not decode, what its tests rest on and the readings
it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-ubx) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request messages in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT.
