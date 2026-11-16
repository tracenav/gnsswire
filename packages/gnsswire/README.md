# gnsswire

Pure-Python codecs for GNSS wire formats, written from their published
specifications (all freely available except RTCM 10403.3, which RTCM sells).
This distribution installs all of them; it has no code of its own.

```sh
pip install gnsswire
```

| Distribution | Import | Contents |
|---|---|---|
| `gnsswire-bits` | `gnsswire.bits` | MSB-first bit reader and writer, CRCs, declarative field tables |
| `gnsswire-nmea` | `gnsswire.nmea` | NMEA 0183 sentence framing, GGA, ZDA |
| `gnsswire-ubx` | `gnsswire.ubx` | UBX framing, RXM-PMP, RXM-RAWX, RXM-SFRBX, NAV-TIMELS |
| `gnsswire-rtcm3` | `gnsswire.rtcm3` | RTCM 3 framing, ephemerides, MSM1 to MSM7, 1005 to 1008, 1033, 1230; IGS SSR (4076) |
| `gnsswire-spartn` | `gnsswire.spartn` | SPARTN v2 framing, AES-128-CTR, OCB, HPAC, GAD, BPAC |
| `gnsswire-skytraq` | `gnsswire.skytraq` | SkyTraq binary framing, raw measurements (0xDD, 0xE5), navigation data bits (0xE0 to 0xE3, 0xE6) |
| `gnsswire-rinex` | `gnsswire.rinex` | RINEX 3 and 4 observation files, read and written losslessly as text fields |
| `gnsswire-nav` | `gnsswire.nav` | GPS, Galileo, BeiDou and GLONASS navigation messages from UBX and SkyTraq words; ephemerides as RTCM 3 fields |

A project that needs only one format can depend on that distribution alone.
Every codec of a binary or sentence format has the same four functions,
`parse`, `scan`, `decode` and `encode`, and decodes to frozen dataclasses of
the raw integers on the wire (RINEX files are read and written whole, with
`read` and `write`):

```python
from gnsswire import nmea, rtcm3

# The 1005 example of RTCM 10403.3 section 4.2.
frame = rtcm3.parse(bytes.fromhex("D300133ED7D30202980EDEEF34B4BD62AC0941986F33360B98"), 0)
assert rtcm3.decode(frame).station == 2003

sentence = b"$GPZDA,082710.00,16,09,2002,00,00*64\r\n"
assert nmea.decode(nmea.parse(sentence, 0)).year == "2002"
```

## Limitations

This distribution adds nothing to the codecs. What each one does not
decode, how it is tested and the readings it takes where its
specification is ambiguous are in the "Limitations" section of its own
README.

## Licence

Released under the MIT licence. The source, the version policy and the
documentation of each codec are in the
[project repository](https://github.com/tracenav/gnsswire#readme).
