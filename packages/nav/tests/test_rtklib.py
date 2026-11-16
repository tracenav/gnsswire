"""Cross-check against RTKLIB: data/rtklib-decoded.txt (tests/make_data/README.md).

The frames are this project's: seeded synthetic ephemerides of GPS, Galileo,
BeiDou (D1 and D2) and GLONASS, encoded by gnsswire.nav into UBX-RXM-SFRBX.
After the frame that completed an ephemeris, the file holds what RTKLIB
decoded from the frames, in its own units. Here the same frames go through
gnsswire.ubx and gnsswire.nav.carriers, and every ephemeris our assemblers
yield must be RTKLIB's, field for field, once the integers are scaled by
the factors of the ICDs: IS-GPS-200N (with IRN-IS-200N-003 and IRN-IS-200N-004,
which change neither) Tables 20-I and 20-III, Galileo OS SIS
ICD 2.2 Tables 67, 70 and 72 (and its section 5.1.2, the GST start epoch,
for the week: GST week 0 begins with GPS week 1024), BDS-SIS-ICD-B1I-3.0
Tables 5-6, 5-7, 5-11 and section 5.2.4.9, GLONASS ICD 5.1 Table 4.5.
Semicircles are converted to radians as RTKLIB does (its pi is
3.1415926535898); the tolerance covers that and nothing more.

Not compared: RTKLIB's "fit" (hours, its reading), GPS "svh" and Galileo
"svh" and "code" (RTKLIB packs several of our fields into one), the
ephemeris times as calendar times (RTKLIB adds the week from its own clock;
toes, the time of week, is compared). RTKLIB moves a BeiDou ephemeris's
week by one when its toe and RTKLIB's clock (from UBX-RXM-RAWX) are more
than half a week apart, which the random toe here often is: that week is
compared to within one.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from gnsswire import ubx
from gnsswire.nav import beidou, carriers, galileo, glonass, gps

DATA = Path(__file__).parent / "data" / "rtklib-decoded.txt"
SC = 3.1415926535898   # RTKLIB's PI, semicircles to radians


def lines() -> list[tuple[bytes, dict | None]]:
    out = []
    for line in DATA.read_text().splitlines():
        hexpart, _, rest = line.partition("  ")
        out.append((bytes.fromhex(hexpart), json.loads(rest) if rest else None))
    return out


def ours_and_rtklib() -> dict[str, tuple[list, list]]:
    asm = carriers.Assembler()
    got: dict[str, tuple[list, list]] = {s: ([], []) for s in ("GPS", "Galileo", "BeiDou",
                                                               "GLONASS")}
    for data, record in lines():
        frame = ubx.parse(data, 0)
        assert isinstance(frame, ubx.Frame)
        message = ubx.decode(frame)
        if isinstance(message, ubx.RxmSfrbx):
            received = carriers.from_sfrbx(message)
            assert ubx.RxmSfrbx(**carriers.sfrbx_fields(received)) == message
            eph = asm.push(received)
            if eph is not None:
                system = {gps.Ephemeris: "GPS", galileo.InavEphemeris: "Galileo",
                          beidou.Ephemeris: "BeiDou", glonass.Ephemeris: "GLONASS"}[type(eph)]
                got[system][0].append((eph, message))
        if record is not None:
            got[record["system"]][1].append(record)
    return got


GOT = ours_and_rtklib()


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-300)


def kepler(eph, r: dict, *, harmonic: int, angle: int) -> None:
    """The Keplerian elements: GPS and Galileo scale the harmonic terms by 2^-29 rad and
    2^-5 m, BeiDou by 2^-31 rad and 2^-6 m; the rest are common."""
    assert close(r["A"], (eph.sqrt_a * 2**-19) ** 2)
    assert close(r["e"], eph.e * 2**-33)
    for ours, theirs in (("i0", "i0"), ("omega0", "OMG0"), ("omega", "omg"), ("m0", "M0")):
        assert close(r[theirs], getattr(eph, ours) * 2**-31 * SC), theirs
    for ours, theirs in (("delta_n", "deln"), ("omega_dot", "OMGd"), ("idot", "idot")):
        assert close(r[theirs], getattr(eph, ours) * 2**-43 * SC), theirs
    for name in ("cuc", "cus", "cic", "cis"):
        assert close(r[name], getattr(eph, name) * 2.0**-angle), name
    for name in ("crc", "crs"):
        assert close(r[name], getattr(eph, name) * 2.0**-harmonic), name


@pytest.mark.parametrize("system", ["GPS", "Galileo", "BeiDou", "GLONASS"])
def test_same_number_of_ephemerides(system):
    ours, theirs = GOT[system]
    assert len(ours) == len(theirs) > 0


def pairs(system: str):
    ours, theirs = GOT[system]
    return list(zip(ours, theirs, strict=True))


@pytest.mark.parametrize("pair", pairs("GPS"), ids=lambda p: f"G{p[0][0].satellite}")
def test_gps(pair):
    (eph, _), r = pair
    assert r["prn"] == eph.satellite
    assert (r["iode"], r["iodc"], r["sva"], r["code"], r["flag"]) == \
        (eph.iode, eph.iodc, eph.accuracy, eph.l2_code, eph.l2p_data)
    assert r["week"] % 1024 == eph.week
    assert r["toes"] == eph.toe * 16
    assert close(r["f0"], eph.af0 * 2**-31)
    assert close(r["f1"], eph.af1 * 2**-43)
    assert close(r["f2"], eph.af2 * 2**-55)
    assert close(r["tgd"][0], eph.tgd * 2**-31)
    kepler(eph, r, harmonic=5, angle=29)


@pytest.mark.parametrize("pair", pairs("Galileo"), ids=lambda p: f"E{p[0][0].satellite}")
def test_galileo(pair):
    (eph, _), r = pair
    assert r["prn"] == eph.satellite
    assert (r["iode"], r["sva"]) == (eph.iodnav, eph.sisa)
    assert r["week"] == eph.week + 1024   # RTKLIB counts GPS weeks; GST week 0 is GPS 1024
    assert r["toes"] == eph.toe * 60
    assert close(r["f0"], eph.af0 * 2**-34)
    assert close(r["f1"], eph.af1 * 2**-46)
    assert close(r["f2"], eph.af2 * 2**-59)
    assert close(r["tgd"][0], eph.bgd_e5a_e1 * 2**-32)
    assert close(r["tgd"][1], eph.bgd_e5b_e1 * 2**-32)
    kepler(eph, r, harmonic=5, angle=29)


@pytest.mark.parametrize("pair", pairs("BeiDou"), ids=lambda p: f"C{p[0][0].satellite}")
def test_beidou(pair):
    (eph, _), r = pair
    assert r["prn"] == eph.satellite
    assert (r["iode"], r["iodc"], r["sva"], r["svh"]) == (eph.aode, eph.aodc, eph.urai,
                                                          eph.health)
    assert abs(r["week"] - eph.week) <= 1
    assert r["toes"] == eph.toe * 8
    assert close(r["f0"], eph.a0 * 2**-33)
    assert close(r["f1"], eph.a1 * 2**-50)
    assert close(r["f2"], eph.a2 * 2**-66)
    assert close(r["tgd"][0], eph.tgd1 * 1e-10)
    assert close(r["tgd"][1], eph.tgd2 * 1e-10)
    kepler(eph, r, harmonic=6, angle=31)


@pytest.mark.parametrize("pair", pairs("GLONASS"), ids=lambda p: f"R{p[0][0].satellite}")
def test_glonass(pair):
    (eph, message), r = pair
    assert r["prn"] == eph.satellite
    assert r["frq"] == message.freq_id - 7
    assert (r["iode"], r["age"]) == (eph.tb, eph.en)
    for i, axis in enumerate("xyz"):
        assert close(r["pos"][i], getattr(eph, axis) * 2**-11 * 1e3)
        assert close(r["vel"][i], getattr(eph, axis + "_dot") * 2**-20 * 1e3)
        assert close(r["acc"][i], getattr(eph, axis + "_ddot") * 2**-30 * 1e3)
    assert close(r["taun"], eph.tau * 2**-30)
    assert close(r["gamn"], eph.gamma * 2**-40)
    assert close(r["dtaun"], eph.delta_tau * 2**-30)
