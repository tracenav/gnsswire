"""How UBX-RXM-SFRBX and the SkyTraq navigation data messages carry the units of each system.

This module imports neither ``gnsswire.ubx`` nor ``gnsswire.skytraq``: it
reads the fields of their message dataclasses (``gnss_id``, ``dwrd`` and
so on) and gives back the field values to build them with, so that each
distribution stays installable on its own.

UBX-RXM-SFRBX (u-blox F9 HPG 1.51, section 3.17.9: gnssId, svId, sigId,
freqId and the 32-bit data words; signal identifiers in section 1.5.4,
Table 4). The earlier F9 HPG 1.32 description and the u-blox X20 HPG 2.11
one (section 3.16.8) print the same message and give the signals taken
here the same gnssId and sigId (section 1.5.4, Table 4). None of them
prints a per-signal layout of the words; the u-blox 8 / M8
Receiver Description (UBX-13003221, R28), chapter 10 "Broadcast Navigation
Data", does, and is the source here:

- GPS L1C/A (10.2.1): ten words, each 2 pad bits then the 30-bit word,
  24 data bits and 6 parity bits. "Where the parity checking algorithm
  requires data to be inverted ... the receiver carries this out before
  the message output" (10.1). The document does not say whether the parity
  bits are complemented with the data; receivers at hand complement the
  whole 30-bit word when the previous word's D30 is 1, and that is the
  reading here (README, "Limitations"): dwrd = pad, then the transmitted
  word XOR (all ones when D30* is 1).
- GLONASS L1OF and L2OF (10.3): four words: the 85-bit string (bit 85 the
  idle chip first) and 11 pad bits in words 1 to 3; word 4 is the
  superframe number (16 bits), 8 pad bits and the frame number (8 bits),
  which "aren't actually transmitted by the SVs" and are 0 when unknown.
- BeiDou B1I (10.4): ten words, each 2 pad bits, 22 data bits, 8 parity
  bits; for word 1 (26 information bits, 4 parity bits) the same 30 bits
  hold the 26 then the 4. The figure gives the data bits de-interleaved
  (22, then the parity) but not the order of the parity bits; receivers at
  hand send them as zero. The reading here (README, "Limitations"): the
  parity fields are all zero (not supplied, nothing to check), or they are P1(1)
  to P1(4) then P2(1) to P2(4) and must equal the BCH code (5.1.3 of the
  BDS ICD); anything else is a :class:`ParityError`.
- Galileo E1 and E5b I/NAV (10.5.1): eight words: the even page part
  (120 bits) and 8 pad bits in words 1 to 4, the odd part and 8 pad bits in
  words 5 to 8. The document draws E1OS; for E5b it says only that both
  carry I/NAV, so E5b is taken to be laid out alike.

Only these are taken: GPS L2C and L5, Galileo E5a (F/NAV), BeiDou B1C and
B2a, QZSS, SBAS, NavIC and IMES (gnssId 4, which F9 HPG 1.51 no longer
lists) raise :class:`Unsupported` (no staged document lays their words out,
or no table here reads them), and so do the signals F9 HPG 1.51 lists and
1.32 did not: Galileo E6 (sigId 8 to 10), BeiDou B3I D1 and D2 (4 and 10)
and the BeiDou B1C and B2a data components (6 and 8; 1.32's B1C and B2a,
sigId 5 and 7, are now the pilots), and QZSS L1C/B (12), which X20 HPG
2.11 adds.

SkyTraq (AN0039 version 1.4.42):

- 0xE0, GPS SUBFRAME: SVID (PRN), SFID, ten 3-byte words: "the 24 higher
  bits of each of the navigation words", parity-checked by the receiver,
  "polarity-adjusted": the source data bits d1 to d24.
- 0xE1, GLONASS STRING: SVID (slot + 64), string number, bits 80 to 9 of
  the string, Hamming code checked by the receiver and not sent. Bits 84
  to 81 are the string number m; the idle chip is 0 (ICD 4.3.3).
- 0xE2 and 0xE3, BEIDOU2 D1 and D2 SUBFRAME: SVID (PRN + 200), SFID, 28
  bytes: the 26 information bits of word 1 and the 22 of words 2 to 10,
  parity checked by the receiver and not sent.
- 0xE6, GENERAL SUBFRAME version 1: for Galileo E1 and E5b (the only GNSS
  whose mapping the note prints, in its "Remark"), eight words laid out as
  UBX lays them out: even part and 8 pad bits ("Pad 0"), odd part and 8 pad
  bits. Other GNSS types and signals raise :class:`Unsupported`.

Where the carrier strips the check bits, they are not checked (the
receiver did); the unit is completed from the ICD (parity, BCH code,
Hamming code computed) so it decodes like any other, and the round trip
drops them again.

:func:`from_sfrbx` and :func:`from_skytraq` give a :class:`Received`;
:func:`sfrbx_fields` and :func:`skytraq_fields` give back the fields of
the carrier message, so that for every message a conforming receiver
sends, ``RxmSfrbx(**sfrbx_fields(from_sfrbx(m))) == m`` and likewise for
SkyTraq.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import beidou, galileo, glonass, gps
from ._common import FieldError, ParityError, Unsupported

GPS, GALILEO_INAV, BEIDOU_D1, BEIDOU_D2, GLONASS = "gps", "galileo-inav", "beidou-d1", \
    "beidou-d2", "glonass"

# UBX gnssId, sigId to system (F9 HPG 1.51 and X20 HPG 2.11, 1.5.4, "Signal identifiers").
_UBX_SIGNALS = {
    (0, 0): GPS,
    (2, 0): GALILEO_INAV, (2, 1): GALILEO_INAV, (2, 5): GALILEO_INAV, (2, 6): GALILEO_INAV,
    (3, 0): BEIDOU_D1, (3, 1): BEIDOU_D2, (3, 2): BEIDOU_D1, (3, 3): BEIDOU_D2,
    (6, 0): GLONASS, (6, 2): GLONASS,
}
_UBX_WORDS = {GPS: 10, GALILEO_INAV: 8, BEIDOU_D1: 10, BEIDOU_D2: 10, GLONASS: 4}


@dataclass(frozen=True, slots=True)
class Received:
    """One unit of navigation data as a carrier delivered it.

    ``system`` is one of ``"gps"``, ``"galileo-inav"``, ``"beidou-d1"``,
    ``"beidou-d2"``, ``"glonass"``; ``satellite`` the PRN (GLONASS: slot
    number) the carrier gives; ``message`` the decoded table of the unit
    (a GPS subframe, a Galileo :class:`~gnsswire.nav.galileo.InavPage`, a
    BeiDou subframe, a GLONASS string). ``carrier`` is what the carrier
    adds that is not in the unit, kept for the round trip: for UBX the
    message's own fields and the pad bits (and BeiDou's parity fields, and
    GLONASS's fourth word), for SkyTraq the message ID and fields.
    """

    system: str
    satellite: int
    signal: int
    message: Any
    carrier: tuple[Any, ...]


# --- UBX-RXM-SFRBX -------------------------------------------------------------------------

def from_sfrbx(msg: Any) -> Received:
    """The unit in a ``gnsswire.ubx.RxmSfrbx`` (any object with its fields)."""
    system = _UBX_SIGNALS.get((msg.gnss_id, msg.sig_id))
    if system is None:
        raise Unsupported(f"UBX-RXM-SFRBX gnssId {msg.gnss_id} sigId {msg.sig_id}: no layout "
                          f"or no tables for its words")
    words = tuple(msg.dwrd)
    if len(words) != _UBX_WORDS[system]:
        raise FieldError(f"{system}: {len(words)} words, UBX-13003221 chapter 10 gives "
                         f"{_UBX_WORDS[system]}")
    header = (msg.gnss_id, msg.sig_id, msg.freq_id, msg.chn, msg.version, msg.reserved0)
    if system == GPS:
        pad = tuple(w >> 30 for w in words)
        transmitted = []
        prev = 0
        for w in words:
            word = (w & 0x3FFFFFFF) ^ (0x3FFFFFFF if prev & 1 else 0)
            transmitted.append(word)
            prev = word & 3
        message = gps.decode(transmitted)
        extra: tuple[Any, ...] = (pad,)
    elif system == GALILEO_INAV:
        even = (words[0] << 96 | words[1] << 64 | words[2] << 32 | words[3]) >> 8
        odd = (words[4] << 96 | words[5] << 64 | words[6] << 32 | words[7]) >> 8
        message = galileo.decode_inav(even, odd)
        extra = ((words[3] & 0xFF, words[7] & 0xFF),)
    elif system in (BEIDOU_D1, BEIDOU_D2):
        pad = tuple(w >> 30 for w in words)
        data = (words[0] >> 4) & ((1 << 26) - 1)
        parities = [words[0] & 0xF]
        for w in words[1:]:
            data = data << 22 | (w >> 8) & 0x3FFFFF
            parities.append(w & 0xFF)
        computed = _bds_parities(data)
        if any(parities) and parities != computed:
            raise ParityError(f"BeiDou BCH parity fields {parities}, section 5.1.3 gives "
                              f"{computed} (and they are not all zero)")
        message = beidou.decode_data(data, d2=system == BEIDOU_D2)
        extra = (pad, tuple(parities))
    else:   # GLONASS
        string = (words[0] << 64 | words[1] << 32 | words[2]) >> 11
        message = glonass.decode(string, frame=words[3] & 0xFF or None)
        extra = (words[2] & 0x7FF, words[3])
    return Received(system, msg.sv_id, msg.sig_id, message, (header, *extra))


def _bds_parities(data: int) -> list[int]:
    out = [beidou.bch((data >> 198) & 0x7FF)]
    for k in range(9):
        info = (data >> (22 * (8 - k))) & 0x3FFFFF
        out.append(beidou.bch(info >> 11) << 4 | beidou.bch(info & 0x7FF))
    return out


def sfrbx_words(received: Received) -> tuple[int, ...]:
    """The UBX-RXM-SFRBX data words of ``received`` (from :func:`from_sfrbx`)."""
    system, message = received.system, received.message
    if system == GPS:
        (pad,) = received.carrier[1:]
        out = []
        prev = 0
        for p, word in zip(pad, gps.encode(message), strict=True):
            out.append(p << 30 | (word ^ (0x3FFFFFFF if prev & 1 else 0)))
            prev = word & 3
        return tuple(out)
    if system == GALILEO_INAV:
        ((pad_even, pad_odd),) = received.carrier[1:]
        even, odd = galileo.encode_inav(message)
        e, o = even << 8 | pad_even, odd << 8 | pad_odd
        return tuple((v >> s) & 0xFFFFFFFF for v in (e, o) for s in (96, 64, 32, 0))
    if system in (BEIDOU_D1, BEIDOU_D2):
        pad, parities = received.carrier[1:]
        data = beidou.encode_data(message)
        out = [pad[0] << 30 | (data >> 198) << 4 | parities[0]]
        for k in range(9):
            out.append(pad[k + 1] << 30 | ((data >> (22 * (8 - k))) & 0x3FFFFF) << 8
                       | parities[k + 1])
        return tuple(out)
    pad3, word4 = received.carrier[1:]
    s = glonass.encode(message) << 11 | pad3
    return ((s >> 64) & 0xFFFFFFFF, (s >> 32) & 0xFFFFFFFF, s & 0xFFFFFFFF, word4)


def sfrbx_fields(received: Received) -> dict[str, Any]:
    """Keyword arguments of ``gnsswire.ubx.RxmSfrbx`` for ``received``."""
    gnss_id, sig_id, freq_id, chn, version, reserved0 = received.carrier[0]
    words = sfrbx_words(received)
    return dict(gnss_id=gnss_id, sv_id=received.satellite, sig_id=sig_id, freq_id=freq_id,
                num_words=len(words), chn=chn, version=version, reserved0=reserved0, dwrd=words)


def to_sfrbx(system: str, satellite: int, message: Any, *, sig_id: int | None = None,
             freq_id: int = 0, chn: int = 0) -> dict[str, Any]:
    """Keyword arguments of an ``RxmSfrbx`` carrying ``message`` (pad bits zero), for encoders."""
    gnss_id = {GPS: 0, GALILEO_INAV: 2, BEIDOU_D1: 3, BEIDOU_D2: 3, GLONASS: 6}[system]
    if sig_id is None:
        sig_id = 1 if system == BEIDOU_D2 else 0
    if system == GPS:
        extra: tuple[Any, ...] = ((0,) * 10,)
    elif system == GALILEO_INAV:
        extra = ((0, 0),)
    elif system in (BEIDOU_D1, BEIDOU_D2):
        extra = ((0,) * 10, tuple(_bds_parities(beidou.encode_data(message))))
    else:
        extra = (0, 0)
    header = (gnss_id, sig_id, freq_id, chn, 2, 0)
    return sfrbx_fields(Received(system, satellite, sig_id, message, (header, *extra)))


# --- SkyTraq --------------------------------------------------------------------------------

_E6_GALILEO_SIGNALS = (0, 5)   # AN0039 0xE6 signal type: 0 E1, 5 E5b (the I/NAV signals)


def from_skytraq(msg: Any) -> Received:
    """The unit in a ``gnsswire.skytraq`` 0xE0, 0xE1, 0xE2, 0xE3 or 0xE6 message."""
    msg_id = getattr(type(msg), "MSG_ID", None)
    if msg_id == 0xE0:
        data = 0
        for w in msg.words:
            data = data << 24 | w
        return Received(GPS, msg.svid, 0, gps.decode_data(data), (0xE0, msg.sfid))
    if msg_id == 0xE1:
        bits = 0
        for b in msg.data:
            bits = bits << 8 | b
        string = msg.string << 80 | bits << 8
        string |= glonass.hamming(string)
        return Received(GLONASS, msg.svid - 64, 0, glonass.decode(string), (0xE1,))
    if msg_id in (0xE2, 0xE3):
        data = int.from_bytes(bytes(msg.data), "big")
        system = BEIDOU_D1 if msg_id == 0xE2 else BEIDOU_D2
        return Received(system, msg.svid - 200, 0,
                        beidou.decode_data(data, d2=msg_id == 0xE3), (msg_id, msg.sfid))
    if msg_id == 0xE6:
        gnss, signal = msg.gnss_signal & 0xF, msg.gnss_signal >> 4
        if gnss != 3 or signal not in _E6_GALILEO_SIGNALS:
            raise Unsupported(f"SkyTraq 0xE6 GNSS type {gnss} signal {signal}: AN0039 prints "
                              f"the word layout of Galileo I/NAV (E1, E5b) only")
        words = tuple(msg.words)
        if len(words) != 8:
            raise FieldError(f"Galileo I/NAV in 0xE6 is 8 words, got {len(words)}")
        even = (words[0] << 96 | words[1] << 64 | words[2] << 32 | words[3]) >> 8
        odd = (words[4] << 96 | words[5] << 64 | words[6] << 32 | words[7]) >> 8
        return Received(GALILEO_INAV, msg.svid, signal, galileo.decode_inav(even, odd),
                        (0xE6, msg.version, msg.gnss_signal, (words[3] & 0xFF, words[7] & 0xFF)))
    raise Unsupported(f"{type(msg).__qualname__} does not carry navigation data units")


def skytraq_fields(received: Received) -> dict[str, Any]:
    """Keyword arguments of the SkyTraq message ``received`` came from (or would)."""
    msg_id = received.carrier[0]
    message = received.message
    if msg_id == 0xE0:
        data = gps.encode_data(message)
        words = tuple((data >> (24 * (9 - i))) & 0xFFFFFF for i in range(10))
        return dict(svid=received.satellite, sfid=received.carrier[1], words=words)
    if msg_id == 0xE1:
        string = glonass.encode(message)
        return dict(svid=received.satellite + 64, string=(string >> 80) & 0xF,
                    data=tuple((string >> s) & 0xFF for s in range(72, 0, -8)))
    if msg_id in (0xE2, 0xE3):
        data = beidou.encode_data(message)
        return dict(svid=received.satellite + 200, sfid=received.carrier[1],
                    data=tuple(data.to_bytes(28, "big")))
    _, version, gnss_signal, (pad_even, pad_odd) = received.carrier
    even, odd = galileo.encode_inav(message)
    e, o = even << 8 | pad_even, odd << 8 | pad_odd
    words = tuple((v >> s) & 0xFFFFFFFF for v in (e, o) for s in (96, 64, 32, 0))
    return dict(version=version, gnss_signal=gnss_signal, svid=received.satellite,
                length=8, words=words)


def to_skytraq(system: str, satellite: int, message: Any, *, signal: int = 0) -> dict[str, Any]:
    """Keyword arguments of the SkyTraq message carrying ``message``, for encoders.

    GPS gives a 0xE0, GLONASS 0xE1, BeiDou D1 and D2 0xE2 and 0xE3, Galileo
    I/NAV 0xE6 (``signal`` 0 for E1, 5 for E5b).
    """
    if system == GPS:
        carrier: tuple[Any, ...] = (0xE0, message.subframe)
    elif system == GLONASS:
        carrier = (0xE1,)
    elif system in (BEIDOU_D1, BEIDOU_D2):
        carrier = (0xE2 if system == BEIDOU_D1 else 0xE3, message.fraid)
    else:
        carrier = (0xE6, 1, signal << 4 | 3, (0, 0))
    return skytraq_fields(Received(system, satellite, signal, message, carrier))


# --- one assembler for every system -----------------------------------------------------------

class Assembler:
    """Feeds :class:`Received` units to the assembler of their system.

    :meth:`push` returns the ephemeris a unit completes (a
    :class:`gps.Ephemeris`, :class:`galileo.InavEphemeris`,
    :class:`beidou.Ephemeris` or :class:`glonass.Ephemeris`), or ``None``.
    GLONASS strings are assembled per satellite and signal; the others per
    satellite.
    """

    def __init__(self) -> None:
        self.gps = gps.Assembler()
        self.galileo = galileo.InavAssembler()
        self.beidou = beidou.Assembler()
        self.glonass = glonass.Assembler()

    def push(self, received: Received) -> Any:
        system, message = received.system, received.message
        if system == GPS:
            return self.gps.push(received.satellite, message)
        if system == GALILEO_INAV:
            if message.page_type or message.page_type_odd:
                return None
            return self.galileo.push(received.satellite, galileo.inav_word(message))
        if system in (BEIDOU_D1, BEIDOU_D2):
            return self.beidou.push(received.satellite, message)
        return self.glonass.push((received.satellite, received.signal), message)
