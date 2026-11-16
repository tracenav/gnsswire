"""GGA and ZDA against the u-blox F9 HPG 1.51 Interface Description.

- Field tables: each table's rows are compared with a transcription of the
  spec's "Payload" table (section 2.7.5.1 GGA, 2.7.21.1 ZDA), and its length
  with the printed "Number of fields".
- Spec examples decode to the values the table's "Example" column prints.
- Public data: the GGA and ZDA sentences of gpsd's ZED-F9P regression log
  (data/gpsd-zed-f9p.nmea, BSD terms, see its header) decode and round-trip
  byte for byte.
- Round trip: ``decode(encode(m)) == m`` on generated messages and
  ``encode(decode(f)) == f`` on their frames.
- Cross-check: pynmeagps, a dev-only dependency used as an oracle through its
  public API, parses the same sentences to the same raw fields, and to typed
  values that agree with ours once the test converts them; sentences it
  builds decode here to the fields it holds (test_pynmeagps_*).
"""

import datetime
from dataclasses import fields
from pathlib import Path

import pynmeagps
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import nmea
from gnsswire.nmea import FieldError, Frame, Gga, Unsupported, Zda, spec_names

DATA = Path(__file__).resolve().parent / "data"
fast = settings(max_examples=200, derandomize=True, deadline=None)

# Field names and "Number of fields" as printed; "xx" stands for the address
# (field 0, "xxGGA"), cs and CRLF close every table.
SPEC = {
    Gga: ("2.7.5.1", 17, ["xx", "time", "lat", "NS", "lon", "EW", "quality", "numSV", "HDOP",
                          "alt", "altUnit", "sep", "sepUnit", "diffAge", "diffStation",
                          "cs", "CRLF"]),
    Zda: ("2.7.21.1", 9, ["xx", "time", "day", "month", "year", "ltzh", "ltzn", "cs", "CRLF"]),
}


def wire(sentence: str) -> bytes:
    return sentence.encode() + b"\r\n"


def decode(sentence: str):
    frame = nmea.parse(wire(sentence))
    assert isinstance(frame, Frame), frame
    return nmea.decode(frame)


def public_sentences() -> list[str]:
    text = (DATA / "gpsd-zed-f9p.nmea").read_text()
    return [line for line in text.splitlines() if line and not line.startswith("#")]


PUBLIC = public_sentences()


# --- tables ------------------------------------------------------------------------

@pytest.mark.parametrize("cls", SPEC)
def test_table_is_the_spec_table(cls):
    section, count, names = SPEC[cls]
    assert cls.SECTION == section
    assert cls.NUMBER_OF_FIELDS == count == len(names)
    assert spec_names(cls) + ["cs", "CRLF"] == names
    rows = fields(cls)
    assert rows[0].type is str and all(f.type == str | None for f in rows[1:-1])
    assert rows[-1].name == "extra" and rows[-1].default == ()
    assert nmea.MESSAGES[cls.FORMATTER] is cls


# --- spec examples -------------------------------------------------------------------

def test_gga_example():
    # Section 2.7.5.1 "Example"; diffAge and diffStation are null.
    assert decode("$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B") \
        == Gga("GP", "092725.00", "4717.11399", "N", "00833.91590", "E", "1", "08", "1.01",
               "499.6", "M", "48.0", "M", "", "")


@pytest.mark.parametrize(("sentence", "expected"), [
    ("$GPZDA,082710.00,16,09,2002,00,00*64",               # 2.7.21.1
     Zda("GP", "082710.00", "16", "09", "2002", "00", "00")),
    ("$GPZDA,141644.00,22,03,2002,00,00*67",               # 2.1, figure
     Zda("GP", "141644.00", "22", "03", "2002", "00", "00")),
])
def test_zda_examples(sentence, expected):
    assert decode(sentence) == expected


