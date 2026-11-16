# How `../data/rtklib-read.json` was made

Nothing here runs under pytest. The scripts are kept so that the test data
can be checked and regenerated.

The RINEX file is this project's own: seeded synthetic observations written
by `gnsswire.rinex`, laid out by the formats of RINEX 3.05 Tables A2 and A3.
The independent part is the reader: RTKLIB's `readrnx` (BSD 2-clause),
through pyrtklib 0.2.7 from PyPI, installed into a throwaway virtual
environment outside this workspace. pyrtklib 0.2.7 has wheels for CPython
3.13 and older only.

```sh
uv venv --python 3.12 /tmp/enc/venv && uv pip install --python /tmp/enc/venv/bin/python pyrtklib==0.2.7
uv run python -I make_data/gen_obs.py /tmp/synthetic.rnx
uv run --no-project --python /tmp/enc/venv/bin/python make_data/rtklib_read.py \
    /tmp/synthetic.rnx data/rtklib-read.json
```

Both steps give the same bytes on every run. `gen_obs.py` writes 30 epochs
of GPS, GLONASS, Galileo, BeiDou, QZSS and SBAS observations: one signal per
band with its C, L, D and S observation, about one in ten blank, LLI and SSI
digits or blanks, the receiver clock offset in half of the epochs, and the
trailing blanks of every record truncated. `rtklib_read.py` stores the file
and, for every observation RTKLIB holds, its time, satellite, signal,
pseudorange, carrier phase, Doppler, SNR and LLI.

`test_obs.py` checks that RTKLIB reads the values our fields hold: the same
pseudoranges and phases, the Doppler as the float32 RTKLIB keeps, the SNR in
RTKLIB's 0.001 dB-Hz, 0 for a blank or missing observation, and the LLI
with bits 0 and 1 only (RTKLIB drops bit 2).
