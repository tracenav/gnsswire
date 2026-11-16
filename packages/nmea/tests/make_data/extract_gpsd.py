"""Cut the GGA and ZDA sentences out of a gpsd regression log (not run by pytest).

    uv run python -I make_data/extract_gpsd.py ublox-zed-f9p-nmea.log data/gpsd-zed-f9p.nmea

The log is gitlab.com/gpsd/gpsd, test/daemon/ublox-zed-f9p-nmea.log, saved
into a fresh directory under /tmp. Lines are kept byte for byte, minus CR LF.
"""

import re
import sys

HEADER = """\
# GGA and ZDA sentences from gpsd's regression log test/daemon/ublox-zed-f9p-nmea.log
# (gitlab.com/gpsd/gpsd, branch master, retrieved 2026-11-14), unchanged and in
# file order, one per line without the CR LF; every other line of the log is
# left out (make_data/extract_gpsd.py).
#
# From the log's header: ZED-F9P NMEA; u-blox ZED-F9P, firmware hpg1.11;
# 2019-04-12; Dunedin, New Zealand; NMEA only.
# "This file is Copyright 2010 by the GPSD project. BSD terms apply: see the
# file COPYING in the distribution root for details." (BSD 2-clause)
"""


def main(src: str, dst: str) -> None:
    raw = open(src, "rb").read()
    lines = [line.rstrip(b"\r") for line in raw.split(b"\n")
             if re.match(rb"\$[A-Z]{2}(GGA|ZDA),", line)]
    with open(dst, "w", newline="\n") as f:
        f.write(HEADER)
        f.writelines(line.decode("ascii") + "\n" for line in lines)
    print(f"{len(lines)} sentences, CR LF in source: {b'\r\n' in raw}")


if __name__ == "__main__":
    main(*sys.argv[1:])
