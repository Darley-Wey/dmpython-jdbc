"""What exists only for dmSQLAlchemy: dialect adjustments and stub symbols."""
import datetime
import json
import sys

from .exceptions import NotSupportedError


def patch_dialect_no_returning():
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

    # This shim's lastrowid is the generated key of a single column. Official
    # dmSQLAlchemy treats lastrowid as a physical ROWID and queries it back.
    # For this shim, fill the PK directly from that key.
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
    def _do_executemany(self, cursor, statement, parameters, context=None):
        rows = [list(p) for p in parameters]
        for row in rows:
            for j, v in enumerate(row):
                if isinstance(v, datetime.datetime):
                    row[j] = v.strftime("%Y-%m-%d %H:%M:%S.%f")
                elif isinstance(v, list):
                    row[j] = json.dumps(v) if v else ''
        cursor.executemany(statement, rows)

    cls.do_executemany = _do_executemany
    cls._jdbc_shim_patched = True


# Optional symbols used by dmSQLAlchemy reflection; provide stubs.
def parse_mysql_stmt(*a, **kw):
    raise NotSupportedError("shim does not support parse_mysql_stmt")


def parse_tsql_stmt(*a, **kw):
    raise NotSupportedError("shim does not support parse_tsql_stmt")


class objedctvar:  # dmSQLAlchemy uses this misspelling
    pass
