"""UBX messages against u-blox F9 HPG 1.51 Interface Description.

- Field tables: each table's rows, types and byte offsets are compared with a
  transcription of the spec's "Payload description" (section 3.15.26.1
  NAV-TIMELS, 3.17.3.1 RXM-PMP, 3.17.6.1 RXM-RAWX, 3.17.9.1 RXM-SFRBX), and
  the payload length with the "Length (Bytes)" of the message structure.
- Hand-built frames: payloads packed with ``struct`` from the spec's offsets,
  independently of the table interpreter, decode to the values put in.
- Round trip: ``decode(encode(m)) == m`` on generated messages and
  ``encode(decode(f)) == f`` on their frames.
- Cross-check: pyubx2, a dev-only dependency used as an oracle through its
  public API, decodes our frames to the same fields, and frames it builds
  decode here to the fields it was given (test_pyubx2_*).

RXM-PMP version 0 is from the u-blox D9 PMP 1.04 Interface Description,
section 2.13.1.1, and checked the same way.

The u-blox X20 HPG 2.11 Interface Description (UBXDOC-304424225-21617 R01)
prints the other four tables with the same rows, types and offsets, so the
transcriptions below are its sections 3.14.22.1, 3.16.3.1, 3.16.6.1 and
3.16.8.1 as well.

No public capture holding these messages was at hand, so the
frames here are built from the spec or by pyubx2. Private captures, when
present in build/private/, are checked at the end of this file
(test_private_*); they skip without it.
"""

import struct
from pathlib import Path

import pytest
import pyubx2
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire import ubx
from gnsswire.ubx import (
    FieldError,
    NavTimels,
    RxmPmp,
    RxmPmpV0,
    RxmRawx,
    RxmRawxMeas,
    RxmSfrbx,
    Unsupported,
)
from gnsswire.ubx._table import Bytes, Group

# (offset, type, spec name) as printed; "n" marks a repeated group's first offset.
SPEC = {
    NavTimels: [  # section 3.15.26.1, length 24
        (0, "U4", "iTOW"), (4, "U1", "version"), (5, "U1[3]", "reserved0"),
        (8, "U1", "srcOfCurrLs"), (9, "I1", "currLs"), (10, "U1", "srcOfLsChange"),
        (11, "I1", "lsChange"), (12, "I4", "timeToLsEvent"), (16, "U2", "dateOfLsGpsWn"),
        (18, "U2", "dateOfLsGpsDn"), (20, "U1[3]", "reserved1"), (23, "X1", "valid"),
    ],
    RxmPmp: [  # section 3.17.3.1, length 24 + [0..n]
        (0, "U1", "version"), (1, "U1", "reserved0"), (2, "U2", "numBytesUserData"),
        (4, "U4", "timeTag"), (8, "U4[2]", "uniqueWord"), (16, "U2", "serviceIdentifier"),
        (18, "U1", "spare"), (19, "U1", "uniqueWordBitErrors"), (20, "U2", "fecBits"),
        (22, "U1", "ebno"), (23, "U1", "reserved1"), (24, "U1 n", "userData"),
    ],
    RxmPmpV0: [  # D9 PMP 1.04 section 2.13.1.1, length 528
        (0, "U1", "version"), (1, "U1[3]", "reserved0"), (4, "U4", "timeTag"),
        (8, "U4[2]", "uniqueWord"), (16, "U2", "serviceIdentifier"), (18, "U1", "spare"),
        (19, "U1", "uniqueWordBitErrors"), (20, "U1[504]", "userData"), (524, "U2", "fecBits"),
        (526, "U1", "ebno"), (527, "U1", "reserved1"),
    ],
    RxmSfrbx: [  # section 3.17.9.1, length 8 + numWords·4
        (0, "U1", "gnssId"), (1, "U1", "svId"), (2, "U1", "sigId"), (3, "U1", "freqId"),
        (4, "U1", "numWords"), (5, "U1", "chn"), (6, "U1", "version"), (7, "U1", "reserved0"),
        (8, "U4 n", "dwrd"),
    ],
    RxmRawx: [  # section 3.17.6.1, length 16 + numMeas·32
        (0, "R8", "rcvTow"), (8, "U2", "week"), (10, "I1", "leapS"), (11, "U1", "numMeas"),
        (12, "X1", "recStat"), (13, "U1", "version"), (14, "U1[2]", "reserved0"),
        (16, "group n", "prMes"),
    ],
}
# The repeated group of RXM-RAWX, offsets as printed less 16 + n·32.
SPEC_GROUP = {
    RxmRawxMeas: [
        (0, "R8", "prMes"), (8, "R8", "cpMes"), (16, "R4", "doMes"), (20, "U1", "gnssId"),
        (21, "U1", "svId"), (22, "U1", "sigId"), (23, "U1", "freqId"), (24, "U2", "locktime"),
        (26, "U1", "cno"), (27, "X1", "prStdev"), (28, "X1", "cpStdev"), (29, "X1", "doStdev"),
        (30, "X1", "trkStat"), (31, "U1", "reserved1"),
    ],
}
CLASS_ID = {NavTimels: (0x01, 0x26), RxmPmp: (0x02, 0x72), RxmPmpV0: (0x02, 0x72),
            RxmSfrbx: (0x02, 0x13), RxmRawx: (0x02, 0x15)}
