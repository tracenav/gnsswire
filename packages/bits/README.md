# gnsswire-bits

Bit fields and CRCs for GNSS wire formats

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-bits)](https://pypi.org/project/gnsswire-bits/)

gnsswire-bits is the toolkit the bit-packed GNSS formats are built on. It
gives you:

- an MSB-first bit reader and writer: unsigned, two's complement and
  sign-magnitude fields of any width;
- the CRCs RTCM 3 and SPARTN use (listed below), and a constant-time CRC
  of any slice of a buffer for resynchronising scans;
- declarative field tables: a dataclass whose annotations are a
  specification's table, read and written by `unpack` and `pack`.

It is part of [gnsswire](https://pypi.org/project/gnsswire/), codecs for
GNSS wire formats, whose RTCM 3, SPARTN and navigation message codecs use
it.

## Installation

```sh
$ pip install gnsswire-bits
```

gnsswire-bits requires Python 3.11+ and has no dependencies. Every gnsswire
format that needs it installs it.

## Usage

### Read and write bit fields

```python
from gnsswire.bits import BitReader, BitWriter

w = BitWriter()
w.uint(1005, 12)    # unsigned, 0 to 64 bits
w.sint(-3, 38)      # two's complement, 1 to 64 bits
w.smag(-3, 22)      # sign-magnitude, 2 to 64 bits (RTCM intS)
data = w.to_bytes()                        # the last byte zero-filled
print(data.hex())                          # 3edfffffffff600003

r = BitReader(data)
print(r.uint(12), r.sint(38), r.smag(22))  # 1005 -3 -3
```

Reads past the end raise `Truncated`, values that do not fit raise
`BitError` (both `ValueError`s), and a failed read leaves the position
where it was. `BitReader` takes any bytes-like object. `mask` reads and
writes an unsigned field of any width, wider than 64 bits included;
`BitReader.tail()` reads every bit left as `(count, value)`, which
`BitWriter.tail(value, count)` writes back.

A sign-magnitude negative zero reads as `NEGATIVE_ZERO`, an `int` equal to
0 that `smag` writes back with its sign bit, so the bits round-trip
(GLONASS ephemeris fields can carry one):

```python
from gnsswire.bits import NEGATIVE_ZERO

value = BitReader(b"\x80").smag(5)
print(value == 0, value is NEGATIVE_ZERO)  # True True
w = BitWriter()
w.smag(value, 5)
print(w.to_bytes())                        # b'\x80'
```

### Check a CRC

`Crc` takes the CRC catalogue's parameters and is called on bytes. Here
the CRC-24Q that ends every RTCM 3 frame:

```python
from gnsswire.bits import CRC24Q

frame = bytes.fromhex("D300133ED7D30202980EDEEF34B4BD62AC0941986F33360B98")
print(CRC24Q(frame[:-3]) == int.from_bytes(frame[-3:], "big"))   # True
```

| CRC | Used for |
|---|---|
| `CRC24Q` | RTCM 3 frames; Galileo I/NAV and F/NAV pages |
| `CRC4_SPARTN` | SPARTN frame header (TF006) |
| `CRC8_SMBUS` | SPARTN message CRC type 0 (TF018) |
| `CRC16_XMODEM` | SPARTN message CRC type 1 |
| `CRC24_LTE_A` | SPARTN message CRC type 2 |
| `CRC32_BZIP2` | SPARTN message CRC type 3 |
| `CRC16_IBM_3740` | the other reading of SPARTN type 1 |
| `CRC24_OPENPGP` | the other reading of SPARTN type 2 |
| `CRC32_ISO_HDLC` | the other reading of SPARTN type 3 |

SPARTN's message CRCs can be read two ways; gnsswire-spartn uses the first
reading of each, and the other is provided for comparison. Any other CRC is
`Crc(name, width, poly, init, refin, refout, xorout, check)`, as the CRC
catalogue gives it. `CrcSlices(crc, buf)` gives the CRC of any slice of one
buffer in constant time, for resynchronising scans that test many candidate
frames.

### Describe a message as a table

A message is a frozen dataclass whose annotations are the specification's
table; `unpack` reads it and `pack` writes it:

```python
from dataclasses import dataclass
from typing import Annotated
from gnsswire.bits import F, Group, S, U, pack, popcount, unpack

@dataclass(frozen=True, slots=True)
class Sat:
    rough: Annotated[int, U(8)]
    fine: Annotated[int | None, S(15, when=F.flags & 1)]   # present if the flag is set

@dataclass(frozen=True, slots=True)
class Example:
    number: Annotated[int, U(12, "DF002")]
    flags: Annotated[int, U(2)]
    mask: Annotated[int, U(8)]
    sats: Annotated[tuple[Sat, ...], Group(Sat, count=popcount(F.mask))]   # one per set bit

data = pack(Example(1, 1, 0b101, (Sat(3, -1), Sat(4, 2))))
print(len(data), unpack(Example, data).sats)
# 9 (Sat(rough=3, fine=-1), Sat(rough=4, fine=2))
```

Kinds are `U`, `S`, `SM`, `Mask` (an unsigned bit mask of any width),
`Octets` and `Group`; each takes `count=` (the row repeats, giving a tuple)
and `when=` (the row is absent, giving `None`, when the condition is zero).
A `Rest` row, last in the outermost table, keeps what follows the table:
`None` for fewer than eight zero bits (fill), otherwise an `Extension(bits,
value)` that `pack` writes back (`whole_bytes` and `fill` split it at the
byte boundary). `unpack(cls, data, strict=True)` refuses such data. A table
class may list names in `PARAMS`, values its caller passes to `unpack` and
`pack` as keyword arguments (so none may be called `strict`). Widths,
counts and conditions are ints or expressions over earlier fields, built
from `F.name`, arithmetic and comparison operators, `popcount()` and
`.map({...})`. `layout(cls)` returns the compiled rows for inspection, with
`fixed_bits` set when the length does not vary.

## Documentation

What gnsswire-bits leaves to the caller is under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-bits) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs in the [issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT.
