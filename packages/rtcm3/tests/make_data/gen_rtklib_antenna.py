"""Make data/rtklib-antenna.hex and data/rtklib-antenna-decoded.json with RTKLIB (pyrtklib 0.2.7).

usage: gen_rtklib_antenna.py OUT_HEX OUT_JSON

Encodes seeded random antenna and receiver descriptors with RTKLIB's
gen_rtcm3 as 1007, 1008 and 1033 (each station's data as all three), then
reads every frame back with a fresh RTKLIB decoder (input_rtcm3) and writes,
line by line, what the encoder was given and what the decoder read. Needs no
input file.

The descriptors are bytes, set one character at a time: pyrtklib takes a
one-character str for a C char and stores a code point below 256 as that
byte, so latin-1 text gives any byte from 0x01 to 0xFF (RTKLIB's strings end
at 0x00, so 0x00 cannot be sent this way). Reading back, pyrtklib gives a
string as UTF-8 text, or raises UnicodeDecodeError, which carries the bytes,
when it is not UTF-8.

Not a test and not run by pytest: pyrtklib is not a dependency of this
workspace. See README.md beside this file, step 6.
"""

import json
import random
import sys

import pyrtklib as p

out_hex, out_json = sys.argv[1], sys.argv[2]
STRINGS = ("antdes", "antsno", "rectype", "recver", "recsno")
# What each message carries, of RTKLIB's sta_t (Tables 3.5-8, 3.5-9, 3.5-36).
CARRIED = {1007: ("antdes",), 1008: ("antdes", "antsno"), 1033: STRINGS}
PRINTABLE = bytes(range(0x20, 0x7F))
LATIN1 = bytes(range(0x01, 0x100))


def put(arr, data: bytes) -> None:
    for i, b in enumerate(data):
        arr[i] = chr(b)
    arr[len(data)] = "\x00"


def get(arr) -> bytes:
    # arr[0] is the C string from the first byte to its NUL, decoded as UTF-8;
    # re-encoding gives its bytes back exactly, and bytes that are not UTF-8
    # come with the exception.
    try:
        return arr[0].encode("utf-8")
    except UnicodeDecodeError as exc:
        return bytes(exc.object)


def text(rng: random.Random, n: int, alphabet: bytes) -> bytes:
    return bytes(rng.choice(alphabet) for _ in range(n))


rng = random.Random(1008)
stations = [
    # Every count at 0 (section 3.5.12.5: unknown descriptors), lowest IDs.
    dict(staid=0, antsetup=0, lengths=(0, 0, 0, 0, 0), alphabet=PRINTABLE),
    # Every count at 31, the top of DF029 and DF032's range; highest IDs.
    dict(staid=4095, antsetup=255, lengths=(31,) * 5, alphabet=PRINTABLE),
    dict(staid=4095, antsetup=255, lengths=(31,) * 5, alphabet=LATIN1),
    # IGS's 20-character antenna descriptor (section 3.5.4), no serial number.
    dict(staid=rng.randrange(4096), antsetup=0, lengths=(20, 0, 20, 5, 0), alphabet=PRINTABLE),
]
for i in range(10):
    stations.append(dict(staid=rng.randrange(4096), antsetup=rng.randrange(256),
                         lengths=tuple(rng.randrange(32) for _ in STRINGS),
                         alphabet=(PRINTABLE, LATIN1)[i % 2]))

frames: list[tuple[str, bytes]] = []
readings = []
for k, s in enumerate(stations):
    enc = p.rtcm_t(); p.init_rtcm(enc)
    enc.staid = s["staid"]
    sta = enc.sta
    given = {"staid": s["staid"], "antsetup": s["antsetup"]}
    for name, n in zip(STRINGS, s["lengths"]):
        data = text(rng, n, s["alphabet"])
        put(getattr(sta, name), data)
        assert get(getattr(sta, name)) == data
        given[name] = data
    sta.antsetup = s["antsetup"]
    enc.sta = sta
    for number in (1007, 1008, 1033):
        if not p.gen_rtcm3(enc, number, 0, 0) or not enc.nbyte:
            print("not encoded:", k, number, file=sys.stderr)
            continue
        raw = bytes(enc.buff[i] for i in range(enc.nbyte))
        dec = p.rtcm_t(); p.init_rtcm(dec)
        ret = 0
        for b in raw:
            ret = p.input_rtcm3(dec, b)
        read = {"staid": dec.staid, "antsetup": dec.sta.antsetup}
        read |= {name: get(getattr(dec.sta, name)).decode("latin-1") for name in CARRIED[number]}
        frames.append((f"synthetic station {k} as {number}", raw))
        readings.append({
            "number": number, "ret": ret, "read": read,
            "given": {key: v.decode("latin-1") if isinstance(v, bytes) else v
                      for key, v in given.items()
                      if key in ("staid", "antsetup") or key in CARRIED[number]}})

with open(out_hex, "w") as f:
    for note, raw in frames:
        f.write(f"{raw.hex()}  # {note}\n")
ABOUT = ("RTKLIB's encoding and decoding (gen_rtcm3 and input_rtcm3 of pyrtklib 0.2.7, a "
         "binding of RTKLIB, BSD 2-clause, copyright T. Takasu) of the frames of "
         "rtklib-antenna.hex, line by line: the station data the encoder was given ('given'), "
         "and the decoder's return value and the station data it read ('read'), each string "
         "as the latin-1 text of its bytes. Made as described in "
         "packages/rtcm3/tests/make_data/README.md, step 6.")
with open(out_json, "w") as f:
    json.dump({"about": ABOUT, "frames": readings}, f, indent=1, sort_keys=True)
    f.write("\n")
print(len(frames))
