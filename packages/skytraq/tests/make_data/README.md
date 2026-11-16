# How `../data/rtklib-decoded.txt` was made

Nothing here runs under pytest. The scripts are kept so that the test data
can be checked and regenerated.

There is no public SkyTraq capture this project can use, so the frames are
this project's own: seeded synthetic measurements encoded by
`gnsswire.skytraq`. The independent part is the decoder: RTKLIB's
`input_stq` (BSD 2-clause), through pyrtklib 0.2.7 from PyPI, installed into
a throwaway virtual environment outside this workspace. pyrtklib 0.2.7 has
wheels for CPython 3.13 and older only.

```sh
uv venv --python 3.12 /tmp/enc/venv && uv pip install --python /tmp/enc/venv/bin/python pyrtklib==0.2.7
uv run python -I make_data/gen_frames.py /tmp/stq-frames.txt
uv run --no-project --python /tmp/enc/venv/bin/python make_data/rtklib_decode.py \
    /tmp/stq-frames.txt data/rtklib-decoded.txt
```

Both steps give the same bytes on every run. `gen_frames.py` writes 20
epochs of MEAS_TIME (0xDC), RAW_MEAS (0xDD) and EXT_RAW_MEAS (0xE5) with
random satellites of every GNSS type and signal the note lists.
`rtklib_decode.py` feeds them to RTKLIB in order and writes, after each
frame for which RTKLIB returned observations, the system, PRN, signal code,
pseudorange, carrier phase, Doppler and SNR of every observation, as JSON.

`test_messages.py` checks that RTKLIB returns one observation per channel,
in order, with the pseudorange, carrier phase and Doppler our integer fields
hold as IEEE 754 bits, and an SNR of CN0 · 1000 (RTKLIB's unit is
0.001 dB-Hz). RTKLIB's system and PRN are not compared: they are its
reading of the SVID conventions (it takes 0xDD SVIDs above 200 for QZSS,
where AN0039 says BeiDou), which this codec leaves to the caller.
