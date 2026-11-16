"""Make data/rtklib.hex with RTKLIB (pyrtklib 0.2.7) as the independent encoder.

usage: gen_rtklib.py GMSD7_20121014.rtcm3 BRDC00WRD_R_20263000000_01D_MN.rnx OUT testglo.rtcm3

Not a test and not run by pytest: pyrtklib is not a dependency of this
workspace. See README.md beside this file.
"""

import random
import sys

import pyrtklib as p

gmsd, brdc, out_path = sys.argv[1:4]
frames: list[tuple[str, bytes]] = []


def take(enc, mtype, note):
    ok = p.gen_rtcm3(enc, mtype, 0, 0)
    if ok and enc.nbyte:
        frames.append((note, bytes(enc.buff[k] for k in range(enc.nbyte))))
    return ok


# --- 1. observables of a public stream, re-encoded as MSM4 -------------------
dec = p.rtcm_t(); p.init_rtcm(dec)
enc = p.rtcm_t(); p.init_rtcm(enc)
made = {1074: 0, 1084: 0, 1124: 0}
empty = {1074: 0, 1084: 0, 1124: 0}
testglo = sys.argv[4]
for name, b in [("GMSD7_20121014", b) for b in open(gmsd, "rb").read()] + \
               [("testglo", b) for b in open(testglo, "rb").read()]:
    ret = p.input_rtcm3(dec, b)
    if ret == 1:
        enc.obs = dec.obs; enc.nav = dec.nav; enc.time = dec.time; enc.staid = dec.staid
        for t in made:
            if made[t] >= 40:
                continue
            if not p.gen_rtcm3(enc, t, 0, 0):
                continue
            frame = bytes(enc.buff[k] for k in range(enc.nbyte))
            if len(frame) == 28:   # empty satellite mask
                if empty[t]:
                    continue
                empty[t] += 1
            else:
                made[t] += 1
            frames.append((f"{name} observables as MSM4 {t}", frame))
print(made, empty)

# --- 2. station messages ------------------------------------------------------
enc = p.rtcm_t(); p.init_rtcm(enc)
rng = random.Random(1230)
for i in range(6):
    enc.staid = rng.randrange(4096)
    sta = enc.sta
    sta.pos[0] = -3947762.7496 + rng.uniform(-1e5, 1e5)
    sta.pos[1] = 3364399.8789 + rng.uniform(-1e5, 1e5)
    sta.pos[2] = 3699428.5111 + rng.uniform(-1e5, 1e5)
    sta.antsetup = rng.randrange(256)
    sta.itrf = rng.randrange(64)
    for field, text in (("antdes", "TRM59800.00     NONE"[: rng.randint(0, 20)]),
                        ("antsno", "12345"[: rng.randint(0, 5)]),
                        ("rectype", "TRIMBLE NETR9"[: rng.randint(0, 13)]),
                        ("recver", "4.85"[: rng.randint(0, 4)]),
                        ("recsno", "5035K69749"[: rng.randint(0, 10)])):
        arr = getattr(sta, field)
        for k, c in enumerate(text + "\0"):
            try:
                arr[k] = c
            except TypeError:
                arr[k] = ord(c)
    sta.glo_cp_align = rng.randrange(2)
    for k in range(4):
        sta.glo_cp_bias[k] = rng.choice([0.0, rng.uniform(-600, 600)])
    enc.sta = sta
    for t in (1005, 1033, 1230):
        take(enc, t, f"synthetic station {i} as {t}")

# --- 3. broadcast ephemerides of a public RINEX navigation file ---------------
obs, nav, sta = p.obs_t(), p.nav_t(), p.sta_t()
p.readrnx(brdc, 0, "", obs, nav, sta)
enc = p.rtcm_t(); p.init_rtcm(enc)
seen = set()
prn = p.Arr1Dint(1)
for i in range(nav.n):
    e = nav.eph[i]
    sys_ = p.satsys(e.sat, prn)
    if sys_ == 1:        # GPS
        key, t, idx = ("G", e.sat), 1019, e.sat - 1
    elif sys_ == 32:     # BDS
        key, t, idx = ("C", e.sat), 1042, e.sat - 1
    elif sys_ == 8 and e.code & 2:     # Galileo F/NAV
        key, t, idx = ("EF", e.sat), 1045, e.sat - 1 + p.MAXSAT
    elif sys_ == 8 and e.code & 5:     # Galileo I/NAV
        key, t, idx = ("EI", e.sat), 1046, e.sat - 1
    else:
        continue
    if key in seen:
        continue
    seen.add(key)
    enc.nav.eph[idx] = e
    enc.ephsat = e.sat
    enc.ephset = 1 if t == 1045 else 0
    enc.time = e.toe
    take(enc, t, f"BRDC00WRD_R_20263000000_01D_MN ephemeris as {t}")
for i in range(nav.ng):
    g = nav.geph[i]
    p.satsys(g.sat, prn)
    if ("R", g.sat) in seen:
        continue
    seen.add(("R", g.sat))
    enc.nav.geph[prn[0] - 1] = g
    enc.ephsat = g.sat
    enc.time = g.toe
    take(enc, 1020, "BRDC00WRD_R_20263000000_01D_MN ephemeris as 1020")

# --- 4. synthetic Galileo (and GPS, BDS) observables as MSM4 -------------------
CLIGHT = 299792458.0
SIGS = {8: [("1C", 1575.42e6), ("5Q", 1176.45e6), ("7Q", 1207.14e6), ("1X", 1575.42e6)],
        1: [("1C", 1575.42e6), ("2W", 1227.60e6), ("5Q", 1176.45e6)],
        32: [("2I", 1561.098e6), ("7I", 1207.14e6), ("6I", 1268.52e6)]}
NPRN = {8: 36, 1: 32, 32: 46}
MSG = {8: 1094, 1: 1074, 32: 1124}
enc = p.rtcm_t(); p.init_rtcm(enc)
rng = random.Random(1094)
ep = p.Arr1Ddouble(6)
for k, v in enumerate([2026, 10, 27, 12, 0, 0]):
    ep[k] = v
t0 = p.epoch2time(ep)
for epoch in range(30):
    for system in (8, 8, 1, 32):
        t = p.timeadd(t0, epoch * 1.0 + rng.random() * 1e-3)
        sats = sorted(rng.sample(range(1, NPRN[system] + 1), rng.randint(1, 12)))
        sigs = rng.sample(SIGS[system], rng.randint(1, len(SIGS[system])))
        while len(sats) * len(sigs) > 64:
            sats.pop()
        n = 0
        for s in sats:
            rho = rng.uniform(1.9e7, 2.8e7)
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
        take(enc, MSG[system], f"synthetic observables as MSM4 {MSG[system]}")

with open(out_path, "w") as f:
    for note, frame in frames:
        f.write(f"{frame.hex()}  # {note}\n")
print(len(frames))
