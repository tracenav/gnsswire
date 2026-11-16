# Third-party notices for the nmea test data

The code of `gnsswire-nmea` is under the MIT licence (`LICENSE`). One test
data file is not this project's work and carries the notice below. It is not
in the wheel; it is in the sdist and the repository.

| File | What it is |
|---|---|
| `tests/data/gpsd-zed-f9p.nmea` | the GGA and ZDA sentences of gpsd's regression log `test/daemon/ublox-zed-f9p-nmea.log`, unchanged and in file order (`tests/make_data/extract_gpsd.py`) |

## GPSD project

The log's header reads: "This file is Copyright 2010 by the GPSD project.
BSD terms apply: see the file COPYING in the distribution root for details."
The text below is gpsd's `COPYING`, unchanged, from gitlab.com/gpsd/gpsd
(branch master; last changed in commit
0e40daf5e7b8d9686cf34a1b492205aab90b0328; retrieved 2026-11-15; sha256
fdf339997bbca9eaf507476b82fbcac608fc39a3d89b86b51e16db4c9f933716).

```text
                          COPYRIGHTS

Compilation copyright is held by the GPSD project.  All rights reserved.

GPSD project copyrights are assigned to the project lead, currently
Eric S. Raymond. Other portions of the GPSD code are Copyright
1997, 1998, 1999, 2000, 2001, 2002 by Remco Treffkorn, and others
Copyright 2005 by Eric S. Raymond.  For other copyrights, see
individual files.

                           LICENSE
              (SPDX short identifier: BSD-2-Clause)

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER
OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
