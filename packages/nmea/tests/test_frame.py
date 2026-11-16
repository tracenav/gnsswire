"""Sentence framing against the u-blox F9 HPG 1.51 Interface Description, chapter 2.

The example sentences are copied from the document (UBXDOC-963802114-13124
R01); the section each comes from is noted. Chapter 2 of the earlier F9 HPG
1.32 description (UBX-22008968 R01) prints the same examples, under the same
section numbers, except the GSV example with an unknown signal, which is new
in 1.51. The properties shared with the other codecs
(truncation, bit flips, scan through garbage) are in tests/test_framing.py.
"""

import pytest

from gnsswire import nmea
from gnsswire.nmea import MAX_LENGTH, Frame, Invalid, NeedMore

# Example sentences whose printed checksum is the XOR of the bytes between
# '$' and '*'. Together they confirm the algorithm the figure of section 2.1
# leaves implicit.
EXAMPLES = [
    "$GPZDA,141644.00,22,03,2002,00,00*67",             # 2.1, figure
    "$GNRMC,014230.00,A,4722.80340,N,00831.68218,E,0.000,,120477,,,A,V*14",   # 2.5
    "$GPGLL,4717.11634,N,00833.91297,E,124923.00,A,A*6E",   # 2.5
    "$GPGLL,,,,,124924.00,V,N*42",                      # 2.5
    "$GPGLL,,,,,,V,N*64",                               # 2.5
    "$GPDTM,W84,,0.0,N,0.0,E,0.0,W84*6F",               # 2.7.1
    "$EIGAQ,RMC*2B",                                    # 2.7.2
    "$EIGBQ,RMC*28",                                    # 2.7.3
    "$GPGBS,235503.00,1.6,1.4,3.2,,,,,,*40",            # 2.7.4
    "$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B",  # 2.7.5
    "$GPGLL,4717.11364,N,00833.91565,E,092321.00,A,A*60",   # 2.7.6
    "$GNGNS,103600.01,5114.51176,N,00012.29380,W,ANNN,07,1.18,111.5,45.6,,,V*00",  # 2.7.9
    "$EIGPQ,RMC*3A",                                    # 2.7.10
    "$GNGRS,104148.00,1,2.6,2.2,-1.6,-1.1,-1.7,-1.5,5.8,1.7,,,,,1,1*52",  # 2.7.12
    "$GPGST,082356.00,1.8,,,,1.7,1.3,2.2*7E",           # 2.7.14
    "$GPGSV,3,1,09,09,,,17,10,,,40,12,,,49,13,,,35,1*6F",   # 2.7.15
    "$GPGSV,3,2,09,15,,,44,17,,,45,19,,,44,24,,,50,1*64",   # 2.7.15
    "$GPGSV,3,3,09,25,,,40,1*6E",                       # 2.7.15
    "$GPGSV,1,1,03,12,,,42,24,,,47,32,,,37,5*66",       # 2.7.15
    "$GPGSV,1,1,01,03,05,218,,0*59",                    # 2.7.15: signal ID 0 (unknown), 1.51
    "$GAGSV,1,1,00,2*76",                               # 2.7.15
    "$GPTXT,01,01,02,u-blox ag - www.u-blox.com*50",    # 2.7.18: spaces, lowercase
    "$GPTXT,01,01,02,ANTARIS ATR0620 HW 00000040*67",   # 2.7.18
    "$GPVTG,77.52,T,,M,0.004,N,0.008,K,A*06",           # 2.7.20
    "$GPZDA,082710.00,16,09,2002,00,00*64",             # 2.7.21
    "$PUBX,41,1,0007,0003,19200,0*25",                  # 2.9.1
    "$PUBX,00*33",                                      # 2.9.2.1
    "$PUBX,00,081350.00,4717.113210,N,00833.915187,E,546.589,G3,2.1,2.0,0.007,77.52,0.007"
    ",,0.92,1.19,0.77,9,0,0*5F",                        # 2.9.2.2: 111 bytes
    "$PUBX,40,GLL,1,0,0,0,0,0*5D",                      # 2.9.3
    "$PUBX,03*30",                                      # 2.9.4.1
    "$PUBX,03,11,23,-,,,45,010,29,-,,,46,013,07,-,,,42,015,08,U,067,31,42,025,10,U,195,33"
    ",46,026,18,U,326,08,39,026,17,-,,,32,015,26,U,306,66,48,025,27,U,073,10,36,026,28,U,"
    "089,61,46,024,15,-,,,39,014*0D",                   # 2.9.4.2: 200 bytes
    "$PUBX,04*37",                                      # 2.9.5.1
]

