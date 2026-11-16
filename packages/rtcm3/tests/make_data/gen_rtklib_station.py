"""Make data/rtklib-station.hex with RTKLIB (pyrtklib 0.2.7) as the independent encoder.

usage: gen_rtklib_station.py OUT

Encodes seeded random station data with RTKLIB's gen_rtcm3 as 1006 (and,
from the same data, 1005), with antenna heights across DF028's range. Needs
no input file.

Not a test and not run by pytest: pyrtklib is not a dependency of this
workspace. See README.md beside this file, step 4.
"""

import random
import sys

import pyrtklib as p

out_path = sys.argv[1]
frames: list[tuple[str, bytes]] = []
enc = p.rtcm_t(); p.init_rtcm(enc)
rng = random.Random(1006)
for i in range(8):
    enc.staid = rng.randrange(4096)
    sta = enc.sta
    sta.pos[0] = -3947762.7496 + rng.uniform(-1e5, 1e5)
    sta.pos[1] = 3364399.8789 + rng.uniform(-1e5, 1e5)
    sta.pos[2] = 3699428.5111 + rng.uniform(-1e5, 1e5)
    sta.itrf = rng.randrange(64)
    sta.hgt = (0.0, 6.5535, rng.uniform(0, 6.5535))[min(i, 2)]
    enc.sta = sta
    for t in (1006, 1005):
        if p.gen_rtcm3(enc, t, 0, 0) and enc.nbyte:
            frames.append((f"synthetic station {i} as {t}",
                           bytes(enc.buff[k] for k in range(enc.nbyte))))

with open(out_path, "w") as f:
    for note, frame in frames:
        f.write(f"{frame.hex()}  # {note}\n")
print(len(frames))
