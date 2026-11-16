"""SkyTraq message tables against AN0039 version 1.4.42.

- SPEC transcribes each field table (type and size per row, as printed) a
  second time, independently of _messages.py, and the tables must match it.
- Every example frame decodes to the "Example(hex)" column of its table,
  and encodes back to the same bytes.
- Generated messages of every table round-trip through bytes.
- data/rtklib-decoded.txt records what RTKLIB's SkyTraq decoder (an
  independent implementation) makes of seeded synthetic frames; the floats
  under our integer fields must be the same numbers (make_data/README.md).
"""

import dataclasses
import importlib.util
import json
import struct
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import skytraq
from gnsswire.skytraq import FieldError, Unsupported, layout
from gnsswire.skytraq._table import Group

HERE = Path(__file__).parent
DATA = HERE / "data"
# The example frames are kept once, in test_frame.py (pytest runs with
# --import-mode=importlib, so the module is loaded by path).
_spec = importlib.util.spec_from_file_location("skytraq_test_frame", HERE / "test_frame.py")
_frame_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_frame_tests)
FRAMES = _frame_tests.FRAMES


def f8(bits: int) -> float:
    return struct.unpack(">d", bits.to_bytes(8, "big"))[0]


def f4(bits: int) -> float:
    return struct.unpack(">f", bits.to_bytes(4, "big"))[0]


# (type, bytes, count) per row after the message ID, as the note prints them;
# "-" is a field printed without a type. Groups are their own entries.
SPEC = {
    skytraq.MeasTime: [("UINT8", 1, None), ("UINT16", 2, None), ("UINT32", 4, None),
                       ("UINT16", 2, None)],
    skytraq.RawMeas: [("UINT8", 1, None), ("UINT8", 1, None), (skytraq.RawMeasChannel, 23, "nmeas")],
    skytraq.RawMeasChannel: [("UINT8", 1, None), ("UINT8", 1, None), ("DPFP", 8, None),
                             ("DPFP", 8, None), ("SPFP", 4, None), ("UINT8", 1, None)],
    skytraq.GpsSubframe: [("UINT8", 1, None), ("UINT8", 1, None), ("BYTES3", 3, 10)],
    skytraq.GlonassString: [("UINT8", 1, None), ("UINT8", 1, None), ("UINT8", 1, 9)],
    skytraq.BeidouD1Subframe: [("UINT8", 1, None), ("UINT8", 1, None), ("UINT8", 1, 28)],
    skytraq.BeidouD2Subframe: [("UINT8", 1, None), ("UINT8", 1, None), ("UINT8", 1, 28)],
    skytraq.ExtRawMeas: [("UINT8", 1, None), ("UINT8", 1, None), ("UINT16", 2, None),
                         ("UINT32", 4, None), ("UINT16", 2, None), ("-1", 1, None),
                         ("-1", 1, None), ("UINT8", 1, None),
                         (skytraq.ExtRawMeasChannel, 31, "nmeas")],
    skytraq.ExtRawMeasChannel: [("-1", 1, None), ("UINT8", 1, None), ("-1", 1, None),
                                ("UINT8", 1, None), ("DPFP", 8, None), ("DPFP", 8, None),
                                ("SPFP", 4, None), ("-1", 1, None), ("-1", 1, None),
                                ("-1", 1, None), ("-2", 2, None), ("-2", 2, None)],
    skytraq.GeneralSubframe: [("UINT8", 1, None), ("UINT8", 1, None), ("UINT8", 1, None),
                              ("UINT8", 1, None), ("BYTES4", 4, "length")],
}
# Fixed payload lengths (message ID included) the note states.
PAYLOAD = {skytraq.MeasTime: 10, skytraq.GpsSubframe: 33, skytraq.GlonassString: 12,
           skytraq.BeidouD1Subframe: 31, skytraq.BeidouD2Subframe: 31}


@pytest.mark.parametrize("cls", list(SPEC), ids=lambda c: c.__name__)
def test_tables_are_the_note(cls):
    got = []
    for row in layout(cls).rows:
        k = row.kind
        got.append((k.cls if isinstance(k, Group) else k.type_name, k.size, k.count))
    assert got == SPEC[cls]


@pytest.mark.parametrize("cls", list(PAYLOAD), ids=lambda c: c.__name__)
def test_fixed_payload_lengths(cls):
    assert 1 + layout(cls).fixed_size == PAYLOAD[cls]


def test_registry():
    assert sorted(skytraq.MESSAGES) == [0xDC, 0xDD, 0xE0, 0xE1, 0xE2, 0xE3, 0xE5, 0xE6]
    assert set(SPEC) - {skytraq.RawMeasChannel, skytraq.ExtRawMeasChannel} == set(
        skytraq.MESSAGES.values())


def decoded(msg_id):
    return skytraq.decode(skytraq.parse(FRAMES[msg_id]))


