# How `../data/*.hex` were made

Nothing here runs under pytest. The scripts are kept so that the test data
can be checked and regenerated. Downloads go into a fresh directory under
`/tmp`, never into the repository.

Inputs, all public:

- RTKLIB, `github.com/rtklibexplorer/RTKLIB` (BSD 2-clause), shallow clone:
  `test/data/rcvraw/GMSD7_20121014.rtcm3` and `test/data/rcvraw/testglo.rtcm3`,
  reference-station stream captures with 1005, 1019, 1020, 1033 and
  observation messages.
- IGS merged broadcast navigation, RINEX 3.05, from BKG without login:
  `https://igs.bkg.bund.de/root_ftp/IGS/BRDC/2026/300/BRDC00WRD_R_20263000000_01D_MN.rnx.gz`
  (GPS, GLONASS, Galileo, BeiDou and others, 2026-10-27), gunzipped.
- pyrtklib 0.2.7 from PyPI, a Python binding of RTKLIB, installed into a
  throwaway virtual environment outside this workspace. RTKLIB is the
  independent encoder; it shares no code with gnsswire.

## Step 1: `public.hex`

```sh
uv run python -I make_data/extract_public.py \
    1005,1019,1020,1033,1042,1044,1045,1046,1230,1074,1084,1094,1124,1077:6,1087:6,1117:6,1127:6 \
    /tmp/public.hex GMSD7_20121014.rtcm3 testglo.rtcm3
uv run python -I make_data/add_header.py /tmp/public.hex data/public.hex header.txt
```

The frames are the captures' own bytes; `gnsswire.rtcm3.scan` only cuts
them out. Of the listed types the captures contain 1005, 1019, 1020 and 1033,
all kept, and the MSM7 types 1077, 1087, 1117 and 1127 (257 frames each in
GMSD7), of which `:6` keeps the first six. The 0.1.0 file was made with the
same command without 1044 and the MSM7 types; its frames are the same
lines, in the same order, less the MSM7 ones.

## Step 2: `rtklib.hex`

```sh
uv venv /tmp/enc/venv && uv pip install --python /tmp/enc/venv/bin/python pyrtklib==0.2.7
uv run --no-project --python /tmp/enc/venv/bin/python make_data/gen_rtklib.py \
    GMSD7_20121014.rtcm3 BRDC00WRD_R_20263000000_01D_MN.rnx /tmp/rtklib.hex testglo.rtcm3
uv run python -I make_data/add_header.py /tmp/rtklib.hex data/rtklib.hex header.txt
```

`gen_rtklib.py` is seeded and gives the same bytes on every run. It encodes

- the first ephemeris of each satellite in the navigation file as 1019,
  1020, 1042, 1045 (F/NAV records) and 1046 (I/NAV records);
- the observations RTKLIB decodes from the captures as MSM4: BeiDou (from
  GMSD's MSM7) as 1124, GLONASS (from testglo's 1012) as 1084. RTKLIB hands
  back only one system per epoch from these files, so GPS and Galileo
  observations come from the next item;
- seeded random observations for GPS, Galileo and BeiDou as 1074, 1094
  and 1124, with random satellite and signal subsets;
- seeded random station data as 1005, 1033 and 1230. RTKLIB always sends
  all four 1230 biases (DF422 = 1111); other masks are covered by the
  generated messages in `test_messages.py`.

## Step 3: `rtklib-msm.hex`

pyrtklib 0.2.7 has wheels for CPython 3.13 and older only, so the throwaway
environment needs one of those (`uv venv --python 3.12 /tmp/enc/venv`).

```sh
uv run --no-project --python /tmp/enc/venv/bin/python make_data/gen_rtklib_msm.py \
    GMSD7_20121014.rtcm3 testglo.rtcm3 /tmp/rtklib-msm.hex
uv run python -I make_data/add_header.py /tmp/rtklib-msm.hex data/rtklib-msm.hex header.txt
```

`gen_rtklib_msm.py` is seeded and gives the same bytes on every run. It
needs no navigation file. It encodes

