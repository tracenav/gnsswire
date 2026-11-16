"""Station messages: 1005, 1006, 1007, 1008, 1033 and 1230.

Each class is the field table of RTCM 10403.3 cited in its docstring, row for
row and in order; the DF numbers are the rows' tags. Values are the raw DF
integers: ``x`` of 1005 is in units of 0.0001 m, the code-phase biases of 1230
in 0.02 m, and so on (section 3.4, Table 3.4-1, gives the resolutions).

Character fields (DF030, DF033, DF228, DF230, DF232) are kept as ``bytes``,
one byte per character, exactly as sent, and never decoded to ``str``. Each
string's length is its counter (DF029, DF032, DF227, DF229, DF231: "the
number of characters (bytes) to follow", Table 3.4-1), a uint8. Table 3.4-1
gives each counter the range 0-31 and the message tables note N ≤ 31; that is
a range, not a width, and is not enforced (field tables do not validate
ranges), so a counter of 32 to 255 decodes and round-trips. ``encode`` refuses
a counter that does not fit the uint8 and a string whose length differs from
its counter.

Which characters a string may hold is AMBIGUOUS. Table 3.3-1 defines char8(n)
as "8 bit characters, ISO 8859-1 (not limited to ASCII)", with "Reserved or
unused characters: [0x00]"; ISO 8859-1 assigns graphic characters to 0x20 to
0x7E and 0xA0 to 0xFF only. But section 3.5.4 calls 1007 "an ASCII
descriptor", DF030 and DF033 say "Alphanumeric characters", and Table 3.5-36
prints its strings as char(N), not char8(N). Readings: (a) ISO 8859-1 graphic
characters; (b) printable ASCII. Neither changes the codec: like a range, the
character set is not enforced, so every byte, 0x00 and the code positions
neither reading allows included, decodes and round-trips as sent, and which
text the bytes stand for is the caller's (``value.decode("latin-1")`` under
either reading). The public 1033 frames (``tests/data/public.hex``) hold
printable ASCII only, inside both readings; ``test_messages.py`` checks that.

Every message table here and in ``_ephemeris`` and ``_msm`` ends with
``extension``: what follows the table in the message, ``None`` when that is
no more than the zero fill bits of the last byte (the note to Table 3.2-1:
"Fill bits (zeros) must be used to complete the last byte"). Section 3.5.16.3.4
reserves data appended to an MSM for future extensions, which a decoder
"shall skip (ignore)" and treat "as normal"; section 3.5.17 reserves the same
for 1230. The standard says nothing of the kind for the other messages, but
keeping the bits loses nothing, so every table keeps them as a
``gnsswire.bits.Extension`` and writes them back, and ``decode(frame,
strict=True)`` refuses them instead.
"""

from dataclasses import dataclass
from typing import Annotated

from gnsswire.bits import Extension, F, Octets, Rest, S, U

# The row that ends every message table: what follows the table.
Ext = Annotated[Extension | None, Rest()]


