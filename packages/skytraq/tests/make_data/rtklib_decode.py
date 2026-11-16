"""Step 2 of data/rtklib-decoded.txt: what RTKLIB's SkyTraq decoder makes of the frames.

usage: rtklib_decode.py FRAMES OUT

Feeds every frame of FRAMES (step 1), in order, to RTKLIB's input_stq
(pyrtklib 0.2.7, a binding of RTKLIB, BSD 2-clause, copyright T. Takasu)
and writes each frame's hex followed, when RTKLIB returned observations
for it, by what it decoded: for every satellite and frequency slot with a
signal code, the system, PRN, code, pseudorange, carrier phase, Doppler and
SNR, as JSON. Not a test and not run by pytest: pyrtklib is not a
dependency of this workspace. See README.md beside this file.
"""

import json
import sys

import pyrtklib as p

SYSTEMS = {1: "GPS", 2: "SBAS", 4: "GLONASS", 8: "Galileo", 16: "QZSS", 32: "BeiDou",
           64: "IRNSS"}
raw = p.raw_t()
p.init_raw(raw, p.STRFMT_STQ)
prn = p.Arr1Dint(1)
out = []
for line in open(sys.argv[1]):
    frame = bytes.fromhex(line.strip())
    got = 0
    for b in frame:
        got = p.input_stq(raw, b) or got
    obs = []
    if got == 1:
        for i in range(raw.obs.n):
            d = raw.obs.data[i]
            system = SYSTEMS[p.satsys(d.sat, prn)]
            for j in range(3):
                if d.code[j]:
                    obs.append([system, prn[0], d.code[j], d.P[j], d.L[j], d.D[j], d.SNR[j]])
    out.append(frame.hex() + ("  " + json.dumps(obs) if obs else "") + "\n")
with open(sys.argv[2], "w") as f:
    f.writelines(out)
print(len(out))
