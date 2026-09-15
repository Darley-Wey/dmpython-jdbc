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
"""
import datetime as _datetime
import glob
import os
import re
import sys

version = "2.5.32"  # spoof the official version; dmSQLAlchemy parses it
apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"  # compiled to JDBC `?`; dialect do_execute uses positional binds


# ---------------------------------------------------------------- exceptions
class Warning(Exception): pass
class Error(Exception): pass
class InterfaceError(Error): pass
class DatabaseError(Error): pass
class DataError(DatabaseError): pass
class OperationalError(DatabaseError): pass
class IntegrityError(DatabaseError): pass
class InternalError(DatabaseError): pass
class ProgrammingError(DatabaseError): pass
class NotSupportedError(DatabaseError): pass


# ---------------------------------------------------------------- type sentinels
# Official dmPython exposes these as classes; dmSQLAlchemy uses isinstance
# (e.g. isinstance(value, dialect.dbapi.LOB)), so they must be types, not instances.
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


def _jdbc_timestamp_to_datetime(result_set, column):
    """Convert a JDBC TIMESTAMP to the datetime shape official dmPython returns."""
    value = result_set.getTimestamp(column)
    if value is None:
        return None

    parsed = _datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    return parsed.replace(microsecond=int(value.getNanos()) // 1000)


def _find_jar():
    jar = os.environ.get("DM_JDBC_JAR")
    if jar and os.path.exists(jar):
        return jar
    here = os.path.dirname(os.path.abspath(__file__))
    packaged = sorted(glob.glob(os.path.join(here, "DmJdbcDriver*.jar")))
    if packaged:
        return packaged[-1]
    for base in (os.path.dirname(here), os.getcwd()):
        hits = sorted(glob.glob(os.path.join(base, "libs", "DmJdbcDriver*.jar"))) \
            or sorted(glob.glob(os.path.join(base, "DmJdbcDriver*.jar")))
        if hits:
            return hits[-1]
    raise InterfaceError("Dameng JDBC driver JAR not found; set DM_JDBC_JAR")


def _ensure_java_home():
    if os.environ.get("JAVA_HOME"):
        return
    for cand in ("/opt/homebrew/opt/openjdk", "/usr/local/opt/openjdk"):
        if os.path.exists(os.path.join(cand, "bin", "java")):
            os.environ["JAVA_HOME"] = cand
            return


# Rewrite :name binds to JDBC `?`, skipping string literals and `::` casts.
_BIND_RE = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")


def _named_to_qmark(sql):
    names = []
    out = []
    pos = 0
    in_str = False
    i = 0
    buf = sql
    # Skip replacements inside single-quoted string literals.
    result = []
    last = 0
    for m in _BIND_RE.finditer(sql):
        seg = sql[last:m.start()]
        # Odd number of quotes before this match means we are inside a string.
        if (sql[:m.start()].count("'") % 2) == 1:
            continue
        result.append(seg)
        result.append("?")
        names.append(m.group(1))
        last = m.end()
    result.append(sql[last:])
    return "".join(result), names


class Cursor:
    def __init__(self, jcur, conn):
        self._cur = jcur
        self._conn = conn
        self.arraysize = 50
        self.outputtypehandler = None
        self.inputtypehandler = None
        self.output_stream = 0
        self.rowfactory = None
        self._lastrowid = None
        self._closed = False

    def _check_conn_open(self):
        # dmSQLAlchemy.is_disconnect only treats InterfaceError("not connected")
        # as a dropped connection. Map Dameng JDBC closed-connection errors to
        # that shape so the pool can discard and reconnect.
        if self._closed or getattr(self._conn, "_closed", False):
            raise InterfaceError("not connected")

    # -- DBAPI --
    @property
    def description(self):
        desc = self._cur.description
        if not desc:
            return desc
        # jaydebeapi uses getColumnName (physical name) instead of getColumnLabel
        # (SQL alias), dropping aliases such as `id as "tab_id"`. Fix via label.
        # Dameng also uppercases unquoted identifiers; official dmPython returns
        # lowercase, and dmSQLAlchemy reflection looks up columns in lowercase.
        meta = getattr(self._cur, "_meta", None)
        names = []
        for i, d in enumerate(desc):
            name = d[0]
            if meta is not None:
                try:
                    name = str(meta.getColumnLabel(i + 1))
                except Exception:
                    pass
            if isinstance(name, str) and name.isupper():
                name = name.lower()
            names.append(name)
        return [(names[i],) + tuple(d[1:]) for i, d in enumerate(desc)]

    @property
    def rowcount(self):
        return self._cur.rowcount

    def _prepare(self, operation, parameters):
        if parameters is None:
            return operation, None
        if isinstance(parameters, (list, tuple)):
            return operation, list(parameters)
        # dict -> named binds rewritten as qmark
        sql, names = _named_to_qmark(operation)
        return sql, [parameters.get(n) for n in names]

    def execute(self, operation, parameters=None, **kw):
        self._check_conn_open()
        sql, params = self._prepare(operation, parameters)
        try:
            self._cur.execute(sql, params)
        except Exception as e:
            msg = str(e)
            # Dameng JDBC uses these Chinese phrases for a closed connection.
            if "尚未建立" in msg or "已经关闭" in msg or "not connected" in msg.lower() or "connection closed" in msg.lower():
                raise InterfaceError("not connected") from e
            raise DatabaseError(msg) from e
        self._capture_identity(sql)
        return self

    def executemany(self, operation, seq_of_parameters, **kw):
        self._check_conn_open()
        first = seq_of_parameters[0] if seq_of_parameters else None
        if isinstance(first, dict):
            sql, names = _named_to_qmark(operation)
            rows = [[p.get(n) for n in names] for p in seq_of_parameters]
        else:
            sql, rows = operation, [list(p) for p in seq_of_parameters]
        try:
            self._cur.executemany(sql, rows)
        except Exception as e:
            msg = str(e)
            # Dameng JDBC uses these Chinese phrases for a closed connection.
            if "尚未建立" in msg or "已经关闭" in msg or "not connected" in msg.lower() or "connection closed" in msg.lower():
                raise InterfaceError("not connected") from e
            raise DatabaseError(msg) from e
        return self

    def _capture_identity(self, sql):
        # Capture identity only after INSERT; lastrowid reads it lazily.
        self._lastrowid = None
        if re.match(r"\s*insert\b", sql, re.I):
            self._pending_identity = True
        else:
            self._pending_identity = False

    @property
    def lastrowid(self):
        if getattr(self, "_pending_identity", False):
            c = self._conn._jconn.cursor()
            try:
                c.execute("SELECT SCOPE_IDENTITY()")
                row = c.fetchone()
                self._lastrowid = int(row[0]) if row and row[0] is not None else None
            except Exception:
                self._lastrowid = None
            finally:
                c.close()
            self._pending_identity = False
        return self._lastrowid

    def _convert_row(self, row):
        """jaydebeapi returns java.sql.Clob/Blob; official dmPython returns str/bytes.
        Normalize so ORM assignment does not fail."""
        if row is None:
            return None
        items = []
        for v in row:
            # JPype proxies look like _jp_java.sql.Clob or java.sql.Clob
            cls_name = type(v).__name__
            if not isinstance(v, (str, bytes, int, float, bool, type(None))):
                try:
                    simple = ''
                    if hasattr(v, 'getClass'):
                        try:
                            simple = str(v.getClass().getSimpleName())
                        except Exception:
                            simple = cls_name
                    else:
                        simple = cls_name
                    if 'Clob' in simple or 'NClob' in simple:
                        v = v.getSubString(1, int(v.length()))
                    elif 'Blob' in simple:
                        v = bytes(v.getBytes(1, int(v.length())))
                    elif cls_name.startswith('_jp_java') or cls_name.startswith('_jp_'):
                        v = str(v)
                except Exception:
                    pass
            items.append(v)
        return tuple(items)

    def fetchone(self):
        return self._convert_row(self._cur.fetchone())

    def fetchmany(self, size=None):
        return [self._convert_row(r) for r in self._cur.fetchmany(size or self.arraysize)]

    def fetchall(self):
        return [self._convert_row(r) for r in self._cur.fetchall()]

    def setinputsizes(self, *args, **kw):
        pass

    def setoutputsize(self, *args, **kw):
        pass

    def var(self, *args, **kw):
        raise NotSupportedError("JDBC shim does not support cursor.var / OUT binds")

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass
        self._closed = True

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Connection:
    def __init__(self, jconn, schema=None):
        self._jconn = jconn
        self.outputtypehandler = None
        self.inputtypehandler = None
        self.autocommit = False
        self.server_version = "8.1.3.140"
        self.current_schema = schema  # dmSQLAlchemy reads the default schema here
        self.local_code = 1  # 1 = utf-8; dmSQLAlchemy reads this
        self._closed = False
        try:
            cur = self._jconn.cursor()
            cur.execute("SELECT CASE_SENSITIVE()")
            row = cur.fetchone()
            cur.close()
            self.str_case_sensitive = bool(row and row[0] in (1, 'Y', 'y', True))
        except Exception:
            self.str_case_sensitive = True

    def _check_open(self):
        if self._closed:
            raise InterfaceError("not connected")

    def cursor(self, *args, **kw):
        self._check_open()
        return Cursor(self._jconn.cursor(), self)

    def commit(self):
        self._check_open()
        self._jconn.commit()

    def rollback(self):
        if self._closed:
            return
        try:
            self._jconn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._jconn.close()
        except Exception:
            pass
        self._closed = True

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


def _patch_dialect_no_returning():
    """RETURNING needs cursor.var OUT binds, which this shim does not support.
    Disable dialect returning so SQLAlchemy falls back to lastrowid."""
    mod = sys.modules.get("dmSQLAlchemy.dmpython")
    if mod is None:
        return
    cls = getattr(mod, "DMDialect_dmPython", None)
    if cls is None or getattr(cls, "_jdbc_shim_patched", False):
        return
    cls.insert_returning = False
    cls.update_returning = False
    cls.delete_returning = False
    cls.insert_executemany_returning = False
    cls.favor_returning_over_lastrowid = False

    # JDBC SCOPE_IDENTITY() returns a single identity column value. Official
    # dmSQLAlchemy treats lastrowid as a physical ROWID and queries it back.
    # For this shim, fill the PK directly from that identity value.
    def _get_cols_from_lastrowid(self, table, primary_columns, lastrowid):
        if len(primary_columns) == 1:
            return (lastrowid,)
        return super(cls.execution_ctx_cls, self).get_cols_from_lastrowid(
            table, primary_columns, lastrowid
        )

    cls.execution_ctx_cls.get_cols_from_lastrowid = _get_cols_from_lastrowid

    # Official do_executemany appends `RETURNING ... INTO ?` to fetch identity.
    # JDBC cannot do that; use plain executemany and let the server assign PKs.
    # If the ORM needs those keys, insert one row at a time and flush.
    import datetime as _dt
    import json as _json

    def _do_executemany(self, cursor, statement, parameters, context=None):
        rows = [list(p) for p in parameters]
        for row in rows:
            for j, v in enumerate(row):
                if isinstance(v, _dt.datetime):
                    row[j] = v.strftime("%Y-%m-%d %H:%M:%S.%f")
                elif isinstance(v, list):
                    row[j] = _json.dumps(v) if v else ''
        cursor.executemany(statement, rows)

    cls.do_executemany = _do_executemany
    cls._jdbc_shim_patched = True


def connect(*args, **kw):
    """Compatible with dmPython.connect(user=..., password=..., dsn='host:port', schema=..., ...)."""
    import jaydebeapi

    _patch_dialect_no_returning()
    _ensure_java_home()
    user = kw.get("user") or kw.get("username") or "SYSDBA"
    password = kw.get("password", "")
    dsn = kw.get("dsn")
    if dsn:
        host, _, port = dsn.partition(":")
    else:
        host, port = kw.get("host", "localhost"), str(kw.get("port", 5236))
    schema = kw.get("schema")
    url = f"jdbc:dm://{host}:{port}"
    props = {}
    if schema:
        props["schema"] = schema
    if kw.get("local_code") is not None:
        pass  # JDBC handles encoding
    if props:
        url += "?" + "&".join(f"{k}={v}" for k, v in props.items())
    try:
        jconn = jaydebeapi.connect(
            "dm.jdbc.driver.DmDriver", url, [user, password], _find_jar()
        )
        timestamp_type = jaydebeapi._jdbc_name_to_const["TIMESTAMP"]
        jconn._converters[timestamp_type] = _jdbc_timestamp_to_datetime
    except Exception as e:
        raise OperationalError(f"Dameng JDBC connection failed: {e}") from e
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
    conn.autocommit = bool(autocommit)
    return conn


# Optional symbols used by dmSQLAlchemy reflection; provide stubs.
def parse_mysql_stmt(*a, **kw):
    raise NotSupportedError("shim does not support parse_mysql_stmt")


def parse_tsql_stmt(*a, **kw):
    raise NotSupportedError("shim does not support parse_tsql_stmt")


class objedctvar:  # dmSQLAlchemy uses this misspelling
    pass
