"""Cyclic redundancy checks in the parameter model of the CRC catalogue.

Each CRC is described by the catalogue's parameters (width, poly, init, refin,
refout, xorout) and carries the catalogue's check value: the CRC of the nine
ASCII bytes ``123456789``. The catalogue is Greg Cook's "Catalogue of
parametrised CRC algorithms", https://reveng.sourceforge.io/crc-catalogue/
(retrieved 2026-11-13; staged in refs/).

CRCs the wire formats use:

- RTCM 10403.3 section 4.2: CRC-24Q, generator bits 0, 1, 3, 4, 5, 6, 7, 10,
  11, 14, 17, 18, 23 and 24 (poly 0x864CFB), "using a seed of 0", over the
  bits from the preamble to the end of the message, parity bit p1 the
  coefficient of X^23. That is MSB-first with no reflection and no final XOR,
  the same parameters as the catalogue's CRC-24/LTE-A.
- SPARTN v2.0.3 Table 7.1, TF006: a 4-bit frame CRC, poly 0x09, initialised
  at zero, input and output reflected, zero final XOR, over the 20 bits of
  TF002 to TF005 followed by four zero bits. The catalogue has no entry with
  these parameters, so it has no catalogue check value; the tests check it
  against the polynomial division done bit by bit.
- SPARTN v2.0.3 Table 7.2, TF018, selected by TF005:

  ===== ================ ============ ============== ==============
  TF005 spec name        poly         initialisation final
  ===== ================ ============ ============== ==============
  0     CRC-8-CCITT      0x07         none           none
  1     CRC-16-CCITT     0x1021       none           none
  2     CRC-24-Radix-64  0x864CFB     none           none
  3     CRC-32-CCITT     0x04C11DB7   0xFFFFFFFF     XOR 0xFFFFFFFF
  ===== ================ ============ ============== ==============

  AMBIGUOUS: Table 7.2 does not say whether these four are reflected, though
  Table 7.1 says so explicitly for the CRC-4. Read literally (no reflection,
  initialisation zero where it says "none") they are CRC-8/SMBUS,
  CRC-16/XMODEM, CRC-24/LTE-A and CRC-32/BZIP2. Two of the names suggest
  other readings: "Radix-64" is the OpenPGP armour checksum, which
  initialises with 0xB704CE (CRC-24/OPENPGP), and the usual 32-bit CRC with
  this initialisation and final XOR is reflected (CRC-32/ISO-HDLC, zlib's).
  Both readings of each are provided here, each with the catalogue's check
  value. The ``spartn`` codec takes the literal reading
  (gnsswire-spartn's README, "Limitations").
"""

from dataclasses import dataclass, field


def _reflect(value: int, width: int) -> int:
    out = 0
    for _ in range(width):
        out = (out << 1) | (value & 1)
        value >>= 1
    return out


@dataclass(frozen=True, slots=True)
class Crc:
    """A CRC in catalogue parameters; call it on bytes to get the CRC as an int."""

    name: str
    width: int
    poly: int
    init: int
    refin: bool
    refout: bool
    xorout: int
    check: int | None   # catalogue check value for b"123456789"; None if not catalogued
    _table: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not 1 <= self.width <= 64:
            raise ValueError(f"CRC width {self.width} outside 1..64")
        top = 1 << self.width
        for label in ("poly", "init", "xorout"):
            if not 0 <= getattr(self, label) < top:
                raise ValueError(f"{label} does not fit {self.width} bits")
        if self.refin:
            # Register held reflected; process each byte LSB first.
            rpoly = _reflect(self.poly, self.width)
            table = []
            for byte in range(256):
                reg = byte
                for _ in range(8):
                    reg = (reg >> 1) ^ rpoly if reg & 1 else reg >> 1
                table.append(reg)
        else:
            # Register held in a window at least 8 bits wide so that widths
            # below 8 can take a whole byte at a time.
            shift = max(self.width, 8) - self.width
            hi = 1 << (max(self.width, 8) - 1)
            mask = (1 << max(self.width, 8)) - 1
            p = self.poly << shift
            table = []
            for byte in range(256):
                reg = byte << (max(self.width, 8) - 8)
                for _ in range(8):
                    reg = ((reg << 1) ^ p if reg & hi else reg << 1) & mask
                table.append(reg)
        object.__setattr__(self, "_table", tuple(table))

    def __call__(self, data: bytes) -> int:
        table = self._table
        if self.refin:
            reg = _reflect(self.init, self.width)
            for b in data:
                reg = (reg >> 8) ^ table[(reg ^ b) & 0xFF]
            if not self.refout:
                reg = _reflect(reg, self.width)
        else:
            window = max(self.width, 8)
            shift = window - self.width
            mask = (1 << window) - 1
            reg = self.init << shift
            for b in data:
                reg = ((reg << 8) & mask) ^ table[((reg >> (window - 8)) ^ b) & 0xFF]
            reg >>= shift
            if self.refout:
                reg = _reflect(reg, self.width)
        return reg ^ self.xorout


