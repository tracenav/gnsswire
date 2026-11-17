"""RINEX 3 and 4 observation files: text to records of text fields and back.

Not a framed binary codec: a RINEX file is read whole with :func:`read` and
written with :func:`write`, and ``write(read(text)) == text`` for every file
this module accepts. Every record is a frozen dataclass whose fields are the
text of its columns (``_records``), as NMEA fields are in ``gnsswire.nmea``;
:func:`number` gives a numeric field as the integer of its digits.

Sources: RINEX 3.05 (1 December 2020) and RINEX 4.02 (1 October 2024),
Tables A2 and A3 and the sections cited in ``_obs`` and ``_records``.
Meteorological and clock files are not implemented
(:class:`Unsupported`).

Navigation message files of RINEX 2, 3 and 4 are read with
:func:`read_nav` and written with :func:`write_nav`, as losslessly;
:func:`nav_fields` gives a record's values by the names of its table and
:func:`real` a floating point field as an exact decimal. :func:`read`
raises :class:`Unsupported` for them. Sources: RINEX 3.05 Tables A5 to A19,
RINEX 4.02 Tables A7 to A41 and RINEX 2.11 Tables A3, A4, A10, A11, A15 and
A16, as cited in ``_nav``.

RINEX 2 observation files are read with :func:`read2` and written with
:func:`write2`, in the same way and with the same header, observation and
satellite records; :func:`read` raises :class:`Unsupported` for them.
Source: RINEX 2.11 (10 December 2007), Tables A1 and A2 and the sections
cited in ``_obs2``.

Errors: every exception this codec raises for a file it cannot read or
records it cannot write is an :class:`Error` (a ``ValueError``):
:class:`Invalid`, :class:`Unsupported`, and the error :func:`number`
raises for a field that is not a number of its format.
"""

from ._nav import (
    NavEpoch,
    NavEpoch2,
    NavFile,
    NavLayout,
    NavLine,
    NavLine2,
    NavRecord,
    NavType,
    nav_fields,
    nav_type,
    read_nav,
    real,
    write_nav,
)
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
from ._obs2 import (
    OBS_TYPES2,
    SYSTEMS2,
    Epoch2,
    EpochRecord2,
    ObsFile2,
    SatelliteList,
    full_year,
    obs_types2,
    read2,
    records2,
    sat_name,
    write2,
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
__all__ += ["OBS_TYPES2", "SYSTEMS2", "Epoch2", "EpochRecord2", "ObsFile2", "SatelliteList",
            "full_year", "obs_types2", "read2", "records2", "sat_name", "write2"]
__all__ += ["NavEpoch", "NavEpoch2", "NavFile", "NavLayout", "NavLine", "NavLine2", "NavRecord",
            "NavType", "nav_fields", "nav_type", "read_nav", "real", "write_nav"]