@pytest.mark.parametrize("msg_id", sorted(FRAMES))
def test_examples_round_trip(msg_id):
    assert skytraq.encode(decoded(msg_id)) == FRAMES[msg_id]


def test_meas_time_example():
    assert decoded(0xDC) == skytraq.MeasTime(0x3D, 0x06ED, 0x0B0CBC40, 0x03E8)


def test_raw_meas_example():
    m = decoded(0xDD)
    assert (m.iod, m.nmeas, len(m.meas)) == (0x3D, 0x0F, 15)
    assert m.meas[0] == skytraq.RawMeasChannel(
        0x02, 0x2B, 0x417442DB7655FA29, 0xC0E2E402215A0000, 0x44208000, 0x07)
    assert f4(m.meas[0].doppler) == 642.0
    # Channel 11, SVID 13: no pseudorange, indicator 0x16 (bits 1, 2, 4).
    assert (m.meas[10].svid, m.meas[10].pseudorange, m.meas[10].indicator) == (0x0D, 0, 0x16)
    # The last channel, a GLONASS satellite (slot 18 + 64), no pseudorange.
    assert (m.meas[14].svid, m.meas[14].cn0, m.meas[14].pseudorange,
            m.meas[14].indicator) == (0x52, 0x1E, 0, 0x06)


def test_gps_subframe_example():
    assert decoded(0xE0) == skytraq.GpsSubframe(0x02, 0x05, (
        0x8B0BB4, 0x3F22B5, 0x4F31CF, 0x4EFD81, 0xFD4D00, 0xA10C98, 0x79E709, 0x08D5C5,
        0xF8ED03, 0xEBFFF4))
    # "The 8 preamble bits ... from the first byte of ... word 1": 10001011.
    assert decoded(0xE0).words[0] >> 16 == 0x8B


def test_glonass_string_example():
    assert decoded(0xE1) == skytraq.GlonassString(0x52, 0x0E, (
        0xB4, 0x05, 0xA9, 0xC3, 0x94, 0x17, 0x50, 0x04, 0x82))


def test_beidou_d1_subframe_example():
    assert decoded(0xE2) == skytraq.BeidouD1Subframe(0xCF, 0x01, tuple(bytes.fromhex(
        "E2404737 58000DA0 E100AC03 878E315B 53B412B2 C0025B04 6007AB81")))
    # "The 11 preamble bits": 11100010010, the BeiDou preamble.
    assert decoded(0xE2).data[0] << 3 | decoded(0xE2).data[1] >> 5 == 0b11100010010


def test_beidou_d2_subframe_example():
    assert decoded(0xE3) == skytraq.BeidouD2Subframe(0xCB, 0x01, tuple(bytes.fromhex(
        "E2404737 95A514C8 CAEACFA5 00155555 55555555 55555555 55555555")))


def test_ext_raw_meas_example():
    m = decoded(0xE5)
    assert (m.version, m.iod, m.week, m.tow, m.period, m.indicator, m.reserved1,
            m.nmeas) == (0x01, 0x0D, 0x077C, 0x06AC4080, 0x03E8, 0x00, 0x00, 0x11)
    assert m.meas[0] == skytraq.ExtRawMeasChannel(
        gnss_signal=0x00, svid=0x0D, freq_lock=0xE0, cn0=0x32, pseudorange=0x41B333998962C9BA,
        carrier=0x41B37F98FDADE000, doppler=0x45794000, pseudorange_stdev=0, carrier_stdev=0,
        doppler_stdev=0, indicator=0x4007, reserved2=0)
    assert f4(m.meas[0].doppler) == 3988.0
    assert len(m.meas) == 17
    # Channels 10 and 11 are GNSS type 1 (SBAS) with SVIDs 128 and 129, 12 to
    # 17 GNSS type 2 (GLONASS) with frequency IDs 3, 8 to 0xC.
    assert [(c.gnss_signal, c.svid) for c in m.meas[9:11]] == [(0x01, 0x80), (0x01, 0x81)]
    assert {c.gnss_signal for c in m.meas[11:]} == {0x02}
    assert [c.freq_lock & 0xF for c in m.meas[11:]] == [3, 8, 9, 0xA, 0xB, 0xC]


def test_general_subframe_example():
    # The frame's words; see _messages.py on how its table differs.
    assert decoded(0xE6) == skytraq.GeneralSubframe(0x01, 0x03, 0x1E, 0x08, (
        0x06FFFFFF, 0xFF000000, 0x12783589, 0xE24D8000, 0x86EE8000, 0x0000002A, 0xAAAA664E,
        0x753F4000))


# ---- generated messages -----------------------------------------------------

def _int(kind):
    return st.integers(kind.lo, kind.hi)