- the observations RTKLIB decodes from the captures as MSM1 to MSM7, three
  non-empty frames per message number: BeiDou (from GMSD's MSM7) as 1121 to
  1127, GLONASS (from testglo's 1012) as 1081 to 1087;
- seeded random observations for GPS, GLONASS, Galileo, SBAS, QZSS and
  BeiDou as MSM1 to MSM7 of each (1071 to 1127), six epochs each;
- seeded random QZSS ephemerides as 1044.

## Step 4: `rtklib-station.hex`

In the same throwaway environment as step 3:

```sh
uv run --no-project --python /tmp/enc/venv/bin/python python -I \
    make_data/gen_rtklib_station.py /tmp/rtklib-station.hex
uv run python -I make_data/add_header.py /tmp/rtklib-station.hex data/rtklib-station.hex header.txt
```

`gen_rtklib_station.py` is seeded, gives the same bytes on every run and
needs no input file. It encodes seeded random station data as 1006, with
antenna heights of 0, 6.5535 m (the top of DF028's range) and random ones,
and the same data as 1005.

## Step 5: `rtklib-igs.hex` and `rtklib-igs-decoded.json`

In the same throwaway environment as step 3 (`header-igs.txt` holds the
leading `#` block of `rtklib-igs.hex`, without the `# `):

```sh
uv run --no-project --python /tmp/enc/venv/bin/python python -I \
    make_data/gen_rtklib_igs.py /tmp/rtklib-igs.hex data/rtklib-igs-decoded.json
uv run python -I make_data/add_header.py /tmp/rtklib-igs.hex data/rtklib-igs.hex header-igs.txt
```

`gen_rtklib_igs.py` is seeded, gives the same bytes on every run and needs
no input file. It

- fills RTKLIB's SSR state with seeded random corrections for five
  satellites of each system and encodes them with `gen_rtcm3` as message
  4076, sub-types 21 to 27, 41 to 47, 61 to 67, 81 to 87, 101 to 107 and
  121 to 127, three rounds (the second with the multiple message
  indicator set). RTKLIB has no encoder for IM201 (VTEC);
- builds, with this checkout's `gnsswire.rtcm3` (put on the path from the
  sources), code and phase bias frames of every system that carry each
  signal identifier 0 to 31 with a distinct non-zero bias;
- decodes every frame with a fresh RTKLIB decoder (`input_rtcm3`) and
  writes what it read into the JSON file, in RTKLIB's units and names.

## Step 6: `rtklib-antenna.hex` and `rtklib-antenna-decoded.json`

In the same throwaway environment as step 3 (`header-antenna.txt` holds the
leading `#` block of `rtklib-antenna.hex`, without the `# `):

```sh
uv run --no-project --python /tmp/enc/venv/bin/python python -I \
    make_data/gen_rtklib_antenna.py /tmp/rtklib-antenna.hex data/rtklib-antenna-decoded.json
uv run python -I make_data/add_header.py /tmp/rtklib-antenna.hex data/rtklib-antenna.hex \
    header-antenna.txt
```

`gen_rtklib_antenna.py` is seeded, gives the same bytes on every run and
needs no input file. It

- fills RTKLIB's station data with seeded random antenna and receiver
  descriptors and encodes each station with `gen_rtcm3` as 1007, 1008 and
  1033: every counter 0 (station ID 0, setup ID 0); every counter 31
  (station ID 4095, setup ID 255), once in printable ASCII and once in bytes
  0x01 to 0xFF; a 20-character antenna descriptor; and ten stations of
  random lengths 0 to 31, alternately printable ASCII and 0x01 to 0xFF.
  RTKLIB's strings end at 0x00, so no frame holds a 0x00 character;
- decodes every frame with a fresh RTKLIB decoder (`input_rtcm3`) and
  writes, frame by frame, what the encoder was given and what the decoder
  read, each string as the latin-1 text of its bytes, with the decoder's
  return value.

The header text of each `.hex` file is its leading `#` block.
