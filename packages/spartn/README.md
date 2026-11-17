# gnsswire-spartn

SPARTN corrections for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-spartn)](https://pypi.org/project/gnsswire-spartn/)

gnsswire-spartn reads and writes SPARTN v2, the correction format of
satellite and IP precise positioning services. It gives you SPARTN framing,
with a scanner that resynchronises through garbage, and these messages:

- OCB: orbit, clock and bias corrections for GPS, GLONASS, Galileo, BeiDou
  and QZSS;
- HPAC: troposphere and ionosphere corrections;
- GAD: the areas the HPAC corrections cover;
- BPAC: basic-precision atmosphere corrections.

Every message decodes to a frozen dataclass of the integers on the wire and
encodes back to the same bytes. Encrypted messages decode too, once
decrypted with the service's key. It is part of
[gnsswire](https://pypi.org/project/gnsswire/), codecs for GNSS wire
formats.

## Installation

```sh
$ pip install gnsswire-spartn
```

gnsswire-spartn requires Python 3.11+ and depends on
[gnsswire-bits](https://pypi.org/project/gnsswire-bits/) only. `pip install
gnsswire` installs it with every other format.

## Usage

### Read messages from a stream

`scan` finds every frame in a buffer, skipping noise and a frame cut off at
the end. A decoded `Message` holds the frame's transport fields, with the
message table in `body`:

```python
from gnsswire import spartn

stream = bytes.fromhex(
    "00FF"                                              # noise
    "730404A1083ADE68A8100388002FA1F41C29802A1F5E"      # GAD, not encrypted
    "730404")                                           # cut off

for frame in spartn.scan(stream):
    message = spartn.decode(frame)
    area = message.body.areas[0]
    print(type(message.body).__name__, message.description.time_tag, area.area_id,
          area.latitude, area.longitude)
# Gad 123456789 1 1000 2000
```

Fields are the raw SF integers; scale them with the resolutions of SPARTN
Table 6.2.

### Write a message

Messages are frozen dataclasses; `encode` frames one, CRCs included:

```python
from dataclasses import replace

later = replace(message, description=replace(message.description, time_tag=123_456_790))
print(spartn.encode(later).hex().upper())
# 730404A1083ADE68B0100388002FA1F41C2980722257
```

### Decrypt a message

A service may encrypt its messages. An encrypted frame (`eaf` set) raises
`Encrypted` until it has been through `decrypt` with the service's key
(AES-128-CTR, section 8.15, in pure Python):

```python
key = bytes.fromhex("000102030405060708090A0B0C0D0E0F")
frame = spartn.parse(bytes.fromhex("730404EC083ADE68A810344084DC48E666F61EC3EB0E8F37"))
try:
    spartn.decode(frame)
except spartn.Encrypted as exc:
    print(exc)                     # the payload is encrypted: decrypt(frame, key) first

message = spartn.decode(spartn.decrypt(frame, key))
print(type(message.body).__name__, message.description.encryption_id,
      message.description.sequence)                    # Gad 3 17
```

A frame with the 16-bit time tag needs the full 32-bit tag for the IV:
`decrypt(frame, key, time_tag)`. `encrypt` does the reverse.

`parse(buf, offset)` answers for one offset only (`Frame`, `NeedMore` or
`Invalid`); `scan` searches. Every exception derives from `spartn.Error` (a
`ValueError`): `decode` raises `Encrypted` for a frame that has not been
through `decrypt`, `Unsupported` for a type and subtype without a table,
`FieldError` (also a `gnsswire.bits.BitError`) when the payload is shorter
than its table, and `NoFrame` when given anything but a `Frame`. Embedded
authentication data (TF017) is kept as bytes, not verified. Any bytes-like
object is accepted where bytes are.

## Messages

| Message | Class | SPARTN v2.0.3 |
|---|---|---|
| framing, TF001 to TF018 | `Frame`, `Description` | section 7, Tables 7.1 and 7.2 |
| OCB, SM 0-0 to 0-4 (GPS, GLONASS, Galileo, BeiDou, QZSS) | `Ocb` | section 6.5.1 |
| OCB header, SM 0-0 to 0-15 | `OcbHeader`, `decode_ocb_header` | Table 6.3; section 8.4 item 5 |
| HPAC, SM 1-0 to 1-4 | `Hpac` | section 6.5.2 |
| GAD, SM 2-0 | `Gad` | section 6.5.3, Tables 6.23 and 6.24 |
| BPAC, SM 3-0 | `Bpac` | section 6.5.4, Tables 6.25 to 6.28 |
| AES-128-CTR | `decrypt`, `encrypt`, `iv` | section 8.15; FIPS 197; RFC 3686 |

The phase and code bias masks are kept as sent; Table 6.2 names the signal
of each bit. v2.0.3 defines Galileo bits 3 and 4 (SF102: L8Q and L6C;
SF105: C8Q and C6C), which v2.0.2 left spare; the mask widths are
unchanged, so frames of either version decode the same.

## Documentation

What gnsswire-spartn does not decode, what its tests rest on and the readings
it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-spartn) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request messages in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT.
