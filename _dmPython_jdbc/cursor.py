"""DBAPI cursor over a JayDeBeApi cursor."""
from ._sync import serialized
from .exceptions import InterfaceError, NotSupportedError
from .jdbc.converters import row_to_python, to_jdbc_parameter
from .jdbc.errors import to_dbapi_error
from .jdbc.generated_keys import GeneratedKeysJdbc, generated_key
from .jdbc.sql import is_insert, named_to_qmark


class Cursor:
    def __init__(self, jcur, conn):
        self._cur = jcur
        self._conn = conn
        self._lock = conn._lock
        self.arraysize = 50
        self.name = None  # Unnamed, forward-only cursor.
        self._statement = None
        self._rownumber = -1
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
        if self._closed:
            raise InterfaceError("not connected")
        self._conn._check_open()

    @property
    def connection(self):
        return self._conn

    @property
    def closed(self):
        return self._closed or self._conn.closed

    @property
    def query(self):
        return self._statement

    statement = query

    @property
    def rownumber(self):
        return self._rownumber

    @property
    def scrollable(self):
        return False

    @scrollable.setter
    def scrollable(self, value):
        if value:
            raise NotSupportedError("JDBC shim only supports forward-only cursors")

    @property
    def withhold(self):
        return False

    @withhold.setter
    def withhold(self, value):
        if value:
            raise NotSupportedError("JDBC shim does not support holdable cursors")

    # -- DBAPI --
    @property
    @serialized
    def description(self):
        self._check_conn_open()
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
    @serialized
    def rowcount(self):
        self._check_conn_open()
        return self._cur.rowcount

    def _prepare(self, operation, parameters):
        if parameters is None:
            return operation, None
        if isinstance(parameters, (list, tuple)):
            return operation, [to_jdbc_parameter(value) for value in parameters]
        # dict -> named binds rewritten as qmark
        sql, names = named_to_qmark(operation)
        return sql, [to_jdbc_parameter(parameters.get(n)) for n in names]

    @serialized
    def execute(self, operation, parameters=None, **kw):
        self._check_conn_open()
        sql, params = self._prepare(operation, parameters)
        self._statement = operation
        self._rownumber = -1
        self._lastrowid = None
        insert = is_insert(sql)
        try:
            if insert:
                self._execute_reporting_keys(sql, params)
            else:
                self._cur.execute(sql, params)
        except Exception as e:
            raise to_dbapi_error(e) from e
        if insert:
            self._lastrowid = generated_key(getattr(self._cur, "_prep", None))
        self._rownumber = 0 if self._cur.description else -1
        return self

    def _execute_reporting_keys(self, sql, params):
        # The caller holds the connection lock, so no other statement can be
        # prepared through the stand-in.
        jdbc = self._conn._jconn
        real = jdbc.jconn
        jdbc.jconn = GeneratedKeysJdbc(real)
        try:
            self._cur.execute(sql, params)
        finally:
            jdbc.jconn = real

    @serialized
    def executemany(self, operation, seq_of_parameters, **kw):
        self._check_conn_open()
        self._statement = operation
        self._rownumber = -1
        self._lastrowid = None
        first = seq_of_parameters[0] if seq_of_parameters else None
        if isinstance(first, dict):
            sql, names = named_to_qmark(operation)
            rows = [[to_jdbc_parameter(p.get(n)) for n in names] for p in seq_of_parameters]
        else:
            sql, rows = operation, [[to_jdbc_parameter(v) for v in p] for p in seq_of_parameters]
        try:
            self._cur.executemany(sql, rows)
        except Exception as e:
            raise to_dbapi_error(e) from e
        return self

    @property
    @serialized
    def lastrowid(self):
        """Key generated by the last execute() if it was an INSERT, else None."""
        self._check_conn_open()
        return self._lastrowid

    @serialized
    def fetchone(self):
        self._check_conn_open()
        row = row_to_python(self._cur.fetchone())
        if row is not None:
            self._rownumber += 1
        return row

    next = fetchone

    @serialized
    def fetchmany(self, size=None):
        self._check_conn_open()
        rows = [row_to_python(r) for r in self._cur.fetchmany(
            self.arraysize if size is None else size
        )]
        self._rownumber += len(rows)
        return rows

    @serialized
    def fetchall(self):
        self._check_conn_open()
        rows = [row_to_python(r) for r in self._cur.fetchall()]
        self._rownumber += len(rows)
        return rows

    def executedirect(self, operation):
        return self.execute(operation)

    def callproc(self, *args, **kwargs):
        raise NotSupportedError("JDBC shim does not support callproc")

    def callfunc(self, *args, **kwargs):
        raise NotSupportedError("JDBC shim does not support callfunc")

    def prepare(self, *args, **kwargs):
        raise NotSupportedError("JDBC shim does not support explicit prepare")

    def mogrify(self, *args, **kwargs):
        raise NotSupportedError("JDBC shim does not support mogrify")

    def nextset(self):
        raise NotSupportedError("JDBC shim does not support multiple result sets")

    def scroll(self, *args, **kwargs):
        raise NotSupportedError("JDBC shim only supports forward-only cursors")

    def setinputsizes(self, *args, **kw):
        pass

    def setoutputsize(self, *args, **kw):
        pass

    def var(self, *args, **kw):
        raise NotSupportedError("JDBC shim does not support cursor.var / OUT binds")

    @serialized
    def close(self):
        if self._closed:
            return
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
