"""Step 2 of data/rtklib-read.json: what RTKLIB's RINEX reader makes of the file.

usage: rtklib_read.py RINEX OUT

Reads RINEX (step 1) with RTKLIB's readrnx (pyrtklib 0.2.7, a binding of
RTKLIB, BSD 2-clause, copyright T. Takasu) and writes a JSON object: the
file's text under "rinex", and under "rtklib" one entry per observation
RTKLIB holds, in its order: GPS time of week, satellite, signal (band and
attribute, as RTKLIB's code2obs gives it), pseudorange, carrier phase,
Doppler (RTKLIB keeps it as a float32), SNR (in RTKLIB's unit of
0.001 dB-Hz) and LLI, for every frequency slot with a signal. Not a test and not run by pytest: pyrtklib is not a
dependency of this workspace. See README.md beside this file.
"""

import json
import sys

import pyrtklib as p

path, out = sys.argv[1], sys.argv[2]
with open(path, newline="") as f:
    text = f.read()
obs, nav, sta = p.obs_t(), p.nav_t(), p.sta_t()
if p.readrnx(path, 1, "", obs, nav, sta) != 1:
    raise SystemExit("readrnx failed")
# RTKLIB's system codes; SBAS and QZSS satellite numbers back to RINEX's
# "PRN minus 100" (3.05 section 5.3.3) and "PRN minus 192".
SYSTEMS = {1: ("G", 0), 2: ("S", 100), 4: ("R", 0), 8: ("E", 0), 16: ("J", 192),
           32: ("C", 0), 64: ("I", 0)}
week = p.Arr1Dint(1)
prn = p.Arr1Dint(1)
rows = []
for i in range(obs.n):
    d = obs.data[i]
    tow = p.time2gpst(d.time, week)
    letter, offset = SYSTEMS[p.satsys(d.sat, prn)]
    sat = f"{letter}{prn[0] - offset:02d}"
    for j in range(p.NFREQ + p.NEXOBS):
        if d.code[j]:
            rows.append([tow, sat, p.code2obs(d.code[j]), d.P[j], d.L[j], d.D[j], d.SNR[j],
                         d.LLI[j]])
with open(out, "w") as f:
    json.dump({"rinex": text, "rtklib": rows}, f, indent=0)
    f.write("\n")
print(len(rows))
