# How `../data/rtklib-decoded.txt` was made

Nothing here runs under pytest. The scripts are kept so that the test data
can be checked and regenerated.

The frames are this project's own: seeded synthetic ephemerides of GPS
(three satellites), Galileo I/NAV (three, word types 0 to 6), BeiDou D1
(two) and D2 (one) and GLONASS (three, strings 1 to 5), encoded by
`gnsswire.nav` (parity, BCH code, Hamming code and CRC computed) and
`gnsswire.ubx` into UBX-RXM-SFRBX, after a UBX-RXM-RAWX without
measurements that gives the receiver time (week 2400). The independent part
is the decoder: RTKLIB (BSD 2-clause), through pyrtklib 0.2.7 from PyPI,
installed into a throwaway virtual environment outside this workspace.
pyrtklib 0.2.7 has wheels for CPython 3.13 and older only.

```sh
uv venv --python 3.12 /tmp/enc/venv && uv pip install --python /tmp/enc/venv/bin/python pyrtklib==0.2.7
uv run python -I make_data/gen_frames.py /tmp/nav-frames.txt
uv run --no-project --python /tmp/enc/venv/bin/python make_data/rtklib_decode.py \
    /tmp/nav-frames.txt data/rtklib-decoded.txt
```

Both steps give the same bytes on every run. `rtklib_decode.py` feeds the
frames, in order, to RTKLIB's `input_ubx` and writes each frame's hex,
followed, when RTKLIB reported an ephemeris, by its `eph_t` or `geph_t`
fields as JSON. RTKLIB's `input_ubx` gives no Galileo ephemeris for these
frames, nor for a receiver's own; for Galileo the script takes the 128-bit
words out of the frames' pages itself and hands word types 0 to 6 to
RTKLIB's `decode_gal_inav` (which returns nothing unless all seven are
present). It takes word type k at byte 16k of its buffer, which was found
by trial, not by reading RTKLIB.

`test_rtklib.py` assembles the same frames with `gnsswire.nav.carriers`
and checks that every ephemeris is RTKLIB's, field for field, once scaled
by the ICDs' factors: issue of data, accuracy, health, times of week,
clock and group delay terms, and the Keplerian elements (GPS, Galileo,
BeiDou); slot, frequency channel, tb, En, position, velocity, acceleration,
tau_n, gamma_n and delta tau_n (GLONASS). RTKLIB's own readings (its week
resolution for BeiDou, its fit interval, its packed health words) are not
compared; the test's docstring says which.
