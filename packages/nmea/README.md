# gnsswire-nmea

NMEA 0183 sentence framing and GGA/ZDA, fields kept as strings.
Standard library only.

Import as `gnsswire.nmea`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme) for the
interface every codec shares and for the version policy. Written from the
freely available u-blox F9 HPG 1.51 Interface Description; NMEA 0183 itself
is sold by the NMEA and was not used.

```python
from dataclasses import replace
from gnsswire import nmea

stream = (b"garbage$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B\r\n"
          b"$GPZDA,082710.00,16,09,2002,00,00*64\r\n")

gga, zda = (nmea.decode(frame) for frame in nmea.scan(stream))
assert (gga.talker, gga.lat, gga.ns, gga.quality) == ("GP", "4717.11399", "N", "1")
assert gga.diff_age == ""                      # null fields stay empty strings
assert (zda.day, zda.month, zda.year) == ("16", "09", "2002")

# Encoding gives back the sentence's bytes, CR LF included.
assert nmea.encode(gga) == stream[7:stream.index(b"\n") + 1]
assert nmea.encode(replace(zda, talker="GN")) == b"$GNZDA,082710.00,16,09,2002,00,00*7A\r\n"
```

`parse(buf, offset)` answers for one offset only (`Frame`, `NeedMore` or
`Invalid`); `scan` skips what is not a sentence. Both take any bytes-like
object. Every exception derives from `nmea.Error` (a `ValueError`): `decode`
raises `Unsupported` for proprietary sentences (`PUBX` and the like) and
sentences without a table, `FieldError` for a sentence that does not fit
its table, and `NoFrame` when given anything but a `Frame`.

Lenient by default, strict on request. The document says the checksum is
"two characters ... in hex" without fixing their case, and that a sentence
ends "always \r\n"; field counts vary with the NMEA version a receiver is
set to (in NMEA 2.1 some sentences have "one field less", later versions
append fields). So by default `parse` and `scan` accept lowercase checksum
digits and a bare LF ending, and `decode` reads a sentence with missing
trailing fields as `None` (absent, unlike a null field's `""`) and keeps
fields beyond the table in `extra`. A frame keeps its checksum case
(`lower_hex`) and line ending (`ending`), and a message its absent and
extra fields, so both round-trip; `encode(message)` writes uppercase digits
and CR LF. `encode_frame(payload, lower_hex=..., ending=...)` frames a
payload either way (`CRLF`, and `ENDINGS`, the endings accepted).
`parse(..., strict=True)`, `scan(..., strict=True)` and
`decode(..., strict=True)` accept only what the document prints.

```python
from gnsswire import nmea

frame = nmea.parse(b"$GPZDA,082710.00,16,09,2002*64\n")
assert frame.ending == b"\n" and nmea.encode(frame) == b"$GPZDA,082710.00,16,09,2002*64\n"
zda = nmea.decode(frame)
assert (zda.year, zda.ltzh, zda.ltzn, zda.extra) == ("2002", None, None, ())
assert nmea.encode(zda) == b"$GPZDA,082710.00,16,09,2002*64\r\n"
assert isinstance(nmea.parse(b"$GPZDA,082710.00,16,09,2002*64\n", strict=True), nmea.Invalid)
try:
    nmea.decode(frame, strict=True)
except nmea.FieldError as exc:
    print(exc)          # ZDA: 4 data fields, section 2.7.21.1 has 6
```

Sentences: GGA and ZDA from any two-letter talker, each the payload table of
the u-blox F9 HPG 1.51 Interface Description (UBXDOC-963802114-13124 R01, sections
2.7.5.1 and 2.7.21.1), which stands in for NMEA 0183 (sold by the NMEA, not freely available). Every field
is the string on the wire, null fields are `""`; parsing numbers is the
caller's.

## Limitations

- Only GGA and ZDA are decoded. Other sentences (RMC, GNS, GSA, GSV and
  the rest) and proprietary ones (`PUBX`, or any address starting with
  `P`) raise `Unsupported`.
- A talker is any two uppercase letters not starting with `P`; written
  from the u-blox description, this rule is not checked against NMEA 0183.
- TAG blocks (`\s:1*78\` before the `$`) and `!`-led encapsulation
  sentences (AIS and similar) are not framed: `scan` yields the sentence
  after a TAG block (the block ends at `frame.offset`) and skips `!`
  sentences.
- A bare CR is not a line ending. A sentence longer than `MAX_LENGTH`
  (4096 bytes, a bound for resynchronising, not the standard's 82
  characters) is `Invalid`.
- GGA and ZDA are tested on a receiver's log (from the GPSD project); the
  lenient forms (lowercase checksum digits, LF endings, missing or extra
  fields) only on sentences built for the tests.

## Licence

Released under the MIT licence. The sdist (not the wheel) also holds
`tests/data/gpsd-zed-f9p.nmea`, sentences from the GPSD project's regression
logs, under the GPSD project's BSD 2-clause terms; its notice is in
`tests/THIRD_PARTY_NOTICES.md`.