VERSION_AT = {NavTimels: (4, 0), RxmPmp: (0, 1), RxmPmpV0: (0, 0), RxmSfrbx: (6, 2),
              RxmRawx: (13, 1)}


def _printed_type(kind) -> str:
    if isinstance(kind, Group):
        return f"group[{kind.count}]" if isinstance(kind.count, int) else "group n"
    if isinstance(kind, Bytes):
        return f"U1[{kind.length}]" if isinstance(kind.length, int) else "U1 n"
    name = type(kind).__name__
    if kind.count is None:
        return name
    return f"{name}[{kind.count}]" if isinstance(kind.count, int) else f"{name} n"


@pytest.mark.parametrize("cls", list(SPEC))
def test_tables_are_the_spec_tables(cls):
    lay = ubx.layout(cls)
    assert [(_printed_type(r.kind), r.kind.name) for r in lay.rows] == [
        (t, n) for _, t, n in SPEC[cls]]
    fields = [r.field for r in lay.rows]
    for (offset, _, _), field in zip(SPEC[cls], fields):
        assert lay.offsets[field] == offset, field
    assert (cls.MSG_CLASS, cls.MSG_ID) == CLASS_ID[cls]
    assert lay.offsets["version"] == VERSION_AT[cls][0]
    assert ubx.MESSAGES[(*CLASS_ID[cls], VERSION_AT[cls][1])] is cls


@pytest.mark.parametrize("cls", list(SPEC_GROUP))
def test_groups_are_the_spec_groups(cls):
    lay = ubx.layout(cls)
    assert [(_printed_type(r.kind), r.kind.name) for r in lay.rows] == [
        (t, n) for _, t, n in SPEC_GROUP[cls]]
    for (offset, _, _), row in zip(SPEC_GROUP[cls], lay.rows):
        assert lay.offsets[row.field] == offset, row.field
    assert lay.fixed_size == 32
    assert ubx.layout(RxmRawx).rows[-1].kind.cls is cls


def test_spec_lengths():
    assert ubx.layout(NavTimels).fixed_size == 24
    assert ubx.layout(RxmPmp).fixed_size is None
    assert ubx.layout(RxmSfrbx).fixed_size is None
    assert ubx.layout(RxmPmpV0).fixed_size == 528
    assert len(ubx.encode(pmp0())) == 8 + 528
    for n in (0, 1, 504):
        assert len(ubx.encode(pmp(user_data=bytes(n)))) == 8 + 24 + n
    for n in (0, 1, 10):
        assert len(ubx.encode(sfrbx(dwrd=tuple(range(n))))) == 8 + 8 + 4 * n
    assert ubx.layout(RxmRawx).fixed_size is None
    for n in (0, 1, 7):
        assert len(ubx.encode(rawx(meas=(meas(),) * n))) == 8 + 16 + 32 * n


