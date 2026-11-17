"""ANTEX 1.4 antenna calibration files: text to records of text fields and back.

An ANTEX file holds, per receiver or satellite antenna and per frequency,
the phase centre offset and the phase centre variations on a grid of zenith
(or nadir) and azimuth angles. It is read whole with :func:`read` and
written with :func:`write`, and ``write(read(text)) == text`` for every file
this module accepts. Every labelled line is a :class:`Record` (content and
label), every line of pattern values a :class:`Row`, as the text of their
columns; :func:`fields` gives a record's content as the frozen dataclass of
its columns, and :func:`number` a numeric field as the integer of its
digits. Nothing is scaled: offsets and pattern values are the file's
millimetres with two decimals, angles its degrees with one.

Source: "ANTEX: The Antenna Exchange Format, Version 1.4" (M. Rothacher,
R. Schmid, 15 September 2010), section 4; the readings taken are in
``_file`` and ``_records``.

Errors: every exception this codec raises for a file it cannot read or
records it cannot write is an :class:`Error` (a ``ValueError``):
:class:`Invalid`, :class:`Unsupported` (another format version), and the
error :func:`number` raises for a field that is not a number of its format.
"""

from ._file import (
    FREQUENCIES,
    SYSTEMS,
    Antenna,
    AntexFile,
    Pattern,
    read,
    write,
)
from ._records import (
    NOAZI,
    TABLE,
    Blank,
    Col,
    Comment,
    Dazi,
    Epoch,
    Error,
    Frequencies,
    FrequencyCode,
    Grid,
    Invalid,
    Method,
    Offset,
    PcvType,
    Record,
    Row,
    SinexCode,
    TypeSerial,
    Unsupported,
    Version,
    columns,
    fields,
    number,
    record,
)

__all__ = ["FREQUENCIES", "NOAZI", "SYSTEMS", "TABLE", "Antenna", "AntexFile", "Blank", "Col",
           "Comment", "Dazi", "Epoch", "Error", "Frequencies", "FrequencyCode", "Grid",
           "Invalid", "Method", "Offset", "Pattern", "PcvType", "Record", "Row", "SinexCode",
           "TypeSerial", "Unsupported", "Version", "columns", "fields", "number", "record",
           "read", "write"]
