# gnsswire-ubx

u-blox UBX framing and a small set of messages, as integer fields.
Standard library only.

Import as `gnsswire.ubx`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme) for the
interface every codec shares and for the version policy. Written from the
freely available u-blox interface descriptions cited below: F9 HPG 1.51
(UBX protocol version 27.50), with D9 PMP 1.04 for RXM-PMP version 0, and
checked against X20 HPG 2.11 (UBX protocol version 50.11), which prints
the same tables.

```python
from gnsswire import ubx

leap = ubx.NavTimels(itow=345_600_000, version=0, reserved0=(0, 0, 0), src_of_curr_ls=2,
                     curr_ls=18, src_of_ls_change=2, ls_change=0, time_to_ls_event=0,
                     date_of_ls_gps_wn=0, date_of_ls_gps_dn=0, reserved1=(0, 0, 0), valid=0b11)
raw = ubx.encode(leap)
assert raw[:4] == b"\xb5\x62\x01\x26" and len(raw) == 8 + 24

stream = b"\x00\xb5" + raw + raw[:10]          # garbage, a frame, a cut-off frame
[frame] = ubx.scan(stream)
assert (frame.offset, frame.msg_class, frame.msg_id) == (2, 0x01, 0x26)
assert ubx.decode(frame) == leap
assert isinstance(ubx.parse(stream, frame.offset + frame.length), ubx.NeedMore)

words = ubx.RxmSfrbx(gnss_id=0, sv_id=5, sig_id=0, freq_id=0, num_words=2, chn=3, version=2,
                     reserved0=0, dwrd=(0x22C0_0000, 0x0000_1234))
assert ubx.decode(ubx.parse(ubx.encode(words))) == words
```

RXM-RAWX keeps its `R8` and `R4` fields (pseudorange, carrier phase, Doppler,
receiver time of week) as the unsigned integers of their IEEE 754 bits, so
that every frame round-trips exactly; turning them into numbers is one
`struct` call:

```python
import struct
from gnsswire import ubx

def r8(x): return struct.unpack("<Q", struct.pack("<d", x))[0]
def r4(x): return struct.unpack("<I", struct.pack("<f", x))[0]

one = ubx.RxmRawxMeas(pr_mes=r8(21_456_789.12), cp_mes=r8(112_754_321.25), do_mes=r4(-1234.5),
                      gnss_id=0, sv_id=12, sig_id=0, freq_id=0, locktime=64_500, cno=47,
                      pr_stdev=4, cp_stdev=3, do_stdev=2, trk_stat=0b0111, reserved1=0)
epoch = ubx.RxmRawx(rcv_tow=r8(345_600.0), week=2400, leap_s=18, num_meas=1, rec_stat=1,
                    version=1, reserved0=(0, 0), meas=(one,))
raw = ubx.encode(epoch)
assert len(raw) == 8 + 16 + 32
decoded = ubx.decode(ubx.parse(raw))
pseudorange = struct.unpack("<d", decoded.meas[0].pr_mes.to_bytes(8, "little"))[0]
assert pseudorange == 21_456_789.12
```

`decode` picks the table by class, ID and version byte, and raises
`Unsupported` for a version no specification describes, `FieldError` when the
payload does not fit the table, and `NoFrame` when given anything but a
`Frame` (such as the `NeedMore` or `Invalid` that `parse` returns); all
three derive from `ubx.Error`, a `ValueError`. `parse`, `scan` and
`encode_frame` take any bytes-like object.

| Message | Class | Version | Source | Same table in X20 HPG 2.11 |
|---|---|---|---|---|
| UBX-RXM-PMP (0x02 0x72) | `RxmPmpV0` | 0 | u-blox D9 PMP 1.04 Interface Description (UBX-21040023 R01), section 2.13.1.1 | not described |
| UBX-RXM-PMP (0x02 0x72) | `RxmPmp` | 1 | u-blox F9 HPG 1.51 Interface Description (UBXDOC-963802114-13124 R01), section 3.17.3.1 | section 3.16.3.1 |
| UBX-RXM-RAWX (0x02 0x15) | `RxmRawx`, `RxmRawxMeas` | 1 | same, section 3.17.6.1 | section 3.16.6.1 |
| UBX-RXM-SFRBX (0x02 0x13) | `RxmSfrbx` | 2 | same, section 3.17.9.1 | section 3.16.8.1 |
| UBX-NAV-TIMELS (0x01 0x26) | `NavTimels` | 0 | same, section 3.15.26.1 | section 3.14.22.1 |

The last column is the u-blox X20 HPG 2.11 Interface Description
(UBXDOC-304424225-21617 R01, UBX protocol version 50.11). It prints these
tables with the same rows, types, offsets and version bytes as the F9
document, framing (sections 3.2 to 3.4) included, and u-blox's JSON
interface description of the same release agrees row for row. It defines
no other version of them. The earlier F9 HPG 1.32 description prints the
same tables under the same section numbers. Both newer descriptions give
RXM-SFRBX's numWords as "up to 16" (F9 HPG 1.32: 10) and list more signal
identifiers (section 1.5.4) than F9 HPG 1.32; the codec keeps both as
sent.

Fields keep the interface description's names in snake case. Bitfields are
kept whole as unsigned integers, RXM-SFRBX data words as the U4 integers on
the wire, `R4` and `R8` values as the integers of their bits; scaling and
subframe interpretation are the caller's.

## Limitations

- Only the messages and versions in the table above are decoded. Other
  messages raise `Unsupported`, among them the security and trusted time
  messages of the F9 HPG 1.51 and X20 HPG 2.11 descriptions (SEC-OSNMA,
  SEC-SIG, SEC-SIGLOG and NAV-TIMETRUSTED), and so does a version byte no
  table has, such as
  RXM-RAWX version 0 (the F9 description's "UBX-RXM-RAWX-DATA0", whose
  table none of the documents above prints) or an RXM-SFRBX version other
  than 2.
- RXM-SFRBX navigation words are kept whole; `gnsswire-nav` reads them.
- Every message is tested on frames built from its table and on frames
  made by pyubx2; the test data holds no receiver capture.