def test_secondary_output_example_after_its_tag_block():
    # Section 2.8.1.1 (NMEA-NAV2-GGA): the same sentence as 2.7.5.1 behind
    # "\s:1*78\". The block stays outside the frame (_frame),
    # and the caller can see it ends where the frame starts.
    stream = b"\\s:1*78\\" + wire(
        "$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B")
    [frame] = nmea.scan(stream)
    assert stream[frame.offset - 1:frame.offset] == b"\\"
    assert nmea.decode(frame) == decode(
        "$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B")


def test_fields_are_not_converted():
    m = decode("$GNGGA,,,,,,0,00,99.99,,,,,,*56")
    assert (m.time, m.quality, m.num_sv, m.hdop, m.alt) == ("", "0", "00", "99.99", "")
    m = decode("$GNGGA,004000.00,4552.65403,S,17030.00673,E,1,12,0.65,14.2,M,1.8,M,,*50")
    assert m.time == "004000.00" and m.lon == "17030.00673" and m.ns == "S"


# --- talkers and addresses -------------------------------------------------------------

@pytest.mark.parametrize("talker", ["GP", "GL", "GA", "GB", "GI", "GQ", "GN", "BD", "XY"])
def test_any_talker(talker):
    body = f"{talker}ZDA,082710.00,16,09,2002,00,00"
    m = nmea.decode(nmea.parse(nmea.encode_frame(body.encode())))
    assert m == Zda(talker, "082710.00", "16", "09", "2002", "00", "00")
    assert nmea.encode(m) == nmea.encode_frame(body.encode())


@pytest.mark.parametrize("body", [
    "PUBX,00",                               # proprietary (section 2.3)
    "PXGGA,,,,,,0,00,99.99,,,,,,",           # proprietary, AMBIGUOUS (_sentences)
    "G1GGA,,,,,,0,00,99.99,,,,,,",           # talker not two letters
    "GPGGAX,,,,,,0,00,99.99,,,,,,",
    "GGA,,,,,,0,00,99.99,,,,,,",
    "GPGSV,1,1,00,2",                        # no table
    "EIGAQ,RMC",
])
def test_unsupported(body):
    with pytest.raises(Unsupported):
        nmea.decode(nmea.parse(nmea.encode_frame(body.encode())))


@pytest.mark.parametrize("body", [
    "GPZDA,082710.00,16,09,2002,00",          # one short
    "GPZDA,082710.00,16,09,2002,00,00,",      # one extra, empty
    "GPZDA",
    "GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,",
])
def test_wrong_number_of_fields(body):
    # strict: only the table's own count. Lenient: kept, and round-trips.
    frame = nmea.parse(nmea.encode_frame(body.encode()))
    with pytest.raises(FieldError, match="data fields"):
        nmea.decode(frame, strict=True)
    m = nmea.decode(frame)
    assert nmea.encode(m) == nmea.encode(frame)
    assert nmea.decode(nmea.parse(nmea.encode(m))) == m


def test_missing_trailing_fields_are_none_and_extra_ones_kept():
    # The document's position fix flags section: before NMEA 2.3 some
    # sentences have "one field less"; later versions append fields. Absent
    # (None) is not null (""): both round-trip.
    short = decode("$GPZDA,082710.00,16,09,2002*64")
    assert short == Zda("GP", "082710.00", "16", "09", "2002", None, None)
    assert nmea.encode(short) == wire("$GPZDA,082710.00,16,09,2002*64")
    longer = nmea.decode(nmea.parse(nmea.encode_frame(b"GPZDA,082710.00,16,09,2002,00,00,,7")))
    assert (longer.ltzn, longer.extra) == ("00", ("", "7"))
    assert nmea.encode(longer) == nmea.encode_frame(b"GPZDA,082710.00,16,09,2002,00,00,,7")
    bare = nmea.decode(nmea.parse(nmea.encode_frame(b"GPGGA")))
    assert bare.time is None and bare.diff_station is None and bare.extra == ()
    assert nmea.encode(bare) == nmea.encode_frame(b"GPGGA")


