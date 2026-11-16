"""Step 1 of data/rtklib-decoded.txt: seeded synthetic navigation data in UBX-RXM-SFRBX frames.

usage: gen_frames.py OUT

Writes one UBX frame per line, as hex: first a UBX-RXM-RAWX without
measurements giving the receiver time (week 2400, a decoder needs a time to
resolve week numbers and GLONASS days), then for each system several
satellites' worth of one issue of ephemeris with random field values,
encoded by gnsswire.nav (tables, parity, BCH code, Hamming code, CRC) and
gnsswire.ubx (UBX-13003221 chapter 10 layouts, through
gnsswire.nav.carriers.to_sfrbx). The same seed gives the same file.
"""

from __future__ import annotations

import dataclasses
import random
import struct
import sys

from gnsswire import ubx
from gnsswire.bits import SM, S, U, layout
from gnsswire.nav import beidou, carriers, galileo, glonass, gps

WEEK = 2400
TOW = 345_600          # Thursday 00:00 GPS time
rng = random.Random(20261115)


def _none(name: str) -> int:
    raise KeyError(name)


def rand(cls: type, **fixed: int) -> object:
    """``cls`` with random values in every field not in ``fixed``."""
    values = {}
    for row in layout(cls).rows:
        if row.name in fixed:
            values[row.name] = fixed[row.name]
            continue
        kind = row.kind
        w = kind.width.eval(_none)
        n = None if kind.count is None else kind.count.eval(_none)

        def one() -> int:
            if isinstance(kind, U):
                return rng.getrandbits(w)
            if isinstance(kind, S):
                return rng.randrange(-(1 << (w - 1)), 1 << (w - 1))
            assert isinstance(kind, SM)
            return rng.randrange(-(1 << (w - 1)) + 1, 1 << (w - 1))
        values[row.name] = one() if n is None else tuple(one() for _ in range(n))
    return cls(**values)


def frame(message: object) -> str:
    return ubx.encode(message).hex()


out = [frame(ubx.RxmRawx(rcv_tow=struct.unpack(">Q", struct.pack(">d", float(TOW)))[0],
                         week=WEEK, leap_s=18, num_meas=0, rec_stat=1, version=1,
                         reserved0=(0, 0), meas=()))]


def sfrbx(system: str, sat: int, message: object, **kw: int) -> None:
    out.append(frame(ubx.RxmSfrbx(**carriers.to_sfrbx(system, sat, message, **kw))))


# GPS LNAV: subframes 1 to 3 of one issue (IODE = IODC LSBs), HOW TOW counts.
for sat in (3, 17, 30):
    iodc = rng.getrandbits(10)
    head = dict(preamble=gps.PREAMBLE, integrity=0, reserved_tlm=0, alert=0, anti_spoof=1)
    toe = rng.randrange(0, 1 << 16)
    tables = [
        rand(gps.Subframe1, **head, subframe=1, week=WEEK % 1024, iodc_msb=iodc >> 8,
             iodc_lsb=iodc & 0xFF, toc=toe, health=0),
        rand(gps.Subframe2, **head, subframe=2, iode=iodc & 0xFF, toe=toe, fit_interval=0),
        rand(gps.Subframe3, **head, subframe=3, iode=iodc & 0xFF),
    ]
    for k, sf in enumerate(tables):
        sf = dataclasses.replace(sf, tow=(TOW // 6 + k + 1))
        sfrbx(carriers.GPS, sat, gps.solve_t(sf))

# Galileo I/NAV: words 1 to 5 of one IODnav, as nominal E1-B pages.
for sat in (4, 11, 26):
    iodnav = rng.getrandbits(10)
    toe = rng.randrange(0, 10080)
    words = [
        rand(galileo.InavWord0, word_type=0, time=2, wn=(WEEK - 1024) & 0xFFF, tow=TOW),
        rand(galileo.InavWord1, word_type=1, iodnav=iodnav, toe=toe, reserved=0),
        rand(galileo.InavWord2, word_type=2, iodnav=iodnav, reserved=0),
        rand(galileo.InavWord3, word_type=3, iodnav=iodnav),
        rand(galileo.InavWord4, word_type=4, iodnav=iodnav, svid=sat, toc=toe, spare=0),
        rand(galileo.InavWord5, word_type=5, e5b_hs=0, e1b_hs=0, e5b_dvs=0, e1b_dvs=0,
             wn=(WEEK - 1024) & 0xFFF, tow=TOW + 10, spare=0),
        rand(galileo.InavWord6, word_type=6, tow=TOW + 12, spare=0),
    ]
    for w in words:
        sfrbx(carriers.GALILEO_INAV, sat, galileo.inav_page(w), sig_id=0)

# BeiDou D1 (MEO/IGSO) subframes 1 to 3 and D2 (GEO) pages 1 to 10 of subframe 1.
BDS_WEEK = WEEK - 1356
for sat in (8, 23):
    sow = TOW
    toe = rng.getrandbits(17)
    head = dict(preamble=beidou.PREAMBLE, rev=0)
    tables = [
        rand(beidou.D1Subframe1, **head, fraid=1, sow=sow, sat_h1=0, week=BDS_WEEK, toc=toe),
        rand(beidou.D1Subframe2, **head, fraid=2, sow=sow + 6, toe_msb=toe >> 15),
        rand(beidou.D1Subframe3, **head, fraid=3, sow=sow + 12, toe_lsb=toe & 0x7FFF, rev2=0),
    ]
    for sf in tables:
        sfrbx(carriers.BEIDOU_D1, sat, sf, sig_id=0)
for sat in (2,):
    toe = rng.getrandbits(17)
    for k in range(1, 11):
        cls = beidou.D2_PAGES[k]
        fixed = dict(preamble=beidou.PREAMBLE, rev=0, fraid=1, sow=TOW + 3 * (k - 1), pnum=k,
                     reserved=(0,) * 5)
        if k == 1:
            fixed.update(sat_h1=0, week=BDS_WEEK, toc=toe)
        if k == 7:
            fixed.update(toe=toe)
        sfrbx(carriers.BEIDOU_D2, sat, rand(cls, **fixed), sig_id=1)

# GLONASS strings 1 to 5 of one frame, Hamming code computed.
for slot, channel in ((5, 1), (14, -7), (21, 6)):
    tb = rng.randrange(1, 96)
    strings = [
        # tk: hours (5 bits), minutes (6 bits), 30-second flag (ICD 4.5, Table 4.5).
        rand(glonass.String1, idle=0, m=1, reserved=0, p1=0,
             tk=(tb * 15 // 60) << 7 | (tb * 15 % 60) << 1),
        rand(glonass.String2, idle=0, m=2, bn=0, tb=tb, reserved=0),
        rand(glonass.String3, idle=0, m=3, reserved=0, ln=0),
        rand(glonass.String4, idle=0, m=4, n=slot, reserved1=0, reserved2=0, nt=652, sat_type=1),
        rand(glonass.String5, idle=0, m=5, na=652, reserved=0, n4=8, ln=0),
    ]
    for s in strings:
        sfrbx(carriers.GLONASS, slot, glonass.with_hamming(dataclasses.replace(s, kx=0)),
              freq_id=channel + 7)

with open(sys.argv[1], "w") as f:
    f.writelines(line + "\n" for line in out)
print(len(out))
