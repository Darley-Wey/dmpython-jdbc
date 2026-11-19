"""DBAPI connection over a JayDeBeApi connection, and connect()."""
from threading import RLock

from ._sync import serialized
from .cursor import Cursor
from .dmsqlalchemy import patch_dialect_no_returning
from .exceptions import InterfaceError, NotSupportedError
from .jdbc.driver import open_connection


class Connection:
    def __init__(self, jconn, schema=None):
        self._jconn = jconn
        self._lock = RLock()
        self.outputtypehandler = None
        self.inputtypehandler = None
        self.server_version = "8.1.3.140"
        self.max_identifier_length = None
        self.current_schema = schema  # dmSQLAlchemy reads the default schema here
        self.local_code = 1  # 1 = utf-8; dmSQLAlchemy reads this
        self._closed = False
        try:
            metadata = self._jconn.jconn.getMetaData()
            self.server_version = str(metadata.getDatabaseProductVersion())
            lengths = [int(metadata.getMaxColumnNameLength()),
                       int(metadata.getMaxTableNameLength())]
            self.max_identifier_length = min((n for n in lengths if n > 0), default=None)
        except Exception:
            # Retain legacy version fallback if the driver cannot provide metadata.
            pass
        try:
            cur = self._jconn.cursor()
            try:
                cur.execute("SELECT CASE_SENSITIVE()")
                row = cur.fetchone()
            finally:
                cur.close()
            self.str_case_sensitive = bool(row and row[0] in (1, 'Y', 'y', True))
        except Exception:
            self.str_case_sensitive = True

    @property
    def version(self):
        """Server version consumed by dmAsync (not the Python package version)."""
        return self.server_version

    @property
    def stmtcachesize(self):
        """The shim does not maintain a Python statement cache."""
        return 0

    @stmtcachesize.setter
    def stmtcachesize(self, value):
        if value != 0:
            raise NotSupportedError("JDBC shim does not support a Python statement cache")

    @property
    @serialized
    def closed(self):
        return self._closed or bool(self._jconn.jconn.isClosed())

    @property
    def status(self):
        """Shim liveness: 1 while open, 0 when closed; not a DPI transaction code."""
        return int(not self.closed)

    @property
    @serialized
    def autocommit(self):
        self._check_open()
        return bool(self._jconn.jconn.getAutoCommit())

    @autocommit.setter
    @serialized
    def autocommit(self, value):
        self._check_open()
        self._jconn.jconn.setAutoCommit(bool(value))

    autoCommit = autocommit

    def _check_open(self):
        if self.closed:
            raise InterfaceError("not connected")

    @serialized
    def cursor(self, *args, **kw):
        self._check_open()
        return Cursor(self._jconn.cursor(), self)

    @serialized
    def commit(self):
        self._check_open()
        self._jconn.commit()

    @serialized
    def rollback(self):
        if self._closed:
            return
        try:
            self._jconn.rollback()
        except Exception:
            pass

    @serialized
    def close(self):
        if self._closed:
            return
        try:
            self._jconn.close()
        except Exception:
            pass
        self._closed = True

    @serialized
    def ping(self, *a, **kw):
        cur = self.cursor()
        try:
            cur.execute("SELECT 1")
            cur.fetchone()
        finally:
            cur.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _jdbc_url(kw):
    """JDBC URL for dmPython.connect() keyword arguments."""
    dsn = kw.get("dsn")
    if dsn:
        host, _, port = dsn.partition(":")
    else:
        host, port = kw.get("host", "localhost"), str(kw.get("port", 5236))
    url = f"jdbc:dm://{host}:{port}"
    props = {}
    if kw.get("schema"):
        props["schema"] = kw["schema"]
    # local_code is not forwarded: JDBC handles encoding.
    # Official dmPython: login_timeout is milliseconds, connection_timeout is seconds.
    # JDBC uses different property names. Forward them here; unknown kwargs stay ignored.
    login_timeout = kw.get("login_timeout")
    if login_timeout is not None:
        props["loginTimeout"] = max(1, int(round(int(login_timeout) / 1000)))
    connection_timeout = kw.get("connection_timeout")
    if connection_timeout is not None:
        props["socketTimeout"] = int(connection_timeout) * 1000
    if props:
        url += "?" + "&".join(f"{k}={v}" for k, v in props.items())
    return url


def connect(*args, **kw):
    """Compatible with dmPython.connect(user=..., password=..., dsn='host:port', schema=..., ...)."""
    patch_dialect_no_returning()
    user = kw.get("user") or kw.get("username") or "SYSDBA"
    password = kw.get("password", "")
    schema = kw.get("schema")
    jconn = open_connection(_jdbc_url(kw), user, password)
    autocommit = kw.get("autoCommit", kw.get("autocommit", False))
    jconn.jconn.setAutoCommit(bool(autocommit))
    conn = Connection(jconn, schema=schema)
    if conn.current_schema is None:
        try:
            cur = conn.cursor()
            cur.execute("SELECT SYS_CONTEXT('userenv','current_schema') FROM dual")
            row = cur.fetchone()
            cur.close()
            conn.current_schema = row[0] if row else user
        except Exception:
            conn.current_schema = user
    return conn