# Example sentences the document prints with a checksum that is not the XOR
# of the sentence (checked against the PDF, not only its text extraction:
# e.g. VLW on page 39). Several repeat a neighbour's checksum: the GLQ, GNQ
# and GQQ polls all print GPQ's *3A. A framer must refuse them.
MISPRINTED = [
    ("$GPDTM,999,,0.08,N,0.07,E,-47.7,W84*1C", 0x1B),   # 2.7.1
    ("$GPGBS,235458.00,1.4,1.3,3.1,03,,-21.4,3.8,1,0*5B", 0x5A),   # 2.7.4
    ("$EIGLQ,RMC*3A", 0x26),                            # 2.7.7
    ("$EIGNQ,RMC*3A", 0x24),                            # 2.7.8
    ("$GNGNS,122310.2,3722.425671,N,12258.856215,W,DAAA,14,0.9,1005.543,6.5,,,V*0E",
     0x0B),                                             # 2.7.9
    ("$GPGNS,122310.2,,,,,,07,,,,5.2,23,V*02", 0x07),   # 2.7.9
    ("$EIGQQ,RMC*3A", 0x3B),                            # 2.7.11
    ("$GNGRS,104148.00,1,,0.0,2.5,0.0,,2.8,,,,,,,1,5*52", 0x51),   # 2.7.12
    ("$GPGSA,A,3,23,29,07,08,09,18,26,28,,,,,1.94,1.18,1.54,1*0D", 0x10),   # 2.7.13 and 2.8.4
    ("$GARLM,00000078A9FBAD5,083559.00,3,C45B*57", 0x09),   # 2.7.16
    ("$GARLM,F7129D41BC6A78C,034433.02,3,B63CA732AFD419D2*57", 0x03),   # 2.7.16
    ("$GPRMC,083559.00,A,4717.11437,N,00833.91522,E,0.004,77.52,091202,,,A,V*57",
     0x2D),                                             # 2.7.17 and 2.8.5
    ("$GPVLW,,N,,N,15.8,N,1.2,N*06", 0x65),             # 2.7.19
    ("$PUBX,04,073731.00,091202,113851.00,1196,15D,1930035,-2660.664,43,*3C", 0x5D),  # 2.9.5.2
]


def wire(sentence: str) -> bytes:
    return sentence.encode() + b"\r\n"


@pytest.mark.parametrize("sentence", EXAMPLES)
def test_spec_examples(sentence):
    frame = wire(sentence)
    result = nmea.parse(frame)
    assert result == Frame(0, len(frame), sentence[1:sentence.index("*")].encode())
    assert nmea.encode(result) == frame
    assert nmea.encode_frame(result.payload) == frame


def test_examples_longer_than_82_characters():
    # Section 2.2: 82 is the CFG-NMEA-LIMIT82 option, not a framing rule.
    long = [s for s in EXAMPLES if len(wire(s)) > 82]
    assert [len(wire(s)) for s in long] == [111, 200]
    assert all(isinstance(nmea.parse(wire(s)), Frame) for s in long)


@pytest.mark.parametrize(("sentence", "xor"), MISPRINTED)
def test_misprinted_examples_are_refused(sentence, xor):
    assert nmea.parse(wire(sentence)) == Invalid("checksum mismatch")
    body = sentence[1:sentence.index("*")]
    assert nmea.encode_frame(body.encode()) == wire(f"${body}*{xor:02X}")


def test_tag_block_is_not_a_sentence():
    # Section 2.8.1: a TAG block before the sentence. Its own checksum "*78"
    # is the XOR of "s:1" too, but TAG blocks are outside this framing.
    stream = b"\\s:1*78\\$GPGGA,092725.00,4717.11399,N,00833.91590,E,1,08,1.01,499.6,M,48.0,M,,*5B\r\n"
    assert isinstance(nmea.parse(stream), Invalid)
    frames = list(nmea.scan(stream))
    assert [(f.offset, f.length) for f in frames] == [(8, len(stream) - 8)]
    assert frames[0].payload.startswith(b"GPGGA,")


@pytest.mark.parametrize(("data", "reason"), [
    (b"GPZDA*00\r\n", "no '$' start character"),
    (b"$*00\r\n", "empty address"),
    (b"$,1*1D\r\n", "empty address"),
    (b"$gpzda*40\r\n", "address is not digits and uppercase letters"),
    (b"$GP ZDA*1A\r\n", "address is not digits and uppercase letters"),
    (b"$GPZDA,a$b*00\r\n", "byte 0x24 not allowed in a field"),
    (b"$GPZDA,a\tb*00\r\n", "byte 0x09 not allowed in a field"),
    (b"$GPZDA,1\r\n", "byte 0x0d not allowed in a field"),
    (b"$GPZDA,\xb5*00\r\n", "byte 0xb5 not allowed in a field"),
    (b"$PUBX,00*3g\r\n", "checksum is not two uppercase hex digits"),
    # AMBIGUOUS in the source (case of the hex digits); see _frame.py.
    (b"$GPGST,082356.00,1.8,,,,1.7,1.3,2.2*7e\r\n", "checksum is not two uppercase hex digits"),
    (b"$PUBX,00*33\n", "no CR LF after the checksum"),
    (b"$PUBX,00*33\r\r", "no CR LF after the checksum"),
    (b"$PUBX,00*33\n\r", "no CR LF after the checksum"),
    (b"$PUBX,00*34\r\n", "checksum mismatch"),
])
def test_invalid(data, reason):
    # strict=True: only what the u-blox document prints.
    assert nmea.parse(data, strict=True) == Invalid(reason)


