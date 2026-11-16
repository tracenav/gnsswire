"""Make data/rtklib-msm.hex with RTKLIB (pyrtklib 0.2.7) as the independent encoder.

usage: gen_rtklib_msm.py GMSD7_20121014.rtcm3 testglo.rtcm3 OUT

Encodes, with RTKLIB's gen_rtcm3:

- the observations RTKLIB decodes from the two public captures as MSM1 to
  MSM7 of their system, three non-empty frames per message number (RTKLIB
  hands back one system per epoch from these files: BeiDou from GMSD7's
  MSM7, GLONASS from testglo's 1012);
- seeded random observations for every system RTKLIB encodes as MSM
  (GPS, GLONASS, Galileo, SBAS, QZSS, BeiDou) at every level;
- seeded random QZSS ephemerides as 1044.

Not a test and not run by pytest: pyrtklib is not a dependency of this
workspace. See README.md beside this file, step 3.
"""

import random
import sys

import pyrtklib as p

gmsd, testglo, out_path = sys.argv[1:4]
frames: list[tuple[str, bytes]] = []
LEVELS = range(1, 8)
SYSTEMS = {1: 1070, 4: 1080, 8: 1090, 2: 1100, 16: 1110, 32: 1120}   # RTKLIB SYS_* to base
NAMES = {1: "GPS", 4: "GLONASS", 8: "Galileo", 2: "SBAS", 16: "QZSS", 32: "BeiDou"}


def grab(enc) -> bytes:
    return bytes(enc.buff[k] for k in range(enc.nbyte))


# --- 1. observables of the public streams at every MSM level -------------------
dec = p.rtcm_t(); p.init_rtcm(dec)
enc = p.rtcm_t(); p.init_rtcm(enc)
made: dict[int, int] = {}
for name, path in (("GMSD7_20121014", gmsd), ("testglo", testglo)):
    for b in open(path, "rb").read():
        if p.input_rtcm3(dec, b) != 1:
            continue
        enc.obs = dec.obs; enc.nav = dec.nav; enc.time = dec.time; enc.staid = dec.staid
        for base in SYSTEMS.values():
            for level in LEVELS:
                t = base + level
                if made.get(t, 0) >= 3 or not p.gen_rtcm3(enc, t, 0, 0):
                    continue
                frame = grab(enc)
                if len(frame) == 28:   # header alone: no satellite of this system
                    continue
                made[t] = made.get(t, 0) + 1
                frames.append((f"{name} observables as MSM{level} {t}", frame))
print("from streams", sorted(made.items()))

# --- 2. synthetic observables of every system at every level -------------------
CLIGHT = 299792458.0
SIGS = {1: [("1C", 1575.42e6), ("2W", 1227.60e6), ("5Q", 1176.45e6)],
        4: [("1C", 1602.0e6), ("2C", 1246.0e6)],
        8: [("1C", 1575.42e6), ("5Q", 1176.45e6), ("7Q", 1207.14e6), ("1X", 1575.42e6)],
        2: [("1C", 1575.42e6), ("5I", 1176.45e6)],
        16: [("1C", 1575.42e6), ("2L", 1227.60e6), ("5Q", 1176.45e6)],
        32: [("2I", 1561.098e6), ("7I", 1207.14e6), ("6I", 1268.52e6)]}
NPRN = {1: 32, 4: 24, 8: 36, 2: 19, 16: 10, 32: 46}
FIRST = {1: 1, 4: 1, 8: 1, 2: 120, 16: 193, 32: 1}
enc = p.rtcm_t(); p.init_rtcm(enc)
rng = random.Random(1077)
ep = p.Arr1Ddouble(6)
for k, v in enumerate([2026, 10, 27, 12, 0, 0]):
    ep[k] = v
t0 = p.epoch2time(ep)
for k in range(13):          # 3 GLONASS frequency channels known to the encoder
    enc.nav.glo_fcn[k] = rng.randint(-7, 6) + 8