def test_fields_are_naturally_aligned():
    # Section 3.3.1: two-byte values at even offsets, four-byte at multiples of
    # four, "and so on" (R8 at multiples of eight). A group starts at a multiple
    # of eight and repeats every 32 bytes, so its fields keep their alignment.
    for cls in [*SPEC, *SPEC_GROUP]:
        lay = ubx.layout(cls)
        for row in lay.rows:
            if not isinstance(row.kind, (Bytes, Group)):
                assert lay.offsets[row.field] % row.kind.size == 0, (cls, row.field)
            if isinstance(row.kind, Group):
                assert lay.offsets[row.field] % 8 == 0 and row.kind.size % 8 == 0


# --- builders --------------------------------------------------------------------------

def timels(**kw) -> NavTimels:
    base = dict(itow=0, version=0, reserved0=(0, 0, 0), src_of_curr_ls=0, curr_ls=0,
                src_of_ls_change=0, ls_change=0, time_to_ls_event=0, date_of_ls_gps_wn=0,
                date_of_ls_gps_dn=0, reserved1=(0, 0, 0), valid=0)
    return NavTimels(**(base | kw))


def pmp(**kw) -> RxmPmp:
    data = kw.pop("user_data", b"")
    base = dict(version=1, reserved0=0, num_bytes_user_data=len(data), time_tag=0,
                unique_word=(0, 0), service_identifier=0, spare=0, unique_word_bit_errors=0,
                fec_bits=0, ebno=0, reserved1=0, user_data=data)
    return RxmPmp(**(base | kw))


def pmp0(**kw) -> RxmPmpV0:
    base = dict(version=0, reserved0=(0, 0, 0), time_tag=0, unique_word=(0, 0),
                service_identifier=0, spare=0, unique_word_bit_errors=0, user_data=bytes(504),
                fec_bits=0, ebno=0, reserved1=0)
    return RxmPmpV0(**(base | kw))


def sfrbx(**kw) -> RxmSfrbx:
    words = kw.pop("dwrd", ())
    base = dict(gnss_id=0, sv_id=0, sig_id=0, freq_id=0, num_words=len(words), chn=0,
                version=2, reserved0=0, dwrd=words)
    return RxmSfrbx(**(base | kw))


def r8(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def r4(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


def meas(**kw) -> RxmRawxMeas:
    base = dict(pr_mes=0, cp_mes=0, do_mes=0, gnss_id=0, sv_id=0, sig_id=0, freq_id=0,
                locktime=0, cno=0, pr_stdev=0, cp_stdev=0, do_stdev=0, trk_stat=0, reserved1=0)
    return RxmRawxMeas(**(base | kw))


def rawx(**kw) -> RxmRawx:
    group = kw.pop("meas", ())
    base = dict(rcv_tow=0, week=0, leap_s=0, num_meas=len(group), rec_stat=0, version=1,
                reserved0=(0, 0), meas=group)
    return RxmRawx(**(base | kw))


# --- hand-built frames -------------------------------------------------------------------

def test_hand_built_timels():
    # A scheduled positive leap second, GPS as source, 18 s now; offsets of 3.15.26.1.
    payload = struct.pack("<IB3sBbBbiHH3sB", 345_600_000, 0, b"\0\0\0", 2, 18, 2, 1,
                          86_400, 2_400, 7, b"\0\0\0", 0b11)
    assert len(payload) == 24
    frame = ubx.parse(ubx.encode_frame(0x01, 0x26, payload))
    assert ubx.decode(frame) == timels(
        itow=345_600_000, src_of_curr_ls=2, curr_ls=18, src_of_ls_change=2, ls_change=1,
        time_to_ls_event=86_400, date_of_ls_gps_wn=2_400, date_of_ls_gps_dn=7, valid=3)


def test_negative_values_are_twos_complement():
    payload = struct.pack("<IB3sBbBbiHH3sB", 0, 0, b"\0\0\0", 255, -1, 0, -1, -1, 0, 0,
                          b"\0\0\0", 0xFC)
    message = ubx.decode(ubx.parse(ubx.encode_frame(0x01, 0x26, payload)))
    assert (message.curr_ls, message.ls_change, message.time_to_ls_event) == (-1, -1, -1)
    assert message.valid == 0xFC   # reserved bits kept
    assert ubx.encode(message)[6:-2] == payload


def test_hand_built_pmp():
    data = bytes(range(7))
    payload = struct.pack("<BBHIIIHBBHBB", 1, 0, len(data), 123_456, 0xB9A6_A8E3, 0x1234_5678,
                          0x2C5B, 3, 1, 17, 80, 0) + data
    message = ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x72, payload)))
    assert message == pmp(time_tag=123_456, unique_word=(0xB9A6_A8E3, 0x1234_5678),
                          service_identifier=0x2C5B, spare=3, unique_word_bit_errors=1,
                          fec_bits=17, ebno=80, user_data=data)
    assert ubx.encode(message)[6:-2] == payload