@pytest.mark.parametrize(("data", "reason"), [
    (b"$PUBX,00*3g\r\n", "checksum is not two hex digits of one case"),
    (b"$GPGST,082356.00,1.8,,,,1.7,1.3,2.2*7E\n\r", None),        # LF, then a stray CR
    (b"$P*aB\r\n", "checksum is not two hex digits of one case"),      # mixed case
    (b"$PUBX,00*33\r\r", "no CR LF after the checksum"),
    (b"$PUBX,00*33\t", "no CR LF or LF after the checksum"),
    (b"$PUBX,00*33\r", None),
])
def test_lenient_still_refuses(data, reason):
    # Lenient parsing takes two hex digits of one case and CR LF or LF, nothing else.
    result = nmea.parse(data)
    if reason is None:
        assert not isinstance(result, Invalid)
    else:
        assert result == Invalid(reason)


@pytest.mark.parametrize("sentence", [
    b"$GPGST,082356.00,1.8,,,,1.7,1.3,2.2*7e\r\n",
    b"$GPGST,082356.00,1.8,,,,1.7,1.3,2.2*7E\n",
    b"$GPGST,082356.00,1.8,,,,1.7,1.3,2.2*7e\n",
])
def test_lowercase_checksum_and_bare_lf_are_accepted_and_kept(sentence):
    # Section 2.1 says only "two characters checksum in hex" (the case is
    # not fixed) and "always \r\n"; a receiver is lenient by default.
    frame = nmea.parse(sentence)
    assert isinstance(frame, Frame) and frame.length == len(sentence)
    assert frame.lower_hex == (b"*7e" in sentence)
    assert frame.ending == (b"\r\n" if sentence.endswith(b"\r\n") else b"\n")
    assert nmea.encode(frame) == sentence
    assert nmea.encode_frame(frame.payload) == sentence[:sentence.index(b"*")] + b"*7E\r\n"
    assert isinstance(nmea.parse(sentence, strict=True), Invalid)
    assert [f.length for f in nmea.scan(b"x" + sentence * 2)] == [len(sentence)] * 2
    assert list(nmea.scan(sentence, strict=True)) == []


def test_encode_frame_refuses_an_unknown_ending():
    with pytest.raises(nmea.Error):
        nmea.encode_frame(b"P", ending=b"\r")


def test_invalid_is_reported_before_the_end_arrives():
    # A streaming caller learns of a bad byte without waiting for CR LF.
    assert isinstance(nmea.parse(b"$GPZDA,1\x00"), Invalid)
    assert isinstance(nmea.parse(b"$PUBX,00*3"), NeedMore)
    assert isinstance(nmea.parse(b"$PUBX,00*3x"), Invalid)
    assert isinstance(nmea.parse(b"$PUBX,00*33\r"), NeedMore)
    assert isinstance(nmea.parse(b"$PUBX,00*33\rx"), Invalid)


def test_need_more_knows_the_length_once_the_star_is_in():
    frame = wire("$PUBX,00*33")
    assert [nmea.parse(frame[:i], strict=True) for i in range(len(frame))] == (
        [NeedMore(0)] * 9 + [NeedMore(len(frame))] * 4)
    # Lenient: until the ending starts, a bare LF would complete it a byte sooner.
    assert [nmea.parse(frame[:i]) for i in range(len(frame))] == (
        [NeedMore(0)] * 9 + [NeedMore(len(frame) - 1)] * 3 + [NeedMore(len(frame))])


def test_max_length():
    def sentence(length: int) -> bytes:
        return nmea.encode_frame(b"P," + b"x" * (length - 8))

    assert len(sentence(MAX_LENGTH)) == MAX_LENGTH
    assert isinstance(nmea.parse(sentence(MAX_LENGTH)), Frame)
    with pytest.raises(ValueError):
        sentence(MAX_LENGTH + 1)
    too_long = b"$P," + b"x" * (MAX_LENGTH - 2) + b"*00\r\n"
    assert nmea.parse(too_long) == Invalid(f"no '*' within {MAX_LENGTH} bytes")
    # The '*' can be no later than MAX_LENGTH - 5: one byte short of that
    # is still undecided, reaching it without a '*' is not.
    assert nmea.parse(too_long[:MAX_LENGTH - 5]) == NeedMore(0)
    assert isinstance(nmea.parse(too_long[:MAX_LENGTH - 4]), Invalid)


@pytest.mark.parametrize("payload", [b"", b",A", b"gp", b"GP,*", b"GP,$", b"GP,\r\n", b"GP,\xff"])
def test_encode_frame_refuses_what_parse_would(payload):
    with pytest.raises(ValueError):
        nmea.encode_frame(payload)


def test_encode_frame_minimal():
    assert nmea.encode_frame(b"P") == b"$P*50\r\n"
    assert nmea.parse(b"$P*50\r\n") == Frame(0, 7, b"P")


def test_parse_accepts_bytearray():
    frame = wire(EXAMPLES[0])
    assert nmea.parse(bytearray(b"xx" + frame), 2) == Frame(2, len(frame), b"GPZDA,141644.00,22,03,2002,00,00")
    assert [f.offset for f in nmea.scan(bytearray(frame * 2))] == [0, len(frame)]
