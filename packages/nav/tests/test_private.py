"""Local recordings: assembled ephemerides against the RTCM ephemerides of the same session.

build/private/ (gitignored, never committed; see its README.txt) may hold,
for one receiver session, ``<name>_sfrbx.bin`` (UBX-RXM-SFRBX among other
messages) and ``<name>_rinex.bin`` (the RTCM 1019, 1020, 1042, 1045/1046 the
session's ephemeris source sent). When both are present, every frame of the
first must decode and round-trip through gnsswire.nav.carriers, and every
ephemeris assembled from it that has an RTCM message of the same satellite
and issue (GPS: IODE and toe; Galileo: IODnav; BeiDou: toe and AODE;
GLONASS: tb and tk) must be that message, field for field, through
``rtcm_fields``. The test skips, naming what is missing, without them.

The RTCM producer is a black box, and some 1019 and 1020 fields are not
taken from the broadcast by it: a field in ``FILLED`` is compared only when
the recording's messages do not hold one value for it throughout (a field
that never varies across all satellites and issues carries a fill, not the
broadcast). GLONASS string 5 fields (NA, tau_c, N4, tau_GPS, the ln of
string 5) are not compared: string 5 is repeated in every frame and is not
part of a satellite's immediate data, so a producer may take any frame's.
At most one pair in twenty of a message type may differ, and then in one
field only: the producer is a black box, and an occasional difference in a
single field is tolerated.
"""

from __future__ import annotations

import collections
import dataclasses
from pathlib import Path

import pytest

from gnsswire import rtcm3, ubx
from gnsswire.nav import beidou, carriers, galileo, glonass, gps

PRIVATE = Path(__file__).resolve().parents[3] / "build" / "private"
FILLED = {1019: {"accuracy", "l2_code", "fit_interval"},
          1020: {"p", "p3", "p4", "ln_third", "delta_tau", "ft", "m", "almanac_health",
                 "almanac_health_available"}}
NOT_COMPARED = {1020: {"na", "tau_c", "n4", "tau_gps", "ln_fifth"}}


def sessions() -> list[tuple[Path, Path]]:
    if not PRIVATE.is_dir():
        return []
    return [(s, s.with_name(s.name.replace("_sfrbx.bin", "_rinex.bin")))
            for s in sorted(PRIVATE.glob("*_sfrbx.bin"))
            if s.with_name(s.name.replace("_sfrbx.bin", "_rinex.bin")).is_file()]


def key(fields: dict) -> tuple:
    n = fields["number"]
    if n == 1019:
        return n, fields["satellite"], fields["iode"], fields["toe"]
    if n == 1020:
        return n, fields["satellite"], fields["tb"], fields["tk"]
    if n == 1042:
        return n, fields["satellite"], fields["toe"], fields["aode"]
    return n, fields["satellite"], fields["iodnav"]


def rtcm_of(eph, message) -> dict:
    if isinstance(eph, gps.Ephemeris):
        return gps.rtcm_fields(eph)
    if isinstance(eph, galileo.InavEphemeris):
        return galileo.rtcm_fields(eph)
    if isinstance(eph, beidou.Ephemeris):
        return beidou.rtcm_fields(eph)
    return glonass.rtcm_fields(eph, channel=message.freq_id)


@pytest.mark.skipif(not PRIVATE.is_dir(), reason="private captures (build/private/) are absent")
def test_private_ephemerides_equal_the_sessions_rtcm():
    pairs = sessions()
    if not pairs:
        pytest.skip("no <name>_sfrbx.bin with a paired <name>_rinex.bin in build/private/")
    for sfrbx_path, rtcm_path in pairs:
        reference: dict[tuple, list[dict]] = collections.defaultdict(list)
        values: dict[tuple[int, str], set] = collections.defaultdict(set)
        for frame in rtcm3.scan(rtcm_path.read_bytes()):
            msg = rtcm3.decode(frame)
            if type(msg).__name__ in ("Msg1019", "Msg1020", "Msg1042", "Msg1046"):
                fields = {f.name: getattr(msg, f.name) for f in dataclasses.fields(msg)
                          if f.name != "extension"}
                if fields not in reference[key(fields)]:   # repeated every 30 s
                    reference[key(fields)].append(fields)
                for name, value in fields.items():
                    values[fields["number"], name].add(value)
        asm = carriers.Assembler()
        compared = collections.Counter()
        differ: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
        for frame in ubx.scan(sfrbx_path.read_bytes()):
            msg = ubx.decode(frame)
            if not isinstance(msg, ubx.RxmSfrbx):
                continue
            received = carriers.from_sfrbx(msg)
            assert ubx.RxmSfrbx(**carriers.sfrbx_fields(received)) == msg
            eph = asm.push(received)
            if eph is None:
                continue
            ours = rtcm_of(eph, msg)
            number = ours["number"]
            for theirs in reference.get(key(ours), []):
                skip = NOT_COMPARED.get(number, set()) | {
                    name for name in FILLED.get(number, ()) if len(values[number, name]) == 1}
                bad = sorted(name for name in theirs
                             if name not in skip and theirs[name] != ours[name])
                compared[number] += 1
                for name in bad:
                    differ[number][name] += 1
                if bad:
                    differ[number]["(pairs)"] += 1
        name = sfrbx_path.name
        assert set(compared) == {1019, 1020, 1042, 1046}, (name, dict(compared))
        for number, count in compared.items():
            bad = differ[number]
            assert bad["(pairs)"] * 20 <= count, (name, number, count, dict(bad))
            assert all(n <= 1 for field, n in bad.items() if field != "(pairs)"), \
                (name, number, dict(bad))
