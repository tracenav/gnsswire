# Third-party notices for the nav test data

The code of `gnsswire-nav` is under the MIT licence (`LICENSE`). One test
data file is not only this project's work and carries the notice below. It
is not in the wheel; it is in the sdist and the repository.

| File | What it is |
|---|---|
| `tests/data/rtklib-decoded.txt` | UBX-RXM-SFRBX frames of this project (seeded synthetic navigation data, encoded by `gnsswire.nav` and `gnsswire.ubx`), each followed, where it completed an ephemeris, by the ephemeris RTKLIB (through pyrtklib 0.2.7) decoded from the frames |

How the file was made is in `tests/make_data/README.md`.

## RTKLIB

The decoded values are the output of RTKLIB, which is distributed under the
BSD 2-clause licence. The text below is RTKLIB's `license.txt`, unchanged,
from github.com/rtklibexplorer/RTKLIB (branch master; last changed in commit
718ff38a98ce95ff16439b9a74780e4014f97894; retrieved 2026-11-15; sha256
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