@pytest.mark.parametrize("change", [
    {"month": None},                       # a field after an absent one
    {"ltzh": None, "ltzn": None, "extra": ("1",)},
    {"extra": ["1"]}, {"extra": (1,)}, {"extra": ("1,2",)},
])
def test_encode_refuses_what_no_sentence_decodes_to(change):
    m = Zda(**{f.name: getattr(ZDA, f.name) for f in fields(Zda)} | change)
    with pytest.raises(FieldError):
        nmea.encode(m)


# --- encode refuses what decode could not give back -------------------------------------

ZDA = Zda("GP", "082710.00", "16", "09", "2002", "00", "00")


@pytest.mark.parametrize("change", [
    {"talker": "gp"}, {"talker": "G"}, {"talker": "GPS"}, {"talker": "PU"}, {"talker": "G1"},
    {"day": "1,6"}, {"day": "1*"}, {"day": "$"}, {"day": "\r"}, {"day": "é"}, {"day": 16},
    {"year": "x" * nmea.MAX_LENGTH},
])
def test_encode_refuses(change):
    m = Zda(**{f.name: getattr(ZDA, f.name) for f in fields(Zda)} | change)
    with pytest.raises(FieldError):
        nmea.encode(m)


def test_encode_refuses_other_types():
    with pytest.raises(TypeError):
        nmea.encode(("GP", "ZDA"))


def test_encode_frame_passthrough():
    frame = nmea.parse(wire("$GPZDA,082710.00,16,09,2002,00,00*64"))
    assert nmea.encode(frame) == wire("$GPZDA,082710.00,16,09,2002,00,00*64")
    assert nmea.encode(nmea.decode(frame)) == nmea.encode(frame)


# --- public data -----------------------------------------------------------------------

def test_public_capture_round_trips():
    assert len(PUBLIC) == 58
    kinds = []
    for sentence in PUBLIC:
        frame = nmea.parse(wire(sentence))
        assert isinstance(frame, Frame), sentence
        m = nmea.decode(frame)
        kinds.append(type(m))
        assert m.talker == "GN"
        assert nmea.encode(m) == wire(sentence)
    assert kinds.count(Gga) == kinds.count(Zda) == 29


# --- generated round trip ------------------------------------------------------------------

FIELD_CHARS = "".join(chr(c) for c in range(0x20, 0x7F) if chr(c) not in "$*,")
talkers = st.from_regex(r"[A-OQ-Z][A-Z]", fullmatch=True)
values = st.text(FIELD_CHARS, max_size=12)


def messages(cls):
    return st.builds(cls, talkers, *[values] * (len(fields(cls)) - 2))


@fast
@given(st.one_of(messages(Gga), messages(Zda)))
def test_generated_round_trip(m):
    raw = nmea.encode(m)
    frame = nmea.parse(raw)
    assert isinstance(frame, Frame) and frame.length == len(raw)
    assert nmea.decode(frame) == m
    assert nmea.encode(nmea.decode(frame)) == raw


# --- cross-check against pynmeagps ----------------------------------------------------------

SPEC_EXAMPLES = [
    "$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B",
    "$GPZDA,082710.00,16,09,2002,00,00*64",
    "$GPZDA,141644.00,22,03,2002,00,00*67",
]


def _time(text: str) -> datetime.time:
    whole, _, frac = text.partition(".")
    return datetime.time(int(whole[:2]), int(whole[2:4]), int(whole[4:6]),
                         int((frac + "000000")[:6]))


def _degrees(text: str, degree_digits: int) -> float:
    return int(text[:degree_digits]) + float(text[degree_digits:]) / 60


# How the test turns our strings into the oracle's typed values. Fields not
# listed are compared as strings.
CONVERT = {
    "time": _time, "lat": lambda s: _degrees(s, 2), "lon": lambda s: _degrees(s, 3),
    "quality": int, "numSV": int, "HDOP": float, "alt": float, "sep": float,
    "diffAge": float, "diffStation": int, "day": int, "month": int, "year": int,
}