def test_hand_built_pmp_version_0():
    # D9 PMP 1.04 section 2.13.1.1: userData sits between the bit errors and fecBits.
    data = bytes(i % 251 for i in range(504))
    payload = (struct.pack("<B3sIIIHBB", 0, b"\x01\x02\x03", 98_765, 0xB9A6_A8E3, 0x0102_0304,
                           0x2C5B, 7, 2) + data + struct.pack("<HBB", 513, 81, 9))
    assert len(payload) == 528
    message = ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x72, payload)))
    assert message == pmp0(reserved0=(1, 2, 3), time_tag=98_765,
                           unique_word=(0xB9A6_A8E3, 0x0102_0304), service_identifier=0x2C5B,
                           spare=7, unique_word_bit_errors=2, user_data=data, fec_bits=513,
                           ebno=81, reserved1=9)
    assert ubx.encode(message)[6:-2] == payload


def test_hand_built_sfrbx():
    words = (0x22C0_0E40, 0x0D7A_0BB0, 0xFFFF_FFFF, 0)
    payload = struct.pack("<8B4I", 6, 4, 0, 9, 4, 11, 2, 0, *words)
    message = ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x13, payload)))
    assert message == sfrbx(gnss_id=6, sv_id=4, freq_id=9, chn=11, dwrd=words)
    assert ubx.encode(message)[6:-2] == payload


@pytest.mark.parametrize("n", [10, 16, 17])
def test_sfrbx_word_count_is_not_bounded(n):
    # F9 HPG 1.51 section 3.17.9.1 (and X20 HPG 2.11) give numWords "up to 16,
    # for currently supported signals", F9 HPG 1.32 "up to 10": a range for
    # today's signals, not a width, so 10, 16 and more all decode.
    words = tuple(range(n))
    payload = struct.pack(f"<8B{n}I", 2, 1, 8, 0, n, 5, 2, 0, *words)
    message = ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x13, payload)))
    assert message == sfrbx(gnss_id=2, sv_id=1, sig_id=8, chn=5, num_words=n, dwrd=words)
    assert ubx.encode(message)[6:-2] == payload


