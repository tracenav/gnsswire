"""Copy the frames of the given message types out of public RTCM 3 files, deduplicated.

usage: extract_public.py 1005,1019,1020,1033,1077:8 OUT FILE...

A type written ``type:n`` keeps only the first n frames of that type (over
all files); a type without a limit keeps every frame. Uses
gnsswire.rtcm3.scan only to cut the files into frames.
"""

import os
import sys

from gnsswire import rtcm3

limits: dict[int, int | None] = {}
for item in sys.argv[1].split(","):
    t, _, n = item.partition(":")
    limits[int(t)] = int(n) if n else None
out = sys.argv[2]
seen = set()
kept: dict[int, int] = {}
lines = []
for path in sys.argv[3:]:
    data = open(path, "rb").read()
    for f in rtcm3.scan(data):
        t = int.from_bytes(f.payload[:2], "big") >> 4 if len(f.payload) > 1 else None
        raw = data[f.offset:f.offset + f.length]
        if t not in limits or raw in seen:
            continue
        if limits[t] is not None and kept.get(t, 0) >= limits[t]:
            continue
        seen.add(raw)
        kept[t] = kept.get(t, 0) + 1
        lines.append(f"{raw.hex()}  # {os.path.basename(path)} offset {f.offset}: {t}\n")
open(out, "w").writelines(lines)
print(len(lines))
