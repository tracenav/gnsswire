"""AES-128 and counter mode against FIPS 197 and RFC 3686.

- FIPS 197: the S-box values of Figure 7 that the text cites (S(0x53) =
  0xED, section 5.1.1) and its first and last rows, the key expansion of
  Appendix A.1, the cipher example of Appendix B and the AES-128 example
  vector of Appendix C.1.
- RFC 3686 section 6, test vectors 1 to 3 (AES-128): counter blocks of a
  32-bit nonce, a 64-bit IV and a 32-bit block counter starting at one, the
  construction SPARTN v2.0.3 section 8.15.1 cites.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnsswire.spartn import _aes


def test_sbox():
    assert _aes.SBOX[0x53] == 0xED                       # section 5.1.1 example
    assert bytes(_aes.SBOX[:16]).hex() == "637c777bf26b6fc53001672bfed7ab76"
    assert bytes(_aes.SBOX[-16:]).hex() == "8ca1890dbfe6426841992d0fb054bb16"
    assert sorted(_aes.SBOX) == list(range(256))


def test_key_expansion_appendix_a1():
    keys = _aes.expand_key(bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c"))
    assert len(keys) == 11
    assert bytes(keys[1]).hex() == "a0fafe1788542cb123a339392a6c7605"   # w4 to w7
    assert bytes(keys[10]).hex() == "d014f9a8c9ee2589e13f0cc8b6630ca6"  # w40 to w43


@pytest.mark.parametrize(("key", "plain", "cipher"), [
    # Appendix B
    ("2b7e151628aed2a6abf7158809cf4f3c", "3243f6a8885a308d313198a2e0370734",
     "3925841d02dc09fbdc118597196a0b32"),
    # Appendix C.1
    ("000102030405060708090a0b0c0d0e0f", "00112233445566778899aabbccddeeff",
     "69c4e0d86a7b0430d8cdb78070b4c55a"),
])
def test_cipher_examples(key, plain, cipher):
    keys = _aes.expand_key(bytes.fromhex(key))
    assert _aes.encrypt_block(keys, bytes.fromhex(plain)).hex() == cipher


# RFC 3686 section 6: (key, nonce, IV, plaintext, ciphertext).
RFC3686 = [
    ("AE6852F8121067CC4BF7A5765577F39E", "00000030", "0000000000000000",
     "53696E676C6520626C6F636B206D7367", "E4095D4FB7A7B3792D6175A3261311B8"),
    ("7E24067817FAE0D743D6CE1F32539163", "006CB6DB", "C0543B59DA48D90B",
     "000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F",
     "5104A106168A72D9790D41EE8EDAD388EB2E1EFC46DA57C8FCE630DF9141BE28"),
    ("7691BE035E5020A8AC6E618529F9A0DC", "00E0017B", "27777F3F4A1786F0",
     "000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F20212223",
     "C1CF48A89F2FFDD9CF4652E9EFDB72D74540A42BDE6D7836D59A5CEAAEF3105325B2072F"),
]


@pytest.mark.parametrize(("key", "nonce", "iv", "plain", "cipher"), RFC3686)
def test_rfc3686_vectors(key, nonce, iv, plain, cipher):
    k, n = bytes.fromhex(key), bytes.fromhex(nonce + iv)
    assert _aes.ctr(k, n, bytes.fromhex(plain)).hex().upper() == cipher
    assert _aes.ctr(k, n, bytes.fromhex(cipher)).hex().upper() == plain


@settings(max_examples=50, derandomize=True, deadline=None)
@given(st.binary(min_size=16, max_size=16), st.binary(min_size=12, max_size=12),
       st.binary(max_size=100))
def test_ctr_is_its_own_inverse(key, nonce, data):
    out = _aes.ctr(key, nonce, data)
    assert len(out) == len(data)
    assert _aes.ctr(key, nonce, out) == data


def test_ctr_keystream_is_the_counter_blocks():
    key, nonce = bytes(range(16)), bytes(range(100, 112))
    keys = _aes.expand_key(key)
    stream = _aes.ctr(key, nonce, bytes(40))
    for i in range(3):
        block = _aes.encrypt_block(keys, nonce + (i + 1).to_bytes(4, "big"))
        assert stream[16 * i:16 * i + 16] == block[:len(stream[16 * i:16 * i + 16])]


def test_wrong_sizes_are_refused():
    with pytest.raises(ValueError, match="16-byte key"):
        _aes.ctr(bytes(32), bytes(12), b"x")
    with pytest.raises(ValueError, match="12 bytes"):
        _aes.ctr(bytes(16), bytes(16), b"x")
    with pytest.raises(ValueError):
        _aes.encrypt_block(_aes.expand_key(bytes(16)), bytes(15))