def _agrees(name: str, ours: str, theirs) -> bool:
    if ours == "":
        return theirs == ""
    convert = CONVERT.get(name, str)
    value = convert(ours)
    if isinstance(value, float):
        return abs(value - theirs) < 1e-9
    return value == theirs


@pytest.mark.parametrize("sentence", SPEC_EXAMPLES + PUBLIC)
def test_pynmeagps_agrees(sentence):
    _check_pynmeagps(sentence)


def _check_pynmeagps(sentence: str) -> None:
    theirs = pynmeagps.NMEAReader.parse(wire(sentence))
    ours = decode(sentence)
    names = spec_names(type(ours))
    values = [getattr(ours, f.name) for f in fields(ours)][:-1]   # without extra
    assert (theirs.talker, theirs.msgID) == (ours.talker, type(ours).FORMATTER)
    assert theirs.payload == values[1:]
    for name, value in zip(names[1:], values[1:]):
        expected = getattr(theirs, name)
        if name in ("lat", "lon") and expected != "":
            # pynmeagps signs the angle by hemisphere; the wire does not.
            hemisphere = ours.ns if name == "lat" else ours.ew
            expected = -expected if hemisphere in "SW" else expected
        assert _agrees(name, value, expected), (name, value, expected)


def test_pynmeagps_messages_decode_here():
    built = [
        pynmeagps.NMEAMessage("GN", "GGA", 0, time="004000.00", lat=-45.8775671667, NS="S",
                              lon=170.5001121667, EW="E", quality=1, numSV=12, HDOP=0.65,
                              alt=14.2, altUnit="M", sep=1.8, sepUnit="M"),
        pynmeagps.NMEAMessage("GA", "ZDA", 0, payload=["082710.00", "16", "09", "2002", "00", "00"]),
        pynmeagps.NMEAMessage("GB", "GGA", 0, payload=[""] * 5 + ["0", "00", "99.99"] + [""] * 6),
    ]
    for m in built:
        raw = m.serialize()
        ours = nmea.decode(nmea.parse(raw))
        assert ours.talker == m.talker and type(ours).FORMATTER == m.msgID
        assert [getattr(ours, f.name) for f in fields(ours)][1:-1] == m.payload
        assert nmea.encode(ours) == raw


# --- private captures ------------------------------------------------------------------------
#
# build/private/ (gitignored, never committed; see its README.txt) holds
# recorded receiver-side streams with GGA and ZDA interleaved with UBX and
# RTCM. When it is present, every GGA and ZDA in them must decode, re-encode
# to its own bytes and agree with pynmeagps. Nothing from these files is
# copied into the repository.

PRIVATE = Path(__file__).resolve().parents[3] / "build" / "private"
private = pytest.mark.skipif(not PRIVATE.is_dir(),
                             reason="private captures (build/private/) are absent")


@private
def test_private_captures_round_trip_and_agree_with_pynmeagps():
    counts = {Gga: 0, Zda: 0}
    failures = []
    for path in sorted(PRIVATE.glob("*.bin")):
        stream = path.read_bytes()
        for frame in nmea.scan(stream):
            raw = stream[frame.offset:frame.offset + frame.length]
            try:
                m = nmea.decode(frame)
            except Unsupported:
                continue
            except FieldError as exc:
                failures.append((path.name, frame.offset, str(exc)))
                continue
            counts[type(m)] += 1
            if nmea.encode(m) != raw:
                failures.append((path.name, frame.offset, "round trip"))
                continue
            try:
                _check_pynmeagps(raw[:-2].decode("ascii"))
            except AssertionError as exc:
                failures.append((path.name, frame.offset, f"pynmeagps: {exc}"))
    assert not failures, failures[:10]
    assert counts[Gga] > 0 and counts[Zda] > 0
