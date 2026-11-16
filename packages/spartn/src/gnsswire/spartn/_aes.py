"""AES-128 (forward cipher only) and counter mode, in pure Python.

Sources:

- FIPS 197, "Advanced Encryption Standard (AES)": the S-box from its
  definition in section 5.1.1 (multiplicative inverse in GF(2^8) modulo
  x^8 + x^4 + x^3 + x + 1, then the affine transformation with c = 0x63),
  ShiftRows, MixColumns and AddRoundKey of sections 5.1.2 to 5.1.4, and the
  key expansion of section 5.2 for Nk = 4, Nr = 10. The state is the input
  bytes in column order (section 3.4: ``s[r, c] = in[r + 4c]``).
- Counter mode: NIST SP 800-38A section 6.5, with the counter block of
  RFC 3686 section 2.1 (the 96 most significant bits fixed, the least
  significant 32 bits a big-endian block counter starting at one), which is
  what SPARTN v2.0.3 section 8.15.1 specifies.

Only encryption of single blocks is needed: counter mode decrypts with the
forward cipher. Constant-time behaviour is not a goal; this decodes
broadcast corrections and is not meant for protecting secrets.
"""

from ._frame import Error


def _xtime(a: int) -> int:
    """Multiplication by x in GF(2^8) (FIPS 197 section 4.2.1)."""
    a <<= 1
    return a ^ 0x11B if a & 0x100 else a


def _sbox() -> tuple[int, ...]:
    # Inverses from powers of the generator x + 1 (0x03): if a = g^k then a^-1 = g^(255-k).
    power, log = [0] * 255, [0] * 256
    a = 1
    for k in range(255):
        power[k], log[a] = a, k
        a ^= _xtime(a)   # a·(x + 1)
    inverse = [0] + [power[(255 - log[a]) % 255] for a in range(1, 256)]
    box = []
    for a in range(256):
        b = inverse[a]
        s = 0x63
        for i in range(8):
            bit = ((b >> i) ^ (b >> ((i + 4) % 8)) ^ (b >> ((i + 5) % 8))
                   ^ (b >> ((i + 6) % 8)) ^ (b >> ((i + 7) % 8))) & 1
            s ^= bit << i
        box.append(s)
    return tuple(box)


SBOX = _sbox()
_X2 = tuple(_xtime(a) for a in range(256))
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def expand_key(key: bytes) -> tuple[tuple[int, ...], ...]:
    """The eleven 16-byte round keys of an AES-128 key (section 5.2)."""
    if len(key) != 16:
        raise Error(f"AES-128 needs a 16-byte key, got {len(key)} bytes")
    w = [list(key[4 * i:4 * i + 4]) for i in range(4)]
    for i in range(4, 44):
        temp = list(w[i - 1])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]                 # RotWord
            temp = [SBOX[b] for b in temp]             # SubWord
            temp[0] ^= _RCON[i // 4 - 1]
        w.append([a ^ b for a, b in zip(w[i - 4], temp)])
    return tuple(tuple(b for word in w[4 * r:4 * r + 4] for b in word) for r in range(11))


def encrypt_block(round_keys: tuple[tuple[int, ...], ...], block: bytes) -> bytes:
    """The cipher of section 5.1 on one 16-byte block."""
    if len(block) != 16:
        raise Error("an AES block is 16 bytes")
    s = [b ^ k for b, k in zip(block, round_keys[0])]
    for rnd in range(1, 11):
        s = [SBOX[b] for b in s]                                        # SubBytes
        s = [s[r + 4 * ((c + r) % 4)] for c in range(4) for r in range(4)]   # ShiftRows
        if rnd < 10:                                                    # MixColumns
            mixed = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                t = a0 ^ a1 ^ a2 ^ a3
                mixed += [a0 ^ t ^ _X2[a0 ^ a1], a1 ^ t ^ _X2[a1 ^ a2],
                          a2 ^ t ^ _X2[a2 ^ a3], a3 ^ t ^ _X2[a3 ^ a0]]
            s = mixed
        s = [b ^ k for b, k in zip(s, round_keys[rnd])]                 # AddRoundKey
    return bytes(s)


def ctr(key: bytes, nonce: bytes, data: bytes) -> bytes:
    """AES-128-CTR of ``data`` with counter blocks ``nonce`` (12 bytes) || counter from 1.

    Encryption and decryption are the same operation.
    """
    if len(nonce) != 12:
        raise Error("the counter block's fixed part is 12 bytes (96 bits)")
    keys = expand_key(bytes(key))
    out = bytearray()
    for i in range(0, len(data), 16):
        counter = (i // 16 + 1) & 0xFFFF_FFFF
        stream = encrypt_block(keys, bytes(nonce) + counter.to_bytes(4, "big"))
        out += bytes(a ^ b for a, b in zip(data[i:i + 16], stream))
    return bytes(out)
