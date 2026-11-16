"""Make data/rtklib-igs.hex and data/rtklib-igs-decoded.json with RTKLIB (pyrtklib 0.2.7).

usage: gen_rtklib_igs.py OUT_HEX OUT_JSON

Fills RTKLIB's SSR state with seeded random corrections for GPS, GLONASS,
Galileo, QZSS, BeiDou and SBAS satellites, encodes every IGS SSR sub-type
RTKLIB's gen_rtcm3 writes (message 4076, sub-types 21 to 27, 41 to 47, 61
to 67, 81 to 87, 101 to 107 and 121 to 127; it has no encoder for IM201),
and decodes each frame again with a fresh RTKLIB decoder (input_rtcm3).
OUT_HEX gets the frames, OUT_JSON what RTKLIB's decoder read from each, in
RTKLIB's units (metres, seconds, degrees) and naming (satellites as RINEX
"G01", signals as RINEX observation codes), so that the test can compare
our integers, scaled by the IGS SSR resolutions, with an independent
reading. Needs no input file.

Not a test and not run by pytest: pyrtklib is not a dependency of this
workspace. See README.md beside this file, step 5.
"""

import json
import random
import sys

import pyrtklib as p

out_hex, out_json = sys.argv[1], sys.argv[2]
rng = random.Random(4076)

SYSTEMS = [  # RTKLIB system, PRNs it numbers, first sub-type, signals RTKLIB may send
    (p.SYS_GPS, range(1, 33), 21),
    (p.SYS_GLO, range(1, 28), 41),
    (p.SYS_GAL, range(1, 37), 61),
    (p.SYS_QZS, range(193, 203), 81),
    (p.SYS_CMP, range(1, 64), 101),
    (p.SYS_SBS, range(120, 159), 121),
]
# Interval codes 0 to 15 of IDF004, in seconds.
UDI = [1, 2, 5, 10, 15, 30, 60, 120, 240, 300, 600, 900, 1800, 3600, 7200, 10800]
# k of RTKLIB's ssr_t arrays (t0, udi, iod) for sub-type offsets 0 to 6.
K = {0: (0,), 1: (1,), 2: (0, 1), 3: (2,), 4: (4,), 5: (5,), 6: (3,)}


def fill(enc, sats, week, tow, udi, iod):
    t = p.gpst2time(week, tow)
    for sat in range(1, p.MAXSAT + 1):
        s = enc.ssr[sat - 1]
        s.update = 0
        for k in range(6):
            s.t0[k] = p.gpst2time(0, 0.0)
    for sat in sats:
        s = enc.ssr[sat - 1]
        for k in range(6):
            s.t0[k] = t
            s.udi[k] = udi
            s.iod[k] = iod
        s.iode = rng.randrange(256)
        for i, lim in enumerate((209.7, 209.7, 209.7)):
            s.deph[i] = rng.uniform(-lim, lim)
        for i in range(3):
            s.ddeph[i] = rng.uniform(-1.04, 1.04)
        s.dclk[0] = rng.uniform(-209.7, 209.7)
        s.dclk[1] = rng.uniform(-1.04, 1.04)
        s.dclk[2] = rng.uniform(-1.34, 1.34)
        s.hrclk = rng.uniform(-209.7, 209.7)
        s.ura = rng.randrange(64)
        s.yaw_ang = rng.uniform(0, 359)
        s.yaw_rate = rng.uniform(-2.7, 2.7)
        for c in range(p.MAXCODE):
            s.cbias[c] = 0.0
            s.pbias[c] = 0.0
        for c in rng.sample(range(p.MAXCODE), 8):
            s.cbias[c] = rng.uniform(-81.9, 81.9)
            s.pbias[c] = rng.uniform(-52.4, 52.4)
        s.update = 1


def satname(sat: int) -> str:
    prn = p.Arr1Dint(1)
    system = p.satsys(sat, prn)
    letter = {p.SYS_GPS: "G", p.SYS_GLO: "R", p.SYS_GAL: "E", p.SYS_QZS: "J", p.SYS_CMP: "C",
              p.SYS_SBS: "S"}[system]
    return f"{letter}{prn[0]:03d}"


