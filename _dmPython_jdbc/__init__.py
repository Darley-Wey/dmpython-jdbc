"""
dmPython-compatible shim for local macOS development.

Dameng does not ship a macOS dmPython build (libdmdpi is closed-source),
so this module implements a DBAPI subset with JayDeBeApi + DmJdbcDriver
and makes dmSQLAlchemy's `dm+dmPython://` dialect usable on Mac.

Dependencies:
  - JayDeBeApi is installed with this package (JPype1 comes with it)
  - brew install openjdk  (JAVA_HOME is probed at /opt/homebrew/opt/openjdk)
  - Dameng JDBC driver JAR is packaged; override with DM_JDBC_JAR

Limits: no cursor.var / OUT binds, no streaming LOB I/O. ORM CRUD is enough.

Layout, top layer first; each imports only from those below it:
  __init__              the public dmPython module surface
  connection, cursor    DBAPI objects
  dmsqlalchemy          dialect adjustments and stubs only dmSQLAlchemy needs
  jdbc/                 Java, JayDeBeApi and Dameng JDBC driver details
  exceptions, dbtypes   DBAPI vocabulary shared by every layer
"""
from . import dbtypes, exceptions
from .connection import Connection, connect
from .cursor import Cursor
from .dbtypes import *  # noqa: F401,F403
from .dmsqlalchemy import objedctvar, parse_mysql_stmt, parse_tsql_stmt
from .exceptions import *  # noqa: F401,F403

version = "2.5.32"  # spoof the official version; dmSQLAlchemy parses it
apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"  # compiled to JDBC `?`; dialect do_execute uses positional binds

# dmPython.py re-exports exactly these names as the dmPython module on macOS.
__all__ = [
    "version",
    "apilevel",
    "threadsafety",
    "paramstyle",
    "connect",
    "Connection",
    "Cursor",
    *exceptions.__all__,
    *dbtypes.__all__,
    "parse_mysql_stmt",
    "parse_tsql_stmt",
    "objedctvar",
]
