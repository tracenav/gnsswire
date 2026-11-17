Version 0.2.1 (2026-XX-XX)
==========================
* gnsswire-antex 0.1.0: ANTEX 1.4 antenna calibration files, a new distribution
  * Phase centre offsets and variations of receiver and satellite antennas, per frequency, read and written losslessly
* gnsswire-rinex 0.1.1: RINEX 2 observation files and RINEX navigation files
  * RINEX 2 observation files with `read2` and `write2`
  * Navigation files of RINEX 2, 3 and 4 with `read_nav` and `write_nav`, and their fields by name
  * Reading is about forty times faster: a record class's column layout is worked out once, not for every line
* gnsswire 0.2.1 installs gnsswire-antex with the others
Version 0.2.0 (2026-11-16)
==========================
* First release: codecs for GNSS wire formats, one distribution per format
* gnsswire 0.2.0 installs them all; or install only the one you need
* gnsswire-nmea 0.2.0: NMEA 0183 GGA and ZDA sentences
* gnsswire-ubx 0.1.1: u-blox UBX RXM-PMP, RXM-RAWX, RXM-SFRBX and NAV-TIMELS
* gnsswire-rtcm3 0.2.0: RTCM 3 messages
  * Station, antenna and receiver: 1005 to 1008 and 1033, and GLONASS biases 1230
  * Ephemerides: 1019, 1020, 1042, 1044, 1045 and 1046
  * MSM1 to MSM7 for GPS, GLONASS, Galileo, SBAS, QZSS and BeiDou
  * IGS SSR corrections (message 4076): orbit, clock, biases, URA, ionosphere
* gnsswire-spartn 0.2.0: SPARTN v2 OCB, HPAC, GAD and BPAC, with AES-128 decryption
* gnsswire-skytraq 0.1.0: SkyTraq binary raw measurements and navigation data
* gnsswire-rinex 0.1.0: RINEX 3 and 4 observation files
* gnsswire-nav 0.1.0: GPS, Galileo, BeiDou and GLONASS navigation messages
  * GPS LNAV by IS-GPS-200N with IRN-IS-200N-003 and -004: subframe 4 and 5 pages of a Data ID other than 2 are kept whole
  * Read from UBX and SkyTraq, assembled into ephemerides as RTCM 3 fields
* gnsswire-bits 0.2.0: the bit reader and writer, CRCs and field tables they share
* Exact round trip: encoding a decoded frame gives back its bytes
* Fields are the raw integers on the wire (text for NMEA and RINEX), unscaled
* Written from the published specifications
* Pure Python, standard library only, Python 3.11 or later
* MIT licence
