"""Step 1 of data/rtklib-read.json: a seeded synthetic RINEX 3.05 observation file.

usage: gen_obs.py OUT

Writes an observation file made by gnsswire.rinex from seeded random
values, laid out by the formats of RINEX 3.05 Tables A2 and A3: every
system, one signal per band and C, L, D and S for each, missing
observations (blank), LLI and SSI digits or blanks, and records whose
trailing blank fields are truncated. Run in this workspace:

    uv run python -I make_data/gen_obs.py /tmp/synthetic.rnx
"""

import random
import sys

from gnsswire import rinex
from gnsswire.rinex import EpochRecord, HeaderRecord, Observation, SatelliteRecord

TYPES = {
    "G": "C1C L1C D1C S1C C2W L2W D2W S2W C5Q L5Q D5Q S5Q",
    "R": "C1C L1C D1C S1C C2P L2P D2P S2P",
    "E": "C1C L1C D1C S1C C5Q L5Q D5Q S5Q C7Q L7Q D7Q S7Q",
    "C": "C2I L2I D2I S2I C7I L7I D7I S7I C6I L6I D6I S6I",
    "J": "C1C L1C D1C S1C C2L L2L D2L S2L C5Q L5Q D5Q S5Q",
    "S": "C1C L1C D1C S1C C5I L5I D5I S5I",
}
PRNS = {"G": range(1, 33), "R": range(1, 25), "E": range(1, 37), "C": range(1, 47),
        "J": range(1, 8), "S": range(20, 59)}


def h(content: str, label: str) -> HeaderRecord:
    return HeaderRecord(content.ljust(60), label.ljust(20))


def obs_types_records() -> list[HeaderRecord]:
    out = []
    for system, types in TYPES.items():
        t = types.split()
        for i in range(0, len(t), 13):
            head = f"{system}  {len(t):3d}" if i == 0 else " " * 6
            out.append(h(head + "".join(f" {x}" for x in t[i:i + 13]), "SYS / # / OBS TYPES"))
    return out


def value(rng: random.Random, kind: str) -> float:
    return {"C": lambda: rng.uniform(1.9e7, 4.0e7), "L": lambda: rng.uniform(-9e8, 9e8),
            "D": lambda: rng.uniform(-5000, 5000), "S": lambda: rng.uniform(20, 55)}[kind]()


def observation(rng: random.Random, kind: str) -> Observation:
    if rng.random() < 0.1:
        return Observation(" " * 14, " ", " ")
    lli = str(rng.randrange(8)) if kind == "L" and rng.random() < 0.5 else " "
    ssi = str(rng.randint(1, 9)) if kind in "CL" and rng.random() < 0.5 else " "
    return Observation(f"{value(rng, kind):14.3f}", lli, ssi)


def truncate(obs: list[Observation]) -> tuple[Observation, ...]:
    """Drop the trailing blanks of the record (RINEX 3.05 section 6.5)."""
    text = "".join(o.value + o.lli + o.ssi for o in obs).rstrip()
    out = []
    for i in range(0, len(text), 16):
        chunk = text[i:i + 16]
        out.append(Observation(chunk[:14], chunk[14:15], chunk[15:16]))
    return tuple(out)


rng = random.Random(0x524E58)
header = [
    h("     3.05           OBSERVATION DATA    M", "RINEX VERSION / TYPE"),
    h("gen_obs.py          gnsswire            20260101 000000 UTC", "PGM / RUN BY / DATE"),
    h("SYNTHETIC", "MARKER NAME"),
    h("  4375274.0000   587466.0000  4589095.0000", "APPROX POSITION XYZ"),
    *obs_types_records(),
    h("  2026    01    01    00    00    0.0000000     GPS", "TIME OF FIRST OBS"),
    h("", "END OF HEADER"),
]
epochs = []
for k in range(30):
    sats = []
    for system in TYPES:
        for prn in sorted(rng.sample(list(PRNS[system]), rng.randint(0, 4))):
            kinds = [t[0] for t in TYPES[system].split()]
            sats.append(SatelliteRecord(f"{system}{prn:02d}",
                                        truncate([observation(rng, kind) for kind in kinds])))
    sats = [s for s in sats if s.obs]
    clock = f"{rng.uniform(-0.01, 0.01):15.12f}" if rng.random() < 0.5 else ""
    record = EpochRecord(" 2026", " 01", " 01", " 00", f" {k // 2:02d}", f"{30.0 * (k % 2):11.7f}",
                         "  0", f"{len(sats):3d}", "      " if clock else "", clock, "")
    epochs.append(rinex.Epoch(record, satellites=tuple(sats)))
text = rinex.write(rinex.ObsFile(tuple(header), tuple(epochs)))
assert rinex.write(rinex.read(text)) == text
with open(sys.argv[1], "w", newline="") as out:
    out.write(text)
print(len(epochs), sum(len(e.satellites) for e in epochs))