def test_hand_built_rawx():
    # Two measurements, GPS L1C/A and GLONASS L1OF (freqId 7 + slot), at the
    # offsets of section 3.17.6.1; R8 and R4 values come back as their bits.
    head = struct.pack("<dHbBBB2s", 345_600.0071, 2_400, 18, 2, 0b01, 1, b"\0\0")
    one = struct.pack("<ddfBBBBHBBBBBB", 21_456_789.123, 112_754_321.25, -1_234.5,
                      0, 12, 0, 0, 64_500, 47, 4, 3, 2, 0b0111, 0)
    two = struct.pack("<ddfBBBBHBBBBBB", 19_876_543.0, -0.0, 3_000.25,
                      6, 3, 0, 10, 1_200, 33, 8, 15, 5, 0b0001, 0)
    payload = head + one + two
    assert len(payload) == 16 + 2 * 32
    message = ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x15, payload)))
    assert message == rawx(
        rcv_tow=r8(345_600.0071), week=2_400, leap_s=18, rec_stat=1,
        meas=(meas(pr_mes=r8(21_456_789.123), cp_mes=r8(112_754_321.25), do_mes=r4(-1_234.5),
                   sv_id=12, locktime=64_500, cno=47, pr_stdev=4, cp_stdev=3, do_stdev=2,
                   trk_stat=7),
              meas(pr_mes=r8(19_876_543.0), cp_mes=1 << 63, do_mes=r4(3_000.25), gnss_id=6,
                   sv_id=3, freq_id=10, locktime=1_200, cno=33, pr_stdev=8, cp_stdev=15,
                   do_stdev=5, trk_stat=1)))
    assert ubx.encode(message)[6:-2] == payload


def test_rawx_keeps_every_float_bit_pattern():
    # NaNs with payloads, infinities, subnormals and negative zero survive the
    # round trip, because R4 and R8 stay integers.
    patterns = [0x7FF8_0000_0000_0001, 0xFFF0_0000_0000_0000, 1, 1 << 63, (1 << 64) - 1]
    group = tuple(meas(pr_mes=p, cp_mes=p ^ 1, do_mes=p & 0xFFFF_FFFF) for p in patterns)
    message = rawx(rcv_tow=0x7FF4_0000_0000_0000, meas=group)
    raw = ubx.encode(message)
    assert ubx.decode(ubx.parse(raw)) == message
    assert ubx.encode(ubx.decode(ubx.parse(raw))) == raw


# --- generated messages ------------------------------------------------------------------

u1, i1 = st.integers(0, 0xFF), st.integers(-0x80, 0x7F)
u2, u4, i4 = st.integers(0, 0xFFFF), st.integers(0, 0xFFFF_FFFF), st.integers(-2**31, 2**31 - 1)
three = st.tuples(u1, u1, u1)

timels_messages = st.builds(
    NavTimels, itow=u4, version=st.just(0), reserved0=three, src_of_curr_ls=u1, curr_ls=i1,
    src_of_ls_change=u1, ls_change=i1, time_to_ls_event=i4, date_of_ls_gps_wn=u2,
    date_of_ls_gps_dn=u2, reserved1=three, valid=u1)
pmp_messages = st.binary(max_size=600).flatmap(lambda d: st.builds(
    RxmPmp, version=st.just(1), reserved0=u1, num_bytes_user_data=st.just(len(d)),
    time_tag=u4, unique_word=st.tuples(u4, u4), service_identifier=u2, spare=u1,
    unique_word_bit_errors=u1, fec_bits=u2, ebno=u1, reserved1=u1, user_data=st.just(d)))
pmp0_messages = st.builds(
    RxmPmpV0, version=st.just(0), reserved0=three, time_tag=u4, unique_word=st.tuples(u4, u4),
    service_identifier=u2, spare=u1, unique_word_bit_errors=u1,
    user_data=st.binary(min_size=504, max_size=504), fec_bits=u2, ebno=u1, reserved1=u1)
sfrbx_messages = st.lists(u4, max_size=20).flatmap(lambda w: st.builds(
    RxmSfrbx, gnss_id=u1, sv_id=u1, sig_id=u1, freq_id=u1, num_words=st.just(len(w)), chn=u1,
    version=st.just(2), reserved0=u1, dwrd=st.just(tuple(w))))
