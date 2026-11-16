"""Step 1 of data/rtklib-decoded.txt: seeded synthetic raw-measurement frames.

usage: gen_frames.py OUT

Writes one frame per line as hex, encoded by gnsswire.skytraq from seeded
random measurements: MEAS_TIME (0xDC) followed by RAW_MEAS (0xDD) with the
same IOD, and EXT_RAW_MEAS (0xE5) for every GNSS type of AN0039. Every
channel has its pseudorange, Doppler and carrier phase marked available,
so that a decoder has no reason to drop one. Run in this workspace:

    uv run python -I make_data/gen_frames.py /tmp/frames.txt
"""

import random
import struct
import sys

from gnsswire import skytraq


def f8(x: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", x))[0]


def f4(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", x))[0]


rng = random.Random(0xE5)
lines = []
# AN0039, 0xDD: PRN for GPS, slot + 64 for GLONASS, SVID + 200 for BeiDou.
DD_SVIDS = [*range(1, 33), *range(65, 89), *range(201, 238)]
# AN0039, 0xE5: GNSS type, its SVIDs and its signal types.
E5 = {0: (range(1, 33), (0, 1, 2, 4)), 1: (range(120, 159), (0,)),
      2: (range(1, 25), (0, 2, 4)), 3: (range(1, 37), (0, 4, 5, 6)),
      4: (range(193, 203), (0, 1, 2, 4)), 5: (range(1, 64), (0, 1, 4, 5, 7))}
week, tow = 2400, 345_600_000
for epoch in range(20):
    iod = epoch % 256
    tow += 1000
    lines.append(skytraq.encode(skytraq.MeasTime(iod, week, tow, 1000)))
    svids = sorted(rng.sample(DD_SVIDS, rng.randint(1, 16)))
    channels = tuple(skytraq.RawMeasChannel(
        svid=s, cn0=rng.randint(25, 52), pseudorange=f8(rng.uniform(1.9e7, 2.6e7)),
        carrier=f8(rng.uniform(-1.4e8, 1.4e8)), doppler=f4(rng.uniform(-4500, 4500)),
        indicator=0x07) for s in svids)
    lines.append(skytraq.encode(skytraq.RawMeas(iod, len(channels), channels)))
    channels = []
    for gnss in sorted(rng.sample(sorted(E5), rng.randint(1, 6))):
        prns, signals = E5[gnss]
        for prn in sorted(rng.sample(list(prns), rng.randint(1, 4))):
            for signal in sorted(rng.sample(signals, rng.randint(1, len(signals)))):
                freq = rng.randint(0, 13) if gnss == 2 else 0
                channels.append(skytraq.ExtRawMeasChannel(
                    gnss_signal=signal << 4 | gnss, svid=prn,
                    freq_lock=rng.randint(0, 15) << 4 | freq, cn0=rng.randint(25, 52),
                    pseudorange=f8(rng.uniform(1.9e7, 4.0e7)),
                    carrier=f8(rng.uniform(-2.1e8, 2.1e8)),
                    doppler=f4(rng.uniform(-4500, 4500)), pseudorange_stdev=0,
                    carrier_stdev=0, doppler_stdev=0, indicator=0x0007, reserved2=0))
    lines.append(skytraq.encode(skytraq.ExtRawMeas(
        1, iod, week, tow, 1000, 0, 0, len(channels), tuple(channels))))
with open(sys.argv[1], "w") as out:
    out.writelines(raw.hex() + "\n" for raw in lines)
print(len(lines))
