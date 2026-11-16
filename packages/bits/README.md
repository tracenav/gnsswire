# gnsswire-bits

MSB-first bit reader and writer, the CRCs GNSS wire formats use, and
declarative field tables. Standard library only.

Import as `gnsswire.bits`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme).

## Bits

```python
from gnsswire.bits import BitReader, BitWriter

w = BitWriter()
w.uint(1005, 12)    # unsigned, 0 to 64 bits
w.sint(-3, 38)      # two's complement, 1 to 64 bits
w.smag(-3, 22)      # sign-magnitude, 2 to 64 bits (RTCM intS)
w.octets(b"ADVNULLANTENNA")
data = w.to_bytes()  # last byte zero-filled

r = BitReader(data)
assert (r.uint(12), r.sint(38), r.smag(22)) == (1005, -3, -3)
```

Reads past the end raise `Truncated`, values that do not fit raise `BitError`
(both `ValueError`s), and a failed read leaves the position where it was.
`BitReader` takes any bytes-like object. `BitReader.mask(n)` and
`BitWriter.mask(value, n)` read and write an unsigned field of any width,
wider than 64 bits included; `BitReader.tail()` reads every bit left as
`(count, value)`, which `BitWriter.tail(value, count)` writes back.

A sign-magnitude negative zero (sign bit set, magnitude zero) reads as
`NEGATIVE_ZERO`, an `int` equal to 0 that `BitWriter.smag` writes back with
its sign bit, so the bits round-trip. RTCM 10403.3 Table 3.3-1 says the
value is not used, but its GLONASS fields follow the GLONASS ICD, which
does not exclude it, so a received frame may hold it.

```python
from gnsswire.bits import NEGATIVE_ZERO, BitReader, BitWriter

w = BitWriter()
w.smag(NEGATIVE_ZERO, 5)
assert w.to_bytes() == b"\x80"
value = BitReader(b"\x80").smag(5)
assert value == 0 and value is NEGATIVE_ZERO
```

## CRCs

`Crc` takes the CRC catalogue's parameters and is called on bytes:
`CRC24Q(frame[:-3])`. Provided: `CRC24Q` (RTCM 3), `CRC4_SPARTN` (SPARTN
TF006), and both readings of SPARTN's TF018 CRCs, which the spec leaves
ambiguous: `CRC8_SMBUS`, `CRC16_XMODEM`, `CRC16_IBM_3740`, `CRC24_LTE_A`,
`CRC24_OPENPGP`, `CRC32_BZIP2`, `CRC32_ISO_HDLC` (see `_crc.py`).
`CrcSlices(crc, buf)` gives the CRC of any slice of one buffer in constant
time, for resynchronising scans that test many candidate frames.

## Field tables

A message is a frozen dataclass whose annotations are the spec's table:

```python
from dataclasses import dataclass
from typing import Annotated
from gnsswire.bits import F, Group, S, U, pack, popcount, unpack

@dataclass(frozen=True, slots=True)
class Sat:
    rough: Annotated[int, U(8)]
    fine: Annotated[int | None, S(15, when=F.flags & 1)]   # present if flag set

@dataclass(frozen=True, slots=True)
class Example:
    number: Annotated[int, U(12, "DF002")]
    flags: Annotated[int, U(2)]
    mask: Annotated[int, U(8)]
    sats: Annotated[tuple[Sat, ...], Group(Sat, count=popcount(F.mask))]

msg = Example(1, 1, 0b101, (Sat(3, -1), Sat(4, 2)))
assert unpack(Example, pack(msg)) == msg
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
`.map({...})`. `layout(cls)` returns the compiled
rows for inspection, with `fixed_bits` set when the length does not vary.

## Limitations

- Bits are read and written most significant first. Byte-oriented
  layouts, such as UBX's little-endian and SkyTraq's big-endian fields,
  are not described with these tables: `gnsswire.ubx` and
  `gnsswire.skytraq` read their own.
- A value is checked against its field's width only. A narrower range a
  specification gives (such as 0 to 31 for an 8-bit RTCM counter) is the
  caller's to check.
- SPARTN's message CRCs: both readings are provided (above);
  `gnsswire-spartn` uses the unreflected one of each.
