# gnsswire-skytraq

SkyTraq binary protocol framing, raw measurement and navigation data
messages, as integer fields. Standard library only.

Import as `gnsswire.skytraq`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme) for the
interface every codec shares and for the version policy. Written from
SkyTraq's freely available application notes AN0039 and AN0037.

```python
import struct
from gnsswire import skytraq

# The MEAS_TIME example of SkyTraq AN0039 (0xDC), behind a garbage byte.
stream = b"\x00" + bytes.fromhex("A0 A1 00 0A DC 3D 06 ED 0B 0C BC 40 03 E8 1A 0D 0A")
[frame] = skytraq.scan(stream)
epoch = skytraq.decode(frame)
assert (frame.offset, frame.msg_id) == (1, 0xDC)
assert (epoch.iod, epoch.week, epoch.tow, epoch.period) == (0x3D, 1773, 185_384_000, 1000)
assert skytraq.encode(epoch) == stream[1:]

def f8(x): return struct.unpack(">Q", struct.pack(">d", x))[0]
def f4(x): return struct.unpack(">I", struct.pack(">f", x))[0]

channel = skytraq.ExtRawMeasChannel(
    gnss_signal=0x00, svid=13, freq_lock=0xE0, cn0=50, pseudorange=f8(20_525_449.3),
    carrier=f8(-107_867_200.5), doppler=f4(-1_234.5), pseudorange_stdev=0, carrier_stdev=0,
    doppler_stdev=0, indicator=0x0007, reserved2=0)
raw = skytraq.ExtRawMeas(version=1, iod=13, week=1916, tow=111_952_000, period=1000,
                         indicator=0, reserved1=0, nmeas=1, meas=(channel,))
frame = skytraq.parse(skytraq.encode(raw))
assert len(skytraq.encode(raw)) == 7 + 14 + 31
decoded = skytraq.decode(frame)
assert struct.unpack(">d", decoded.meas[0].pseudorange.to_bytes(8, "big"))[0] == 20_525_449.3
```

`decode` picks the table by message ID, and raises `Unsupported` for a
message ID without a table or, for 0xE5 and 0xE6, a version no table
describes, `FieldError` when the body does not fit the table, and
`NoFrame` when given anything but a `Frame` (such as the `NeedMore` or
`Invalid` that `parse` returns); all three derive from `skytraq.Error`, a
`ValueError`. `parse`, `scan` and `encode_frame` take any bytes-like object.

| Message | Class | Source |
|---|---|---|
| MEAS_TIME (0xDC) | `MeasTime` | SkyTraq AN0039 version 1.4.42 |
| RAW_MEAS (0xDD) | `RawMeas`, `RawMeasChannel` | same |
| GPS SUBFRAME (0xE0) | `GpsSubframe` | same |
| GLONASS STRING (0xE1) | `GlonassString` | same |
| BEIDOU2 D1 SUBFRAME (0xE2) | `BeidouD1Subframe` | same |
| BEIDOU2 D2 SUBFRAME (0xE3) | `BeidouD2Subframe` | same |
| EXT_RAW_MEAS version 1 (0xE5) | `ExtRawMeas`, `ExtRawMeasChannel` | same |
| GENERAL SUBFRAME version 1 (0xE6) | `GeneralSubframe` | same |

Framing follows the "Binary Message Structure" section, which AN0039 and
AN0037 (the Phoenix binary message protocol, version 1.4.69) print alike.
Values are the integers on the wire, big-endian as the notes say: SPFP and
DPFP values (pseudorange, carrier phase, Doppler) as the unsigned integers
of their IEEE 754 bits, navigation words and bitfields whole. Scaling and
subframe interpretation are the caller's.

## Limitations

- Only the eight messages above are decoded. Other messages, such as
  SV_CH_STATUS (0xDE), RCV_STATE (0xDF) and the rest of AN0037, raise
  `Unsupported`, and so do EXT_RAW_MEAS (0xE5) and GENERAL SUBFRAME (0xE6)
  of a version other than 1.
- The checksum is the XOR of the PL payload bytes, from the message ID, as
  AN0039's prose says; its pseudo-code, read literally, would take one
  byte more.
- SVIDs are kept as sent; AN0039's numbering (GLONASS slot + 64, BeiDou
  SVID + 200, IRNSS SVID + 240) is the caller's to apply.
- Tested on AN0039's example frame of each message and on synthetic
  frames, with RTKLIB's decoding of synthetic 0xDC, 0xDD and 0xE5 frames
  as a cross-check; the test data holds no receiver capture.

## Licence

Released under the MIT licence. The sdist (not the wheel) also holds
`tests/data/rtklib-decoded.txt`, this project's synthetic frames with what
RTKLIB's SkyTraq decoder read from them, under RTKLIB's BSD 2-clause
licence; its notice is in `tests/THIRD_PARTY_NOTICES.md`, and how it was
made in `tests/make_data/README.md`.
