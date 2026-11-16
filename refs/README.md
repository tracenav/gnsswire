# refs

The specifications the codecs are written from. Stage local copies here for
reading; nothing in this directory is committed except this file, because
several of the documents are copyrighted. The sha256 prefix is that of the
copy the codecs were written from.

| Document | Used by | Where to get it | sha256 |
|---|---|---|---|
| RTCM 10403.3 (2016-10-07, 288 pages) | `rtcm3` | RTCM (sold by RTCM) | `535398c5…` |
| SPARTN v2.0.3 (2025-11-07, 53 pages) | `spartn` | spartnformat.org | `cce617b8…` |
| RINEX 3.05 and 4.02 | `rinex` (Tables A2 and A3, sections 5 and 6) | IGS | `05de6c89…`, `c267f641…` |
| u-blox F9 HPG 1.51 interface description, UBXDOC-963802114-13124 R01, UBX protocol version 27.50 (327 pages; `ublox_F9_HPG_1.51_InterfaceDescription.pdf`, text copy `ublox_F9_HPG_1.51_InterfaceDescription.txt`) | `ubx`; `nmea` (its NMEA chapter stands in for NMEA 0183 v4.11, which is not public); `nav` (signal identifiers, section 1.5.4) | content.u-blox.com | `ac5fb90c…` |
| u-blox D9 PMP 1.04 interface description, UBX-21040023 R01 (63 pages) | `ubx` (RXM-PMP version 0, section 2.13.1) | content.u-blox.com | `bd839453…` |
| u-blox X20 HPG 2.11 interface description, UBXDOC-304424225-21617 R01, UBX protocol version 50.11 (278 pages; `ublox_X20_HPG_2.11_InterfaceDescription.pdf`, text copy `ublox_X20_HPG_2.11_InterfaceDescription.txt`) | `ubx` (checked against: same tables as F9 HPG 1.51, sections 3.2 to 3.4, 3.14.22.1, 3.16.3.1, 3.16.6.1, 3.16.8.1); `nav` (signal identifiers, section 1.5.4) | content.u-blox.com | `4f99e644…` |
| u-blox X20 HPG 2.11 JSON interface description, `u-blox-X20-HPG-2.11.json` (the PDF's tables, machine-readable) | `ubx` (field tables cross-checked by script) | github.com/u-blox/u-blox-X20-interface-description-json, path `HPG/ZED-X20P/u-blox-X20-HPG-2.11.json`; its README lets anyone use, copy, modify and distribute it without fee | `22bff439…` |
| IS-GPS-200N (Aug 2022, 248 pages) | `nav` (GPS LNAV, from UBX-RXM-SFRBX and SkyTraq words), `rtcm3` field meanings | archive.gps.gov | `54ec544b…` |
| IRN-IS-200N-003 (2023-09-27, 48 pages; `IRN-IS-200N-003.pdf`, text copy `IRN-IS-200N-003.txt`), change notice to IS-GPS-200N | read with IS-GPS-200N (`nav`: Data ID, 20.3.3.5.1.1 and 6.4.6.4) | gps.gov, with IS-GPS-200N | `a12ea313…` |
| IRN-IS-200N-004 (2026-06-16, 54 pages; `IRN-IS-200N-004.pdf`, text copy `IRN-IS-200N-004.txt`), change notice to IS-GPS-200N | read with IS-GPS-200N (changes CNAV message type 40 only, which no codec decodes) | gps.gov, with IS-GPS-200N | `9727534c…` |
| Galileo OS SIS ICD v2.2 (November 2025, 130 pages; `Galileo_OS_SIS_ICD_v2.2.pdf`, text copy `Galileo_OS_SIS_ICD_v2.2.txt`) | `nav`, `rtcm3` field meanings | gsc-europa.eu | `1ca51b26…` |
| BDS B1I ICD v3.0 (89 pages) | `nav`, `rtcm3` field meanings | en.beidou.gov.cn | `7f2de6f6…` |
| GLONASS ICD edition 5.1, 2008, English (65 pages) | `nav`, `rtcm3` field meanings | unavco.org, gge.ext.unb.ca | `5c6226de…` |
| SkyTraq AN0039 v1.4.42 (2022-07-22), "Binary Messages Raw Measurement Data Extension of SkyTraq Phoenix GNSS Receiver" | `skytraq` (framing, message tables) | skytraq.com.tw (`/homesite/AN0039.pdf`) | `dd48d4e4…` |
| SkyTraq AN0037 v1.4.69 (2025-03-26), "Binary Messages of SkyTraq Phoenix GNSS Receiver" | `skytraq` (framing, checked against AN0039) | skytraq.com.tw (`/homesite/AN0037.pdf`) | `747f8947…` |
| IGS State Space Representation (SSR) Format, Version 1.00 (2020-10-05, 49 pages; `IGS_SSR_v1.00.pdf`, text copy `IGS_SSR_v1.00.txt`) | `rtcm3` (message 4076) | IGS, files.igs.org (`/pub/data/format/igs_ssr_v1.pdf`), free | `2077dde0…` (retrieved 2026-11-15) |
| CRC catalogue (Greg Cook, reveng.sourceforge.io/crc-catalogue/all.htm) | `bits` (CRC parameters and check values) | that page | `18b47f52…` (retrieved 2026-11-13) |

A text copy made with `pdftotext -layout` is convenient for searching, but
the PDF is the authority: check any table, formula or bit width against it,
because the text extraction can misplace columns and symbols. The skytraq
codec was written with the PDFs open and the text copies
(`SkyTraq_AN0039_1.4.42.txt`, `SkyTraq_AN0037_1.4.69.txt`) staged here.
