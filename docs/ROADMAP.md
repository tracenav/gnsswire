# Roadmap

gnsswire is a set of small distributions that turn GNSS wire bytes into
the fields on the wire (integers; text for NMEA and RINEX) and back, each
usable on its own, written from the published specifications. Every new message is a field table
added as data, with the checks the existing ones have; a frame that raised
`Unsupported` then decodes. What each distribution does not decode today
is under "Limitations" in the repository README.

## Next

- `nmea`: RMC, GNS, GSA and GSV, and the u-blox PUBX sentences.
- `rtcm3`: the NavIC (1041) and SBAS (1043) ephemerides and NavIC MSM
  (1131 to 1137). RTCM 10403.3 does not define them; this waits on the
  later RTCM document that does.
- `skytraq`: SV_CH_STATUS (0xDE), RCV_STATE (0xDF) and other messages of
  SkyTraq AN0037.
- `nav`: Galileo I/NAV word types 7 to 9, 16 to 20 and 22 (word 22 as
  Galileo OS SIS ICD issue 2.2 defines it) and F/NAV page types 5 and 6,
  which are now kept whole.
- `spartn`: the dynamic key message (SM 4-0), the other key lengths of
  SF087 and the ChaCha12 and ChaCha20 ciphers of SF085, and verification
  of embedded authentication data (TF017).
- Receiver frames from public sources as test data, for the messages now
  tested only on frames built from the tables or by an independent
  encoder.

## Later

- `nav`: QZSS L1C/A, GPS CNAV (L2C, L5; with the integrity support
  message, message type 40, as IRN-IS-200N-004 defines it), BeiDou B1C,
  B2a and B3I, Galileo E6, SBAS and NavIC navigation messages, and Galileo
  F/NAV in UBX-RXM-SFRBX, each once a published document gives its layout.
- Signal and observation codes for the Galileo E5a-QP pilot (OS SIS ICD
  issue 2.2), once a carrier or RINEX document defines them.
- `ubx`: RXM-RAWX version 0 and other message versions, each once a
  document prints its table.
- `ubx`: messages of the u-blox F9 HPG 1.51 and X20 HPG 2.11
  descriptions, such as SEC-OSNMA, SEC-SIG and SEC-SIGLOG (navigation
  message authentication, jamming and spoofing status) and
  NAV-TIMETRUSTED.
- `rtcm3`: IGS SSR sub-types that v1.00 reserves (such as 202), if a
  published IGS document defines them.
- `rinex`: the header records now kept as text, such as GLONASS SLOT /
  FRQ # and SYS / PHASE SHIFT, read into fields.
- RINEX navigation files and SP3; RINEX 2 observation files.
- C decoders generated from the same field tables, for embedded targets.

## Not planned

- The standard RTCM SSR messages (1057 to 1068 and 1240 to 1270): the
  state-space formats carried are SPARTN and IGS SSR (message 4076), which
  holds the same content for every system in one published document.
  `decode` raises `Unsupported` for them.
- SPARTN group authentication (SM 4-1): SPARTN v2 deprecates it, to be
  removed in later versions.
- Scaling to physical units: messages hold the integers on the wire, which
  keeps every codec lossless; scaling is the caller's.
- Expanding compressed RINEX (Hatanaka CRINEX, gzip): these are formats of
  their own; a file is expanded before `read`.
- Correcting transmission errors: the parity, Hamming code, CRC or
  checksum detects them, and the word or frame is refused.
