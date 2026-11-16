# gnsswire-spartn

SPARTN v2 framing, decryption and OCB/HPAC/GAD/BPAC messages, as integer
fields. Depends on `gnsswire-bits` only.

Import as `gnsswire.spartn`. Part of the gnsswire workspace; see the
[repository README](https://github.com/tracenav/gnsswire#readme) for the
interface every codec shares and for the version policy. Written from the
freely available SPARTN v2.0.3 interface specification.

```python
from gnsswire import spartn

# A geographic area definition (SM 2-0) with one area, in a frame with a
# 32-bit time tag and the 24-bit CRC (TF005 = 2).
area = spartn.GadArea(area_id=1, latitude=1000, longitude=2000, latitude_nodes=3,
                      longitude_nodes=4, latitude_spacing=5, longitude_spacing=6)
gad = spartn.Gad(siou=7, aiou=1, reserved=0, area_count=0, areas=(area,))  # SF030 = count - 1
plain = spartn.Message(
    message_type=2, eaf=0, crc_type=2,
    description=spartn.Description(subtype=0, time_tag_type=1, time_tag=123_456_789,
                                   solution_id=1, processor_id=0, encryption_id=None,
                                   sequence=None, auth_indicator=None, auth_length=None),
    body=gad)
raw = spartn.encode(plain)
[frame] = spartn.scan(b"\x00garbage" + raw)
assert spartn.decode(frame) == plain

# Encrypted frames (EAF set) need the key: AES-128-CTR, IV of section 8.15.1.
key = bytes(range(16))
sealed = spartn.Message(2, 1, 2, spartn.Description(0, 1, 123_456_789, 1, 0, 3, 17, 0, 0), gad)
wire = spartn.encode(spartn.encrypt(spartn.to_frame(sealed), key))
frame = spartn.parse(wire)
try:
    spartn.decode(frame)
except spartn.Encrypted:
    pass
assert spartn.decode(spartn.decrypt(frame, key)) == sealed
```

A decoded `Message` is the frame's transport fields (TF002 to TF015, and the
embedded authentication data TF017 kept as bytes, not verified) with the
message table in `body`. Every exception derives from `spartn.Error` (a
`ValueError`). `decode` raises `Encrypted` for a frame that has not been
through `decrypt`, `Unsupported` for a type and subtype without a table,
`FieldError` (also a `gnsswire.bits.BitError`) when the payload is shorter
than its table, and `NoFrame` when given anything but a `Frame`, such as
the `NeedMore` or `Invalid` that `parse` returns. Any bytes-like object is
accepted where bytes are.

| Message | Class | SPARTN v2.0.3 |
|---|---|---|
| framing, TF001 to TF018 | `Frame`, `Description` | section 7, Tables 7.1 and 7.2 |
| OCB, SM 0-0 to 0-4 (GPS, GLONASS, Galileo, BeiDou, QZSS) | `Ocb` | section 6.5.1 |
| OCB header, SM 0-0 to 0-15 | `OcbHeader`, `decode_ocb_header` | Table 6.3; section 8.4 item 5 |
| HPAC, SM 1-0 to 1-4 | `Hpac` | section 6.5.2 |
| GAD, SM 2-0 | `Gad` | section 6.5.3, Tables 6.23 and 6.24 |
| BPAC, SM 3-0 | `Bpac` | section 6.5.4, Tables 6.25 to 6.28 |
| AES-128-CTR | `decrypt`, `encrypt`, `iv` | section 8.15; FIPS 197; RFC 3686 |

Fields are the raw SF integers; scale them with the resolutions of Table 6.2.
The phase and code bias masks are kept as sent; Table 6.2 names the signal
of each bit. v2.0.3 defines Galileo bits 3 and 4 (SF102: L8Q and L6C;
SF105: C8Q and C6C), which v2.0.2 left spare; the mask widths are
unchanged, so frames of either version decode the same.

**Data after a table.** Section 8.4 item 4: "decoder implementations should
not use payload length to indicate where they stop decoding", so that
fields can be added to a message later. `decode` keeps whatever follows the
table in the body's `extension`: `None` for nothing but zero fill bits,
otherwise a `gnsswire.bits.Extension` that `encode` writes back, so the
frame round-trips. `decode(frame, strict=True)` refuses such a payload with
`FieldError`.

**OCB header of any subtype.** Section 8.4 item 5 asks decoders to read
the end-of-set flag (SF010) of every OCB message "even though they may not
understand the data". `decode_ocb_header(frame)` reads the header block of
Table 6.3 for every subtype, 0 to 15; `ephemeris_type`, `mask_size` and
`mask` are `None` for subtypes without a table (their widths depend on the
constellation).

**Do-not-use satellites (AMBIGUOUS).** Table 6.2 says a satellite with SF013
(DNU) set carries no other data; Table 8.2 sizes its block as SF013, SF014
and SF015. This codec follows Table 6.2: SF013 is defined there twice in the
same words, Table 8.2 only gives "nominal" sizes, and its OCB header length
does not hold for every constellation either. Where a payload fits only the
Table 8.2 reading, the tolerant `decode` returns that reading instead, and
`spartn.dnu_reading(message.body)` reports which one it is
(`DNU_TABLE_6_2` or `DNU_TABLE_8_2`); `encode` writes a message back with
the reading it was decoded with. `strict=True` accepts Table 6.2 only.

**BPAC VTEC blocks (AMBIGUOUS).** Table 6.26 repeats the VTEC block "for each
grid point", while SF079 is a mask of the grid points present and Table 8.2
counts the blocks as the number of points present. The codec follows the
mask: one `BpacGridPoint` per set bit of `present`.

**Time tags and the IV.** A frame with the 16-bit time tag (seconds within
a half day of the constellation's time) needs the caller to supply the full
32-bit tag for the IV (`decrypt(frame, key, time_tag)`): section 8.15.1
does not say how to expand it. `iv`, `decrypt` and `encrypt` raise
`TimeTagError` when the full tag supplied does not reduce to the frame's
16-bit tag (`time_tag % HALF_DAY`), or when a frame with a 32-bit tag is
given another one.

## Limitations

- Not decoded (`Unsupported`): the dynamic key message (SM 4-0, which
  `decrypt` and `encrypt` refuse too), group authentication (SM 4-1),
  proprietary messages, and any other type or subtype without a table
  above; `decode_ocb_header` still reads the header of every OCB subtype.
- Decryption is AES-128-CTR with a 16-byte key only: the other key lengths
  of SF087 and the ChaCha12 and ChaCha20 ciphers of SF085 are not
  implemented. Embedded authentication data (TF017) is kept, not verified.
- Tested only on frames generated from the tables, compared with pyspartn,
  and decryption against the `cryptography` package; the test data holds
  no frame from a correction service. pyspartn refuses OCB frames with an
  extended bias mask, so those are checked by round trips and Table 8.2's
  sizes only.
- The message CRCs (TF018) are taken unreflected, as Table 7.2 prints
  them: CRC-8/SMBUS, CRC-16/XMODEM, CRC-24/LTE-A and CRC-32/BZIP2.
  TF006's CRC-4 is the reflected one of Table 7.1.
- TF017 is read whenever TF014 is above 1, with the lengths Table 7.1
  gives every TF015 value.
- Do-not-use satellites, BPAC blocks and 16-bit time tags: the readings
  taken are in the sections above.
