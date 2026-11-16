# Third-party notices for the rtcm3 test data

The code of `gnsswire-rtcm3` is under the MIT licence (`LICENSE`). Eight test
data files are not only this project's work and carry the notices below.
None of them is in the wheel; all are in the sdist and the repository.

| File | What it is |
|---|---|
| `tests/data/public.hex` | RTCM 3 frames copied byte for byte from RTKLIB's test data, `test/data/rcvraw/GMSD7_20121014.rtcm3` and `test/data/rcvraw/testglo.rtcm3` |
| `tests/data/rtklib.hex` | RTCM 3 frames produced by RTKLIB's encoder (through pyrtklib 0.2.7) from the files above, from a public IGS broadcast navigation file and from seeded synthetic data |
| `tests/data/rtklib-msm.hex` | RTCM 3 frames produced by RTKLIB's encoder (through pyrtklib 0.2.7) from the observations of the files above and from seeded synthetic data: MSM1 to MSM7, and 1044 |
| `tests/data/rtklib-station.hex` | RTCM 3 frames produced by RTKLIB's encoder (through pyrtklib 0.2.7) from seeded synthetic station data: 1006 and 1005 |
| `tests/data/rtklib-igs.hex` | RTCM 3 frames of message 4076 (IGS SSR): produced by RTKLIB's encoder (through pyrtklib 0.2.7) from seeded synthetic SSR corrections, and frames built by this project for RTKLIB's decoder to read |
| `tests/data/rtklib-igs-decoded.json` | RTKLIB's decoder's reading (through pyrtklib 0.2.7) of every frame of `rtklib-igs.hex` |
| `tests/data/rtklib-antenna.hex` | RTCM 3 frames produced by RTKLIB's encoder (through pyrtklib 0.2.7) from seeded synthetic antenna and receiver descriptors: 1007, 1008 and 1033 |
| `tests/data/rtklib-antenna-decoded.json` | What RTKLIB's encoder was given for each frame of `rtklib-antenna.hex`, and its decoder's reading (through pyrtklib 0.2.7) of that frame |

How the files were made is in `tests/make_data/README.md`.

## RTKLIB

All eight files come from RTKLIB, its data, its encoder or its decoder, which is distributed
under the BSD 2-clause licence. The text below is RTKLIB's `license.txt`,
unchanged, from github.com/rtklibexplorer/RTKLIB (branch master; last
changed in commit 718ff38a98ce95ff16439b9a74780e4014f97894; retrieved
2026-11-15; sha256
219747832d49ee958457b2934080ab8d94bd9d8e45fcb1c36f89776fd2c5ed8a).

```text

The RTKLIB software package is distributed under the following BSD 2-clause
license. Users are permitted to develop, produce or sell their own non-
commercial or commercial products utilizing, linking or including RTKLIB as long
as they comply with the license.

--------------------------------------------------------------------------------

         Copyright (c) 2007-2020, T. Takasu, All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

Redistributions of source code must retain the above copyright notice, this list
of conditions and the following disclaimer. Redistributions in binary form must
reproduce the above copyright notice, this list of conditions and the following
disclaimer in the documentation and/or other materials provided with the
distribution.

The software package includes some companion executive binaries or shared
libraries necessary to execute APs on Windows. These licenses succeed to the
original ones of these software.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

--------------------------------------------------------------------------------

Notes:
Previous versions of RTKLIB until ver. 2.4.1 had been distributed under GPLv3
license.

```

## IGS data

The files also hold data of the International GNSS Service (IGS):

- `public.hex`: the RTKLIB capture `GMSD7_20121014.rtcm3` is a stream of the
  IGS station GMSD (Nakatane, Japan; its IGS station notices are filed by
  JAXA), 2012-10-14.
- `rtklib-msm.hex`: the observations it re-encodes come from that stream
  (and from `testglo.rtcm3`).
- `rtklib.hex`: the ephemerides are encoded from the IGS merged broadcast
  navigation file `BRDC00WRD_R_20263000000_01D_MN.rnx` (2026-10-27), as
  served by the BKG GNSS Data Center (igs.bkg.bund.de, Bundesamt für
  Kartographie und Geodäsie).

The IGS "Data and Product Disclaimer and Terms of Use" (5 August 2020,
igs.org/wp-content/uploads/2020/09/IGS-Data-and-Product-Disclaimer-and-Terms-of-Use-200805.pdf)
asks: "By accessing data, products, and any other information from the IGS,
users agree to appropriately cite and attribute these resources to providers
and their sponsors, acknowledgment of IGS and its contributing
organizations, and to adherence to professional and ethical standards." It
also states that IGS makes no guarantee of the quality, reliability,
usability, availability or suitability of its data and products for any
purpose.

Acknowledgement: these data are provided by the International GNSS Service
and its contributing organisations, among them the operator of station GMSD
and the BKG GNSS Data Center. The citation the IGS gives (igs.org/documents,
"Citation"):

> Johnston, G., Riddell, A., Hausler, G. (2017). The International GNSS
> Service. Teunissen, Peter J.G., & Montenbruck, O. (Eds.), Springer
> Handbook of Global Navigation Satellite Systems (1st ed., pp. 967-982).
> Cham, Switzerland: Springer International Publishing. DOI:
> 10.1007/978-3-319-42928-1.
