"""Write SRC to DST with the text of HEADER prepended as '#' comment lines.

usage: add_header.py SRC DST HEADER
"""

import os
import sys

src, dst, header = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(src).read()
os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, "w") as f:
    for line in open(header).read().splitlines():
        f.write(("# " + line).rstrip() + "\n")
    f.write(body)