class CrcSlices:
    """The CRC of any slice of one buffer, in time that does not grow with the slice.

    For a framer's resynchronising scan, which checks a CRC over the length a
    candidate frame start claims at every candidate: done directly, a run of
    false starts that each claim a long frame costs a full-length CRC per
    byte. Here each call costs a few operations, plus one pass over bytes
    no earlier call has covered.

    Only for CRCs that are not reflected and whose width is a whole number of
    bytes (every CRC the formats use but the CRC-4). With ``P(k)`` the
    register after the bytes from a base position to ``k``, starting at
    zero, the register of ``buf[a:b]`` starting at zero is ``P(b) ^ P(a) *
    x**(8 * (b - a)) mod poly`` (the register is linear in its start value),
    and a start value ``init`` adds ``init * x**(8 * (b - a)) mod poly``.
    The base moves forward when the slices asked for do, so memory stays
    bounded by about ``window`` entries plus the longest slice.
    """

    __slots__ = ("crc", "_buf", "_base", "_p", "_pow", "_mask", "window")

    def __init__(self, crc: Crc, buf: bytes, window: int = 1 << 16) -> None:
        if crc.refin or crc.refout or crc.width % 8:
            raise ValueError(f"{crc.name}: only unreflected CRCs of whole bytes")
        self.crc = crc
        self._buf = buf
        self._base = -1
        self._p: list[int] = []
        self._pow = [1]           # x**(8n) mod poly, by n
        self._mask = (1 << crc.width) - 1
        self.window = window

    def _step(self, reg: int, byte: int) -> int:
        w = self.crc.width
        return ((reg << 8) & self._mask) ^ self.crc._table[(reg >> (w - 8)) ^ byte]

    def _times(self, a: int, n: int) -> int:
        """``a * x**(8n) mod poly``."""
        pow_ = self._pow
        while len(pow_) <= n:
            pow_.append(self._step(pow_[-1], 0))
        k, product = pow_[n], 0
        while a:                  # carry-less product of a and k
            low = a & -a
            product ^= k << (low.bit_length() - 1)
            a ^= low
        w = self.crc.width
        reg = 0                   # product mod poly: the high half through the table
        for byte in (product >> w).to_bytes(w // 8, "big"):
            reg = self._step(reg, byte)
        return reg ^ (product & self._mask)

    def __call__(self, start: int, end: int) -> int:
        """The CRC of ``buf[start:end]``, the same as ``crc(buf[start:end])``."""
        if not 0 <= start <= end <= len(self._buf):
            raise ValueError(f"slice {start}:{end} outside a buffer of {len(self._buf)} bytes")
        if not self._p or start < self._base or start - self._base > self.window:
            self._base, self._p = start, [0]
        p, base = self._p, self._base
        if base + len(p) <= end:
            reg = p[-1]
            table, mask, shift = self.crc._table, self._mask, self.crc.width - 8
            for byte in self._buf[base + len(p) - 1:end]:
                reg = ((reg << 8) & mask) ^ table[(reg >> shift) ^ byte]
                p.append(reg)
        reg = p[end - base] ^ self._times(p[start - base] ^ self.crc.init, end - start)
        return reg ^ self.crc.xorout


CRC24Q = Crc("CRC-24Q", 24, 0x864CFB, 0, False, False, 0, 0xCDE703)

CRC4_SPARTN = Crc("CRC-4/SPARTN", 4, 0x9, 0, True, True, 0, None)

CRC8_SMBUS = Crc("CRC-8/SMBUS", 8, 0x07, 0, False, False, 0, 0xF4)
CRC16_XMODEM = Crc("CRC-16/XMODEM", 16, 0x1021, 0, False, False, 0, 0x31C3)
CRC24_LTE_A = Crc("CRC-24/LTE-A", 24, 0x864CFB, 0, False, False, 0, 0xCDE703)
CRC32_BZIP2 = Crc("CRC-32/BZIP2", 32, 0x04C11DB7, 0xFFFFFFFF, False, False, 0xFFFFFFFF, 0xFC891918)

CRC16_IBM_3740 = Crc("CRC-16/IBM-3740", 16, 0x1021, 0xFFFF, False, False, 0, 0x29B1)
CRC24_OPENPGP = Crc("CRC-24/OPENPGP", 24, 0x864CFB, 0xB704CE, False, False, 0, 0x21CF02)
CRC32_ISO_HDLC = Crc("CRC-32/ISO-HDLC", 32, 0x04C11DB7, 0xFFFFFFFF, True, True, 0xFFFFFFFF, 0xCBF43926)
