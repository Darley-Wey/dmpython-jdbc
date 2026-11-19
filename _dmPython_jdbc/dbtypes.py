"""Type sentinels.

Official dmPython exposes these as classes; dmSQLAlchemy uses isinstance
(e.g. isinstance(value, dialect.dbapi.LOB)), so they must be types, not instances.
"""

__all__ = [
    "STRING",
    "UNICODE",
    "LONG_STRING",
    "FIXED_CHAR",
    "VARCHAR",
    "CLOB",
    "NCLOB",
    "BLOB",
    "BFILE",
    "BINARY",
    "LONG_BINARY",
    "NUMBER",
    "NATIVE_FLOAT",
    "DATETIME",
    "DATE",
    "TIME",
    "TIMESTAMP",
    "INTERVAL",
    "ROWID",
    "LOB",
    "CURSOR",
    "BOOLEAN",
    "TupleCursor",
]


class _DBType:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<dmPython.{self.name}>"


def _make_type(name):
    return type(name, (_DBType,), {"_type_name": name})


STRING = _make_type("STRING")
UNICODE = _make_type("UNICODE")
LONG_STRING = _make_type("LONG_STRING")
FIXED_CHAR = _make_type("FIXED_CHAR")
VARCHAR = _make_type("VARCHAR")
CLOB = _make_type("CLOB")
NCLOB = _make_type("NCLOB")
BLOB = _make_type("BLOB")
BFILE = _make_type("BFILE")
BINARY = _make_type("BINARY")
LONG_BINARY = _make_type("LONG_BINARY")
NUMBER = _make_type("NUMBER")
NATIVE_FLOAT = _make_type("NATIVE_FLOAT")
DATETIME = _make_type("DATETIME")
DATE = _make_type("DATE")
TIME = _make_type("TIME")
TIMESTAMP = _make_type("TIMESTAMP")
INTERVAL = _make_type("INTERVAL")
ROWID = _make_type("ROWID")
LOB = _make_type("LOB")
CURSOR = _make_type("CURSOR")
BOOLEAN = _make_type("BOOLEAN")
TupleCursor = _make_type("TupleCursor")