# Numbers, not NaNs, so that the pyubx2 cross-check below can compare them;
# every bit pattern is covered by test_generated_frames_round_trip.
r8s = st.floats(allow_nan=False).map(r8)
r4s = st.floats(width=32, allow_nan=False).map(r4)
meas_groups = st.builds(
    RxmRawxMeas, pr_mes=r8s, cp_mes=r8s, do_mes=r4s, gnss_id=u1, sv_id=u1, sig_id=u1,
    freq_id=u1, locktime=u2, cno=u1, pr_stdev=u1, cp_stdev=u1, do_stdev=u1, trk_stat=u1,
    reserved1=u1)
rawx_messages = st.lists(meas_groups, max_size=12).flatmap(lambda g: st.builds(
    RxmRawx, rcv_tow=r8s, week=u2, leap_s=i1, num_meas=st.just(len(g)), rec_stat=u1,
    version=st.just(1), reserved0=st.tuples(u1, u1), meas=st.just(tuple(g))))
messages = st.one_of(timels_messages, pmp_messages, pmp0_messages, sfrbx_messages,
                     rawx_messages)

often = settings(max_examples=300, derandomize=True, deadline=None)


@often
@given(messages)
def test_generated_messages_round_trip(message):
    raw = ubx.encode(message)
    frame = ubx.parse(raw)
    assert isinstance(frame, ubx.Frame)
    assert (frame.msg_class, frame.msg_id) == (message.MSG_CLASS, message.MSG_ID)
    assert ubx.decode(frame) == message
    assert ubx.encode(ubx.decode(frame)) == raw


@often
@given(st.data())
def test_generated_frames_round_trip(data):
    cls = data.draw(st.sampled_from(list(SPEC)))
    version = VERSION_AT[cls]
    if cls is NavTimels:
        payload = bytearray(data.draw(st.binary(min_size=24, max_size=24)))
    elif cls is RxmPmpV0:
        payload = bytearray(data.draw(st.binary(min_size=528, max_size=528)))
    elif cls is RxmPmp:
        n = data.draw(st.integers(0, 600))
        payload = bytearray(data.draw(st.binary(min_size=24, max_size=24)) + bytes(n))
        payload[2:4] = n.to_bytes(2, "little")
        payload[24:] = data.draw(st.binary(min_size=n, max_size=n))
    elif cls is RxmRawx:   # any bytes, so every R4 and R8 bit pattern
        n = data.draw(st.integers(0, 20))
        payload = bytearray(data.draw(st.binary(min_size=16 + 32 * n, max_size=16 + 32 * n)))
        payload[11] = n
    else:
        n = data.draw(st.integers(0, 20))
        payload = bytearray(data.draw(st.binary(min_size=8 + 4 * n, max_size=8 + 4 * n)))
        payload[4] = n
    payload[version[0]] = version[1]
    raw = ubx.encode_frame(*CLASS_ID[cls], bytes(payload))
    assert ubx.encode(ubx.decode(ubx.parse(raw))) == raw


# --- refusals ----------------------------------------------------------------------------

def test_unknown_class_and_id():
    with pytest.raises(Unsupported):
        ubx.decode(ubx.parse(ubx.encode_frame(0x01, 0x07, bytes(92))))


@pytest.mark.parametrize(("cls", "at", "version"), [
    (RxmPmp, 0, 2), (RxmPmpV0, 0, 2), (RxmSfrbx, 6, 1), (NavTimels, 4, 1),
    (RxmRawx, 13, 0), (RxmRawx, 13, 2)])
def test_other_versions_are_unsupported(cls, at, version):
    # RXM-RAWX version 0 ("UBX-RXM-RAWX-DATA0") is in no staged document.
    good = ubx.encode({RxmPmp: pmp(), RxmPmpV0: pmp0(), RxmSfrbx: sfrbx(),
                       NavTimels: timels(), RxmRawx: rawx(meas=(meas(),))}[cls])[6:-2]
    payload = bytearray(good)
    payload[at] = version
    with pytest.raises(Unsupported, match="version"):
        ubx.decode(ubx.parse(ubx.encode_frame(*CLASS_ID[cls], bytes(payload))))


