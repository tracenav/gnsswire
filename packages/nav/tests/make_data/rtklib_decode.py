"""Step 2 of data/rtklib-decoded.txt: what RTKLIB's UBX decoder makes of the frames.

usage: rtklib_decode.py FRAMES OUT

Feeds every frame of FRAMES (step 1), in order, to RTKLIB's input_ubx
(pyrtklib 0.2.7, a binding of RTKLIB, BSD 2-clause, copyright T. Takasu)
and writes each frame's hex followed, when RTKLIB reported a new
ephemeris for it (return value 2), by that ephemeris as JSON: RTKLIB's
system and PRN and its eph_t or geph_t fields, in its units (seconds,
metres, radians and semicircle-derived radians as RTKLIB scales them).
Not a test and not run by pytest: pyrtklib is not a dependency of this
workspace. See README.md beside this file.
"""

import json
import sys

import pyrtklib as p

SYSTEMS = {1: "GPS", 2: "SBAS", 4: "GLONASS", 8: "Galileo", 16: "QZSS", 32: "BeiDou",
           64: "IRNSS"}
EPH = ("iode", "iodc", "sva", "svh", "week", "code", "flag", "fit", "toes", "A", "e", "i0",
       "OMG0", "omg", "M0", "deln", "OMGd", "idot", "crc", "crs", "cuc", "cus", "cic", "cis",
       "f0", "f1", "f2")
GEPH = ("iode", "frq", "svh", "sva", "age", "taun", "gamn", "dtaun")

def galileo_word(frame: bytes) -> tuple[int, int, bytes] | None:
    """(svId, word type, the 16-byte I/NAV word) of a Galileo UBX-RXM-SFRBX nominal page.

    RTKLIB's input_ubx gives no Galileo ephemeris for these frames (nor for
    a receiver's own), so the words are taken out here and given to its
    decode_gal_inav: UBX-13003221 10.5.1 for where the page parts are in
    the data words, the Galileo OS SIS ICD 2.2 Tables 37 to 39 for where data k
    and data j are in the parts. decode_gal_inav takes word type k at byte
    16k of its buffer (found by trial: it is not a documented interface).
    """
    if frame[2:4] != b"\x02\x13" or frame[6] != 2:
        return None
    payload = frame[6:-2]
    words = [int.from_bytes(payload[8 + 4 * i:12 + 4 * i], "little") for i in range(8)]
    even = (words[0] << 96 | words[1] << 64 | words[2] << 32 | words[3]) >> 8
    odd = (words[4] << 96 | words[5] << 64 | words[6] << 32 | words[7]) >> 8
    if even >> 118 & 1:   # alert page
        return None
    data_k = (even >> 6) & ((1 << 112) - 1)
    data_j = (odd >> 102) & 0xFFFF
    word = data_k << 16 | data_j
    return payload[1], word >> 122, word.to_bytes(16, "big")


raw = p.raw_t()
p.init_raw(raw, p.STRFMT_UBX)
prn = p.Arr1Dint(1)
gal: dict[int, dict[int, bytes]] = {}
out = []
for line in open(sys.argv[1]):
    frame = bytes.fromhex(line.strip())
    got = 0
    for b in frame:
        got = p.input_ubx(raw, b) or got
    record = None
    word = galileo_word(frame)
    if word is not None:
        sv, kind, data = word
        words = gal.setdefault(sv, {})
        words[kind] = data
        # decode_gal_inav returns 0 (no ephemeris) unless word types 0 to 6 are all present.
        if all(k in words for k in range(7)):
            buf = getattr(p, "Arr1Dunsigned char")(16 * 7)
            for k in range(7):
                for i, b in enumerate(words[k]):
                    buf[16 * k + i] = b
            e = p.eph_t()
            if p.decode_gal_inav(buf, e, p.Arr1Ddouble(4), p.Arr1Ddouble(8)):
                record = {"system": "Galileo", "prn": sv, "set": 0,
                          **{name: getattr(e, name) for name in EPH},
                          "toe": e.toe.time, "toc": e.toc.time,
                          "tgd": [e.tgd[i] for i in range(4)]}
            words.clear()
    if got == 2:
        sat = raw.ephsat
        system = SYSTEMS[p.satsys(sat, prn)]
        if system == "GLONASS":
            g = raw.nav.geph[prn[0] - 1]
            record = {name: getattr(g, name) for name in GEPH}
            record.update(toe=g.toe.time, tof=g.tof.time,
                          pos=[g.pos[i] for i in range(3)], vel=[g.vel[i] for i in range(3)],
                          acc=[g.acc[i] for i in range(3)])
        else:
            e = raw.nav.eph[sat - 1 + p.MAXSAT * raw.ephset]
            record = {name: getattr(e, name) for name in EPH}
            record.update(toe=e.toe.time, toc=e.toc.time, tgd=[e.tgd[i] for i in range(4)])
        record = {"system": system, "prn": prn[0], "set": raw.ephset, **record}
    out.append(frame.hex() + ("  " + json.dumps(record) if record else "") + "\n")
with open(sys.argv[2], "w") as f:
    f.writelines(out)
print(len(out), sum(1 for line in out if "  " in line))