def reading(dec, offset) -> dict:
    """What RTKLIB's decoder holds after one frame, for the satellites it set."""
    out = {}
    for sat in range(1, p.MAXSAT + 1):
        s = dec.ssr[sat - 1]
        ks = [k for k in K[offset] if s.t0[k].time]
        if not ks:
            continue
        k = ks[0]
        week = p.Arr1Dint(1)
        tow = p.time2gpst(s.t0[k], week)
        entry = {"tow": tow, "udi": s.udi[k], "iod_ssr": s.iod[k]}
        if offset in (0, 2):
            entry |= {"iode": s.iode, "deph": list(s.deph), "ddeph": list(s.ddeph)}
        if offset in (1, 2):
            entry["dclk"] = list(s.dclk)
        if offset == 3:
            entry["hrclk"] = s.hrclk
        if offset == 6:
            entry["ura"] = s.ura
        if offset == 4:
            entry["cbias"] = {p.code2obs(c + 1): s.cbias[c] for c in range(p.MAXCODE)
                              if s.cbias[c]}
        if offset == 5:
            entry["pbias"] = {p.code2obs(c + 1): s.pbias[c] for c in range(p.MAXCODE)
                              if s.pbias[c]}
            entry |= {"yaw_ang": s.yaw_ang, "yaw_rate": s.yaw_rate}
        out[satname(sat)] = entry
    return out


frames, readings = [], []
for round_ in range(3):
    for system, prns, first in SYSTEMS:
        enc = p.rtcm_t(); p.init_rtcm(enc)
        week, tow = 2300 + round_, float(rng.randrange(604800))
        enc.time = p.gpst2time(week, tow)
        udi = UDI[rng.randrange(16)]
        iod = rng.randrange(16)
        sats = sorted(p.satno(system, prn) for prn in rng.sample(list(prns), min(len(prns), 5)))
        fill(enc, sats, week, tow, udi, iod)
        for offset in range(7):
            subtype = first + offset
            if not p.gen_rtcm3(enc, 4076, subtype, round_ % 2) or not enc.nbyte:
                print("not encoded:", subtype, file=sys.stderr)
                continue
            raw = bytes(enc.buff[k] for k in range(enc.nbyte))
            dec = p.rtcm_t(); p.init_rtcm(dec)
            dec.time = enc.time
            ret = 0
            for b in raw:
                ret = p.input_rtcm3(dec, b)
            frames.append((f"RTKLIB 4076 sub-type {subtype}, seeded synthetic, round {round_}",
                           raw))
            readings.append({"subtype": subtype, "ret": ret, "sats": reading(dec, offset)})

# Part 2: every signal identifier. Code and phase bias frames built by
# gnsswire.rtcm3 (run from this checkout's sources), each satellite with
# biases for identifiers 0 to 15 or 16 to 31, every bias a different
# non-zero value, so that RTKLIB's reading shows which RINEX code (if any)
# its decoder gives each identifier.
ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "bits" / "src"), str(ROOT / "rtcm3" / "src")]
from gnsswire import rtcm3  # noqa: E402

for system, first in rtcm3.IGS_SYSTEMS.items():
    sats = (1, 2)   # IDF011 0 is satellite 64, beyond RTKLIB's numbering
    for offset, cls, sat_cls, sig_cls in (
            (4, rtcm3.IgsCodeBias, rtcm3.IgsCodeBiasSat, rtcm3.IgsCodeBiasSignal),
            (5, rtcm3.IgsPhaseBias, rtcm3.IgsPhaseBiasSat, rtcm3.IgsPhaseBiasSignal)):
        blocks = []
        for half, sat in enumerate(sats):
            ids = range(16 * half, 16 * half + 16)
            if offset == 4:
                biases = tuple(sig_cls(i, 100 * (i + 1)) for i in ids)
                blocks.append(sat_cls(sat, 16, biases))
            else:
                biases = tuple(sig_cls(i, 1, 0, 0, 1000 * (i + 1)) for i in ids)
                blocks.append(sat_cls(sat, 16, 64, 8, biases))
        head = dict(number=4076, version=1, subtype=first + offset, epoch=345600, interval=2,
                    multiple=0, iod_ssr=3, provider=0, solution=0)
        if offset == 5:
            head |= dict(dispersive=0, mw=0)
        raw = rtcm3.encode(cls(**head, satellite_count=2, satellites=tuple(blocks)))
        dec = p.rtcm_t(); p.init_rtcm(dec)
        dec.time = p.gpst2time(2300, 345600.0)
        ret = 0
        for b in raw:
            ret = p.input_rtcm3(dec, b)
        frames.append((f"gnsswire 4076 sub-type {first + offset}, every signal identifier", raw))
        readings.append({"subtype": first + offset, "ret": ret, "sats": reading(dec, offset)})

with open(out_hex, "w") as f:
    for note, raw in frames:
        f.write(f"{raw.hex()}  # {note}\n")
ABOUT = ("RTKLIB's decoding (input_rtcm3 of pyrtklib 0.2.7, a binding of RTKLIB, BSD 2-clause, "
         "copyright T. Takasu) of the frames of rtklib-igs.hex, line by line: its return value "
         "and its SSR state for each satellite it set, in RTKLIB's units. Made as described in "
         "packages/rtcm3/tests/make_data/README.md, step 5.")
with open(out_json, "w") as f:
    json.dump({"about": ABOUT, "frames": readings}, f, indent=1, sort_keys=True)
    f.write("\n")
print(len(frames))
