"""
dmPython 兼容 shim（仅 macOS 本地开发用）。

达梦官方没有 macOS 版 dmPython（缺少 libdmdpi 闭源库无法本地编译），
本模块用 JayDeBeApi + DmJdbcDriver 实现 dmPython 的 DBAPI 子集，
让 dmSQLAlchemy 的 `dm+dmPython://` 方言在 mac 上可用。

依赖:
  - pip/uv 安装本包时会自动拉 JayDeBeApi（jpype1 会一并安装）
  - brew install openjdk               (JAVA_HOME 自动探测 /opt/homebrew/opt/openjdk)
  - 达梦 JDBC 驱动 jar 已随包发布；可用环境变量 DM_JDBC_JAR 覆盖

限制: 不支持存储过程出参(cursor.var)、LOB 流式读写等高级特性, 满足 ORM CRUD 即可。
"""
import datetime as _datetime
import glob
import os
import re
import sys

version = "2.5.32"  # 伪装成官方版本号, dmSQLAlchemy 会解析它
apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"  # 编译成 ? 占位符, 与 JDBC 原生一致; dialect do_execute 也按位置索引参数


# ---------------------------------------------------------------- 异常体系
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


# ---------------------------------------------------------------- 类型哨兵
# 官方 dmPython 中这些符号本身是类, dmSQLAlchemy 会拿来做 isinstance 判断
# (如 isinstance(value, dialect.dbapi.LOB)), 所以必须是类而不是实例。
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
    """将 JDBC TIMESTAMP 转为与官方 dmPython 一致的 Python datetime。"""
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
    raise InterfaceError("找不到达梦 JDBC 驱动 jar, 请设置环境变量 DM_JDBC_JAR")


def _ensure_java_home():
    if os.environ.get("JAVA_HOME"):
        return
    for cand in ("/opt/homebrew/opt/openjdk", "/usr/local/opt/openjdk"):
        if os.path.exists(os.path.join(cand, "bin", "java")):
            os.environ["JAVA_HOME"] = cand
            return


# :name 占位符 → JDBC '?' 占位符。跳过字符串字面量与 :: 转换。
_BIND_RE = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")


def _named_to_qmark(sql):
    names = []
    out = []
    pos = 0
    in_str = False
    i = 0
    buf = sql
    # 简单状态机: 单引号字符串内不做替换
    result = []
    last = 0
    for m in _BIND_RE.finditer(sql):
        seg = sql[last:m.start()]
        # 统计该占位符之前未闭合的单引号数
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
        # dmSQLAlchemy.is_disconnect 只把 InterfaceError("not connected") 判成断线;
        # 把 JDBC 的“连接尚未建立或已经关闭”映射成这一形态, 连接池才能自动丢弃旧连接并重建。
        if self._closed or getattr(self._conn, "_closed", False):
            raise InterfaceError("not connected")

    # -- DBAPI --
    @property
    def description(self):
        desc = self._cur.description
        if not desc:
            return desc
        # jaydebeapi 用 getColumnName(底层列名)而非 getColumnLabel(SQL 别名),
        # 会丢掉 `id as "tab_id"` 这类别名; 这里用 label 修正。
        # 另: DM 服务端把未加引号的标识符统一大写返回, 官方 dmPython 返回小写,
        # dmSQLAlchemy 反射代码按小写取列, 全大写时转小写保持一致。
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
        # dict → named 转 qmark
        sql, names = _named_to_qmark(operation)
        return sql, [parameters.get(n) for n in names]

    def execute(self, operation, parameters=None, **kw):
        self._check_conn_open()
        sql, params = self._prepare(operation, parameters)
        try:
            self._cur.execute(sql, params)
        except Exception as e:
            msg = str(e)
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
            if "尚未建立" in msg or "已经关闭" in msg or "not connected" in msg.lower() or "connection closed" in msg.lower():
                raise InterfaceError("not connected") from e
            raise DatabaseError(msg) from e
        return self

    def _capture_identity(self, sql):
        # 仅 INSERT 后按需取自增值(get_lastrowid 会读取)
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
        """jaydebeapi 把 CLOB/BLOB 列返回为 java.sql.Clob/Blob 对象,
        官方 dmPython 返回 str/bytes, 这里统一转换避免 ORM 赋值时报错。"""
        if row is None:
            return None
        items = []
        for v in row:
            # jpype1 代理对象的类名形如 _jp_java.sql.Clob, 或是接口类型 java.sql.Clob
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
        raise NotSupportedError("JDBC shim 不支持 cursor.var/出参")

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
        self.current_schema = schema  # dmSQLAlchemy 取默认 schema 用
        self.local_code = 1  # 1 = utf-8, dmSQLAlchemy 会读取
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
    """RETURNING 依赖 cursor.var 出参, JDBC shim 不支持;
    关闭方言的 returning 能力, 让 SQLAlchemy 回退到 lastrowid 取自增主键。"""
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

    # JDBC 的 SCOPE_IDENTITY() 返回单列自增主键值；dmSQLAlchemy 官方驱动
    # 则将 lastrowid 视为物理 ROWID 再查询。为 JDBC shim 直接回填该主键值。
    def _get_cols_from_lastrowid(self, table, primary_columns, lastrowid):
        if len(primary_columns) == 1:
            return (lastrowid,)
        return super(cls.execution_ctx_cls, self).get_cols_from_lastrowid(
            table, primary_columns, lastrowid
        )

    cls.execution_ctx_cls.get_cols_from_lastrowid = _get_cols_from_lastrowid

    # 官方 do_executemany 会拼 `RETURNING ... INTO ?` 出参取回自增主键,
    # JDBC 无此机制; 改为普通 executemany, 主键由服务端自增, ORM 批量插入
    # 后如需主键请单条 add + flush。
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
    """兼容 dmPython.connect(user=..., password=..., dsn='host:port', schema=..., ...)"""
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
        pass  # 编码由 JDBC 自动处理
    if props:
        url += "?" + "&".join(f"{k}={v}" for k, v in props.items())
    try:
        jconn = jaydebeapi.connect(
            "dm.jdbc.driver.DmDriver", url, [user, password], _find_jar()
        )
        timestamp_type = jaydebeapi._jdbc_name_to_const["TIMESTAMP"]
        jconn._converters[timestamp_type] = _jdbc_timestamp_to_datetime
    except Exception as e:
        raise OperationalError(f"达梦 JDBC 连接失败: {e}") from e
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


# dmSQLAlchemy 反射用到的可选符号, 提供占位实现
def parse_mysql_stmt(*a, **kw):
    raise NotSupportedError("shim 不支持 parse_mysql_stmt")


def parse_tsql_stmt(*a, **kw):
    raise NotSupportedError("shim 不支持 parse_tsql_stmt")


class objedctvar:  # dmSQLAlchemy 引用了这个拼写
    pass