def test_pmp_version_byte_picks_the_table():
    # The two versions differ in layout; the version byte, not the length, decides.
    assert isinstance(ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x72, bytes(528)))), RxmPmpV0)
    v1 = bytearray(ubx.encode(pmp(user_data=bytes(504)))[6:-2])
    assert len(v1) == 528
    assert isinstance(ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x72, bytes(v1)))), RxmPmp)
    v1[0] = 0   # a version 1 layout labelled version 0 is decoded as version 0
    assert isinstance(ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x72, bytes(v1)))), RxmPmpV0)
    for size in (0, 24, 527, 529):
        with pytest.raises(FieldError):
            ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x72, bytes(size))))


@pytest.mark.parametrize("size", [0, 4, 23, 25])
def test_timels_wrong_length(size):
    # 0 and 4 bytes end before the version byte at offset 4.
    with pytest.raises(FieldError):
        ubx.decode(ubx.parse(ubx.encode_frame(0x01, 0x26, bytes(size))))


def test_counted_lengths_must_match():
    good_pmp = ubx.encode(pmp(user_data=b"abc"))[6:-2]
    for payload in (good_pmp[:-1], good_pmp + b"\0"):
        with pytest.raises(FieldError):
            ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x72, payload)))
    good_sfrbx = ubx.encode(sfrbx(dwrd=(1, 2)))[6:-2]
    for payload in (good_sfrbx[:-1], good_sfrbx + bytes(4), good_sfrbx[:4]):
        with pytest.raises(FieldError):
            ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x13, payload)))
    good_rawx = ubx.encode(rawx(meas=(meas(), meas())))[6:-2]
    for payload in (good_rawx[:-1], good_rawx[:-32], good_rawx + bytes(32), good_rawx[:14]):
        with pytest.raises(FieldError):
            ubx.decode(ubx.parse(ubx.encode_frame(0x02, 0x15, payload)))


@pytest.mark.parametrize("message", [
    timels(itow=-1), timels(itow=2**32), timels(curr_ls=128), timels(curr_ls=-129),
    timels(reserved0=(0, 0)), timels(reserved0=(0, 0, 256)), timels(valid=True),
    pmp(num_bytes_user_data=4), pmp(user_data=b"ab", num_bytes_user_data=3),
    pmp(unique_word=(1,)), pmp(user_data="abc", num_bytes_user_data=3),
    sfrbx(dwrd=(1, 2), num_words=3), sfrbx(dwrd=(2**32,)), sfrbx(num_words=256),
    timels(version=1), pmp(version=0), sfrbx(version=1),
    pmp0(version=1), pmp0(user_data=bytes(503)), pmp0(reserved0=(0, 0)),
    rawx(version=0), rawx(rcv_tow=1 << 64), rawx(rcv_tow=-1), rawx(rcv_tow=1.5),
    rawx(meas=(meas(),), num_meas=2), rawx(meas=[meas()]), rawx(meas=(sfrbx(),)),
    rawx(meas=(meas(do_mes=1 << 32),)), rawx(meas=(meas(locktime=-1),)),
])
def test_encode_refuses_what_does_not_fit(message):
    with pytest.raises(FieldError):
        ubx.encode(message)


def test_encode_refuses_other_objects():
    with pytest.raises(TypeError):
        ubx.encode(object())


# --- cross-check with pyubx2 -------------------------------------------------------------

def _oracle_view(message) -> dict:
    """Our message keyed and shaped the way pyubx2 1.4 reports it.

    pyubx2 names fields as the spec does; it reports a constant U1[n] as one
    little-endian integer, a U4[n] as name1, name2..., a repeated group as
    name_01, name_02..., userData as one little-endian integer, an X1 (with
    parsebitfield=0) as bytes, R4 and R8 as floats, and scales ebno by 2^-3
    to dB. For RXM-RAWX it takes bytes 13 to 15 (version and reserved0) as
    one three-byte "reserved1", and names the group's reserved1 "reserved3".
    """
    view = _view_rows(message, "")
    if "ebno" in view:
        view["ebno"] = view["ebno"] / 8
    if isinstance(message, RxmRawx):
        view.pop("reserved0")
        view.pop("version")
        view["reserved1"] = int.from_bytes(bytes((message.version, *message.reserved0)), "little")
        view = {k.replace("reserved1_", "reserved3_"): v for k, v in view.items()}
    return view


