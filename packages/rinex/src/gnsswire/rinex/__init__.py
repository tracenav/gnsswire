"""RINEX 3 and 4 observation files: text to records of text fields and back.

Not a framed binary codec: a RINEX file is read whole with :func:`read` and
written with :func:`write`, and ``write(read(text)) == text`` for every file
this module accepts. Every record is a frozen dataclass whose fields are the
text of its columns (``_records``), as NMEA fields are in ``gnsswire.nmea``;
:func:`number` gives a numeric field as the integer of its digits.

Sources: RINEX 3.05 (1 December 2020) and RINEX 4.02 (1 October 2024),
Tables A2 and A3 and the sections cited in ``_obs`` and ``_records``.
Navigation, meteorological and clock files, and RINEX 2, are not
implemented (:class:`Unsupported`).

Errors: every exception this codec raises for a file it cannot read or
records it cannot write is an :class:`Error` (a ``ValueError``):
:class:`Invalid`, :class:`Unsupported`, and the error :func:`number`
raises for a field that is not a number of its format.
"""

from ._obs import (
    END_OF_HEADER,
    OBS_TYPES,
    SYSTEMS,
    Epoch,
    ObsFile,
    obs_types,
    read,
    records,
    write,
)
from ._records import (
    Col,
    EpochRecord,
    Error,
    HeaderRecord,
    Invalid,
    Observation,
    SatelliteRecord,
    Unsupported,
    columns,
    number,
)

__all__ = ["END_OF_HEADER", "OBS_TYPES", "SYSTEMS", "Col", "Epoch", "EpochRecord", "Error",
           "HeaderRecord", "Invalid", "ObsFile", "Observation", "SatelliteRecord",
           "Unsupported", "columns", "number", "obs_types", "read", "records", "write"]