for epoch in range(6):
    for system, base in SYSTEMS.items():
        for level in LEVELS:
            t = p.timeadd(t0, epoch * 1.0 + rng.random() * 1e-3)
            prns = sorted(rng.sample(range(FIRST[system], FIRST[system] + NPRN[system]),
                                     rng.randint(1, min(10, NPRN[system]))))
            sigs = rng.sample(SIGS[system], rng.randint(1, len(SIGS[system])))
            while len(prns) * len(sigs) > 64:
                prns.pop()
            n = 0
            for s in prns:
                rho = rng.uniform(1.9e7, 3.8e7)
                d = enc.obs.data[n]
                d.time = t
                d.sat = p.satno(system, s)
                d.rcv = 1
                used = [sig for sig in sigs if rng.random() < 0.8] or sigs[:1]
                for j in range(3):
                    d.P[j] = d.L[j] = d.D[j] = 0.0
                    d.SNR[j] = 0
                    d.LLI[j] = 0
                    d.code[j] = 0
                for j, (code, freq) in enumerate(used[:3]):
                    d.code[j] = p.obs2code(code)
                    d.P[j] = rho + rng.uniform(-5, 5)
                    d.L[j] = (rho + rng.uniform(-10, 10)) * freq / CLIGHT if rng.random() < 0.9 else 0.0
                    d.D[j] = rng.uniform(-3000, 3000)
                    d.SNR[j] = int(rng.uniform(20, 55) / 0.001)
                    d.LLI[j] = rng.choice([0, 0, 0, 1, 2])
                enc.obs.data[n] = d
                n += 1
            enc.obs.n = n
            enc.time = t
            enc.staid = rng.randrange(4096)
            if p.gen_rtcm3(enc, base + level, 0, 0) and enc.nbyte:
                frames.append((f"synthetic {NAMES[system]} observables as MSM{level} "
                               f"{base + level}", grab(enc)))

# --- 3. synthetic QZSS ephemerides as 1044 --------------------------------------
enc = p.rtcm_t(); p.init_rtcm(enc)
rng = random.Random(1044)
for i in range(12):
    prn = 193 + rng.randrange(10)
    sat = p.satno(16, prn)
    e = enc.nav.eph[sat - 1]
    e.sat = sat
    e.week = 2400 + rng.randrange(20)
    toe = 16 * rng.randrange(37800)   # 16-s steps within the week
    e.toe = p.gpst2time(e.week, toe)
    e.toc = e.toe
    e.ttr = e.toe
    e.iode = rng.randrange(256)
    e.iodc = rng.randrange(1024)
    e.sva = rng.randrange(16)
    e.svh = rng.randrange(64)
    e.code = 2
    e.flag = 0
    e.fit = rng.choice([0.0, 2.0, 4.0])
    e.A = rng.uniform(4.0e7, 4.4e7)
    e.e = rng.uniform(0.0, 0.1)
    e.i0 = rng.uniform(0.6, 0.8)
    e.OMG0 = rng.uniform(-3.1, 3.1)
    e.omg = rng.uniform(-3.1, 3.1)
    e.M0 = rng.uniform(-3.1, 3.1)
    e.deln = rng.uniform(-1e-9, 1e-9)
    e.OMGd = rng.uniform(-3e-9, 0.0)
    e.idot = rng.uniform(-1e-10, 1e-10)
    for name in ("crc", "crs"):
        setattr(e, name, rng.uniform(-500.0, 500.0))
    for name in ("cuc", "cus", "cic", "cis"):
        setattr(e, name, rng.uniform(-1e-5, 1e-5))
    e.toes = toe
    e.f0 = rng.uniform(-1e-4, 1e-4)
    e.f1 = rng.uniform(-1e-11, 1e-11)
    e.f2 = 0.0
    e.tgd[0] = rng.uniform(-1e-8, 1e-8)
    enc.nav.eph[sat - 1] = e
    enc.ephsat = sat
    enc.ephset = 0
    enc.time = e.toe
    if p.gen_rtcm3(enc, 1044, 0, 0) and enc.nbyte:
        frames.append(("synthetic QZSS ephemeris as 1044", grab(enc)))

with open(out_path, "w") as f:
    for note, frame in frames:
        f.write(f"{frame.hex()}  # {note}\n")
print(len(frames))