@st.composite
def messages(draw, cls):
    rows = layout(cls).rows
    counters = {r.kind.count for r in rows if isinstance(r.kind.count, str)}
    values = {}
    for row in rows:
        k = row.kind
        if row.field in counters:
            values[row.field] = draw(st.integers(0, 4))
        elif row.field == "version" and hasattr(cls, "VERSION"):
            values[row.field] = cls.VERSION
        elif k.count is None:
            values[row.field] = draw(_int(k))
        else:
            n = k.count if isinstance(k.count, int) else values[k.count]
            item = messages(k.cls) if isinstance(k, Group) else _int(k)
            values[row.field] = tuple(draw(st.lists(item, min_size=n, max_size=n)))
    return cls(**values)


@pytest.mark.parametrize("cls", list(skytraq.MESSAGES.values()), ids=lambda c: c.__name__)
@settings(max_examples=60, derandomize=True, deadline=None)
@given(data=st.data())
def test_generated_messages_round_trip(cls, data):
    message = data.draw(messages(cls))
    raw = skytraq.encode(message)
    frame = skytraq.parse(raw)
    assert (frame.msg_id, frame.length) == (cls.MSG_ID, len(raw))
    assert skytraq.decode(frame) == message


@settings(max_examples=200, derandomize=True)
@given(st.integers(0, 2**64 - 1), st.integers(0, 2**32 - 1))
def test_every_float_bit_pattern_is_kept(pr, doppler):
    # NaNs and infinities included: the bits are the value.
    channel = skytraq.ExtRawMeasChannel(0, 1, 0, 0, pr, pr, doppler, 0, 0, 0, 0, 0)
    message = skytraq.ExtRawMeas(1, 0, 0, 0, 1000, 0, 0, 1, (channel,))
    assert skytraq.decode(skytraq.parse(skytraq.encode(message))) == message


# ---- refusals ---------------------------------------------------------------

@pytest.mark.parametrize("msg_id", [0x01, 0x80, 0xDE, 0xDF, 0xE4, 0xE7, 0xE8, 0xFF])
def test_message_without_a_table(msg_id):
    with pytest.raises(Unsupported):
        skytraq.decode(skytraq.parse(skytraq.encode_frame(msg_id, b"\x01\x02")))


@pytest.mark.parametrize("msg_id", [0xE5, 0xE6])
@pytest.mark.parametrize("version", [0, 2, 0xFF])
def test_other_versions_are_unsupported(msg_id, version):
    raw = FRAMES[msg_id]
    frame = skytraq.parse(raw)
    body = bytes([version]) + frame.body[1:]
    with pytest.raises(Unsupported):
        skytraq.decode(skytraq.parse(skytraq.encode_frame(msg_id, body)))
    message = skytraq.decode(frame)
    with pytest.raises(FieldError):
        skytraq.encode(dataclasses.replace(message, version=version))


@pytest.mark.parametrize("msg_id", sorted(FRAMES))
def test_bodies_that_do_not_fit(msg_id):
    body = skytraq.parse(FRAMES[msg_id]).body
    for bad in (body[:-1], body + b"\0", b""):
        with pytest.raises(FieldError):
            skytraq.decode(skytraq.parse(skytraq.encode_frame(msg_id, bad)))


def test_encode_checks_values():
    good = decoded(0xDC)
    for field, value in (("iod", 256), ("iod", -1), ("week", 1 << 16), ("tow", 1 << 32),
                         ("period", True), ("period", 1.0)):
        with pytest.raises(FieldError):
            skytraq.encode(dataclasses.replace(good, **{field: value}))
    with pytest.raises(FieldError):   # nmeas and the channels disagree
        skytraq.encode(skytraq.RawMeas(1, 2, decoded(0xDD).meas[:1]))
    with pytest.raises(FieldError):   # a channel of the wrong kind
        skytraq.encode(skytraq.RawMeas(1, 1, decoded(0xE5).meas[:1]))
    with pytest.raises(TypeError):
        skytraq.encode(skytraq.RawMeasChannel(1, 1, 0, 0, 0, 0))
    with pytest.raises(TypeError):
        skytraq.encode(b"\xa0\xa1")


# ---- RTKLIB -----------------------------------------------------------------

def _rtklib_lines():
    for line in (DATA / "rtklib-decoded.txt").read_text().splitlines():
        raw, _, obs = line.partition("  ")
        yield bytes.fromhex(raw), json.loads(obs) if obs else []


def test_rtklib_decodes_the_same_numbers():
    measured = 0
    for raw, obs in _rtklib_lines():
        message = skytraq.decode(skytraq.parse(raw))
        assert skytraq.encode(message) == raw
        if not hasattr(message, "meas"):
            assert obs == []
            continue
        # RTKLIB keeps the channels in order, one observation each.
        assert len(obs) == len(message.meas) > 0
        for channel, (_system, _prn, _code, p, l, d, snr) in zip(message.meas, obs):
            assert (f8(channel.pseudorange), f8(channel.carrier), f4(channel.doppler)) == (p, l, d)
            assert snr == channel.cn0 * 1000   # RTKLIB's SNR unit is 0.001 dB-Hz
            measured += 1
    assert measured > 300
