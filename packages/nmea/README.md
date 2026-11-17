# gnsswire-nmea

NMEA 0183 sentences for Python

[![tests](https://github.com/tracenav/gnsswire/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/tracenav/gnsswire/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/gnsswire-nmea)](https://pypi.org/project/gnsswire-nmea/)

gnsswire-nmea reads and writes NMEA 0183, the text sentences GNSS receivers
print their position and time in. It gives you:

- sentence framing and checksums, with a scanner that skips everything
  that is not a sentence;
- GGA (position fix) and ZDA (date and time) from any talker;
- every field as the string on the wire, so a sentence encodes back to its
  own bytes.

It is part of [gnsswire](https://pypi.org/project/gnsswire/), codecs for
GNSS wire formats.

## Installation

```sh
$ pip install gnsswire-nmea
```

gnsswire-nmea requires Python 3.11+ and has no dependencies. `pip install
gnsswire` installs it with every other format.

## Usage

### Read sentences from a stream

`scan` finds every sentence in a buffer, skipping noise and a sentence cut
off at the end; `decode` gives its fields:

```python
from gnsswire import nmea

stream = (b"noise$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B\r\n"
          b"$GPZDA,082710.00,16,09,2002,00,00*64\r\n$GPGGA,0927")

for frame in nmea.scan(stream):
    message = nmea.decode(frame)
    print(type(message).__name__, message.talker)       # Gga GP, then Zda GP

gga = nmea.decode(next(nmea.scan(stream)))
print(gga.lat, gga.ns, gga.lon, gga.ew, gga.quality)    # 4717.11399 N 00833.91590 E 1
print(repr(gga.diff_age))                               # '': null fields are empty strings
```

Fields are the strings on the wire; parsing them into numbers is yours.

### Change a field and write the sentence back

Messages are frozen dataclasses. `encode` writes a message as a sentence,
checksum included:

```python
from dataclasses import replace

zda = nmea.decode(nmea.parse(b"$GPZDA,082710.00,16,09,2002,00,00*64\r\n"))
print(nmea.encode(replace(zda, talker="GN")))   # b'$GNZDA,082710.00,16,09,2002,00,00*7A\r\n'
```

### Lenient by default, strict on request

Receivers differ in checksum case, line endings and, with the NMEA version
they are set to, the number of fields. By default `parse` and `scan` accept
lowercase checksum digits and a bare LF ending, and `decode` reads missing
trailing fields as `None` (absent, unlike a null field's `""`) and keeps
extra ones in `extra`. A frame keeps its checksum case (`lower_hex`) and
line ending (`ending`), so `encode(frame)` gives its bytes back;
`encode(message)` writes the canonical form, uppercase digits and CR LF.
`strict=True` on `parse`, `scan` and `decode` accepts the canonical form
only:

```python
frame = nmea.parse(b"$GPZDA,082710.00,16,09,2002*64\n")     # two fields short, LF only
zda = nmea.decode(frame)
print(zda.year, zda.ltzh, zda.ltzn)                         # 2002 None None
print(nmea.encode(frame))                                   # b'$GPZDA,082710.00,16,09,2002*64\n'
print(nmea.encode(zda))                                     # b'$GPZDA,082710.00,16,09,2002*64\r\n'

try:
    nmea.decode(frame, strict=True)
except nmea.FieldError as exc:
    print(exc)                          # ZDA: 4 data fields, section 2.7.21.1 has 6
```

`parse(buf, offset)` answers for one offset only (`Frame`, `NeedMore` or
`Invalid`); `scan` searches. Both take any bytes-like object.
`encode_frame(payload, lower_hex=..., ending=...)` frames a payload either
way. Every exception derives from `nmea.Error` (a `ValueError`): `decode`
raises `Unsupported` for proprietary sentences and sentences without a
table, `FieldError` for a sentence that does not fit its table, and
`NoFrame` when given anything but a `Frame`.

## Sentences

| Sentence | Class | u-blox F9 HPG 1.51 Interface Description |
|---|---|---|
| GGA, any talker | `Gga` | section 2.7.5.1 |
| ZDA, any talker | `Zda` | section 2.7.21.1 |

## Documentation

What gnsswire-nmea does not decode, what its tests rest on and the readings
it takes where its specification is ambiguous are under
[Limitations](https://github.com/tracenav/gnsswire#gnsswire-nmea) in the
[repository README](https://github.com/tracenav/gnsswire#readme), with the
interface every gnsswire format shares and the version policy. Release
notes are in [RELEASES.md](https://github.com/tracenav/gnsswire/blob/main/RELEASES.md).

## Contribute

Report bugs and request sentences in the
[issue tracker](https://github.com/tracenav/gnsswire/issues).

## Licence

MIT. Notices for the third-party test data in the sdist are in
`tests/THIRD_PARTY_NOTICES.md`.