@dataclass(frozen=True, slots=True)
class Msg1005:
    """Stationary antenna reference point, no height. RTCM 10403.3 Table 3.5-6 (152 bits)."""

    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    itrf_year: Annotated[int, U(6, "DF021")]
    gps: Annotated[int, U(1, "DF022")]
    glonass: Annotated[int, U(1, "DF023")]
    galileo: Annotated[int, U(1, "DF024")]
    reference_station: Annotated[int, U(1, "DF141")]
    x: Annotated[int, S(38, "DF025")]
    single_oscillator: Annotated[int, U(1, "DF142")]
    reserved: Annotated[int, U(1, "DF001")]
    y: Annotated[int, S(38, "DF026")]
    quarter_cycle: Annotated[int, U(2, "DF364")]
    z: Annotated[int, S(38, "DF027")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1006:
    """Stationary antenna reference point, with height. RTCM 10403.3 Table 3.5-7 (168 bits).

    Table 3.5-6 (1005) followed by DF028, the antenna height (uint16, 0.0001
    m: "Reference Point above the marker used in the survey campaign").
    """

    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    itrf_year: Annotated[int, U(6, "DF021")]
    gps: Annotated[int, U(1, "DF022")]
    glonass: Annotated[int, U(1, "DF023")]
    galileo: Annotated[int, U(1, "DF024")]
    reference_station: Annotated[int, U(1, "DF141")]
    x: Annotated[int, S(38, "DF025")]
    single_oscillator: Annotated[int, U(1, "DF142")]
    reserved: Annotated[int, U(1, "DF001")]
    y: Annotated[int, S(38, "DF026")]
    quarter_cycle: Annotated[int, U(2, "DF364")]
    z: Annotated[int, S(38, "DF027")]
    height: Annotated[int, U(16, "DF028")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1007:
    """Antenna descriptor. RTCM 10403.3 Table 3.5-8 (40 + 8·N bits).

    Section 3.5.4. The descriptor (DF030, char8(N)) follows its counter N
    (DF029; the table notes N ≤ 31), then the antenna setup ID (DF031: 0 for
    "a standard model type calibration", 1-255 a provider's setup). Strings
    and counters as in the module docstring. Its rows are the first five of
    Table 3.5-9 (1008).
    """

    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    antenna_count: Annotated[int, U(8, "DF029")]
    antenna: Annotated[bytes, Octets(F.antenna_count, "DF030")]
    antenna_setup: Annotated[int, U(8, "DF031")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1008:
    """Antenna descriptor and serial number. RTCM 10403.3 Table 3.5-9 (48 + 8·(M+N) bits).

    Section 3.5.4: Table 3.5-8 (1007) followed by the serial number counter M
    (DF032; the table notes M ≤ 31) and the antenna serial number (DF033,
    char8(M)). Its rows are the first seven of Table 3.5-36 (1033), "an
    elaboration of Message Type 1008" (section 3.5.12.5).
    """

    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    antenna_count: Annotated[int, U(8, "DF029")]
    antenna: Annotated[bytes, Octets(F.antenna_count, "DF030")]
    antenna_setup: Annotated[int, U(8, "DF031")]
    antenna_serial_count: Annotated[int, U(8, "DF032")]
    antenna_serial: Annotated[bytes, Octets(F.antenna_serial_count, "DF033")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1033:
    """Receiver and antenna descriptors. RTCM 10403.3 Table 3.5-36 (72 + 8·(N+M+I+J+K) bits).

    Each string follows its counter; strings and counters as in the module
    docstring (the table prints the type as char(N), Table 3.4-1 as char8).
    Section 3.5.12.5: an unknown descriptor has a zero counter and no
    characters.
    """

    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    antenna_count: Annotated[int, U(8, "DF029")]
    antenna: Annotated[bytes, Octets(F.antenna_count, "DF030")]
    antenna_setup: Annotated[int, U(8, "DF031")]
    antenna_serial_count: Annotated[int, U(8, "DF032")]
    antenna_serial: Annotated[bytes, Octets(F.antenna_serial_count, "DF033")]
    receiver_count: Annotated[int, U(8, "DF227")]
    receiver: Annotated[bytes, Octets(F.receiver_count, "DF228")]
    firmware_count: Annotated[int, U(8, "DF229")]
    firmware: Annotated[bytes, Octets(F.firmware_count, "DF230")]
    receiver_serial_count: Annotated[int, U(8, "DF231")]
    receiver_serial: Annotated[bytes, Octets(F.receiver_serial_count, "DF232")]
    extension: Ext = None


@dataclass(frozen=True, slots=True)
class Msg1230:
    """GLONASS L1 and L2 code-phase biases. RTCM 10403.3 Table 3.5-109 (32 + 16·N bits).

    DF422 is a mask whose most significant bit marks the presence of DF423
    and whose least significant bit marks DF426 (DF422 in Table 3.4-1); a
    bias whose bit is clear is absent from the message and ``None`` here.
    """

    number: Annotated[int, U(12, "DF002")]
    station: Annotated[int, U(12, "DF003")]
    aligned: Annotated[int, U(1, "DF421")]
    reserved: Annotated[int, U(3, "DF001")]
    mask: Annotated[int, U(4, "DF422")]
    l1_ca: Annotated[int | None, S(16, "DF423", when=F.mask & 8)]
    l1_p: Annotated[int | None, S(16, "DF424", when=F.mask & 4)]
    l2_ca: Annotated[int | None, S(16, "DF425", when=F.mask & 2)]
    l2_p: Annotated[int | None, S(16, "DF426", when=F.mask & 1)]
    extension: Ext = None