def _view_rows(message, suffix: str) -> dict:
    view = {}
    for row in ubx.layout(type(message)).rows:
        kind, value = row.kind, getattr(message, row.field)
        name = kind.name
        if isinstance(kind, Group):
            for i, item in enumerate(value):
                view.update(_view_rows(item, f"_{i + 1:02d}"))
        elif isinstance(kind, Bytes):
            view[name] = int.from_bytes(value, "little")
        elif kind.count is None:
            kind_name = type(kind).__name__
            if kind_name == "X1":
                value = value.to_bytes(1, "little")
            elif kind_name in ("R4", "R8"):
                value = struct.unpack("<f" if kind_name == "R4" else "<d",
                                      value.to_bytes(kind.size, "little"))[0]
            view[name + suffix] = value
        elif type(kind).__name__ == "U1":
            view[name] = int.from_bytes(bytes(value), "little")
        elif isinstance(kind.count, int):
            view.update({f"{name}{i + 1}": v for i, v in enumerate(value)})
        else:
            view.update({f"{name}_{i + 1:02d}": v for i, v in enumerate(value)})
    return view


def _oracle_fields(parsed) -> dict:
    return {k: v for k, v in vars(parsed).items() if not k.startswith("_")}


@often
@given(messages)
def test_pyubx2_decodes_our_frames_alike(message):
    raw = ubx.encode(message)
    parsed = pyubx2.UBXReader.parse(raw, parsebitfield=0)
    assert parsed.identity == message.NAME
    assert _oracle_fields(parsed) == _oracle_view(message)


@often
@given(messages)
def test_pyubx2_frames_decode_here(message):
    view = _oracle_view(message)
    built = pyubx2.UBXMessage(message.MSG_CLASS, message.MSG_ID, 0, parsebitfield=0, **view)
    raw = built.serialize()
    assert ubx.decode(ubx.parse(raw)) == message
    assert ubx.encode(message) == raw


# --- private captures ------------------------------------------------------------------------
#
# build/private/ (gitignored, never committed; see its README.txt) holds
# recorded receiver streams. When it is present, every UBX frame in them must
# decode, re-encode to its own bytes and agree with pyubx2. Nothing from these
# files is copied into the repository.

PRIVATE = Path(__file__).resolve().parents[3] / "build" / "private"
private = pytest.mark.skipif(not PRIVATE.is_dir(),
                             reason="private captures (build/private/) are absent")


@private
def test_private_captures_round_trip_and_agree_with_pyubx2():
    seen: dict[str, int] = {}
    failures = []
    for path in sorted(PRIVATE.glob("*.bin")):
        stream = path.read_bytes()
        for frame in ubx.scan(stream):
            raw = stream[frame.offset:frame.offset + frame.length]
            try:
                message = ubx.decode(frame)
            except Unsupported:
                continue
            seen[f"{message.NAME} v{message.version}"] = seen.get(
                f"{message.NAME} v{message.version}", 0) + 1
            parsed = pyubx2.UBXReader.parse(raw, parsebitfield=0)
            if ubx.encode(message) != raw:
                failures.append((path.name, frame.offset, "round trip"))
            elif _oracle_fields(parsed) != _oracle_view(message):
                failures.append((path.name, frame.offset, "pyubx2 differs"))
    assert not failures, failures[:10]
    # What the README says the captures hold.
    assert seen.get("RXM-PMP v1", 0) > 0 and seen.get("RXM-SFRBX v2", 0) > 0
    assert seen.get("NAV-TIMELS v0", 0) > 0
