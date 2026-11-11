# dmpython-jdbc

[English](README.md) | [简体中文](README.zh-CN.md)

macOS compatibility layer for Dameng `dmPython`. Dameng does not ship a macOS driver, so this package implements a DBAPI subset with JayDeBeApi + Dameng JDBC and makes dmSQLAlchemy's `dm+dmPython://` dialect work locally.

**The distribution name is `dmpython-jdbc`; the import name remains `dmPython`.** Application code does not need to change.

- macOS: use this package's JDBC shim
- Other platforms: forward `import dmPython` to the official driver

## Install

PyPI:

```bash
pip install dmpython-jdbc
```

Cross-platform projects (official driver on Linux/Windows, this package on macOS):

```toml
[project]
dependencies = [
    "dmpython>=2.5.32; sys_platform != 'darwin'",
    "dmpython-jdbc>=2.5.32; sys_platform == 'darwin'",
]
```

If the project also depends on `dmSQLAlchemy`, see [Using with dmSQLAlchemy](#using-with-dmsqlalchemy). That package pulls official `dmpython` unconditionally.

From Git:

```bash
pip install "dmpython-jdbc @ git+https://github.com/Darley-Wey/dmpython-jdbc.git"
```

uv:

```toml
[tool.uv.sources]
dmpython-jdbc = { git = "https://github.com/Darley-Wey/dmpython-jdbc.git" }
```

Pin a commit or tag by appending `@<ref>`, for example `@main` or `@v2.5.32`.

## Runtime requirements

- Python >= 3.12
- JDK (`brew install openjdk` on macOS). `JAVA_HOME` is probed at `/opt/homebrew/opt/openjdk` and `/usr/local/opt/openjdk`
- The Dameng JDBC driver is bundled in the wheel; override it with `DM_JDBC_JAR`


## Using with dmSQLAlchemy

`dmSQLAlchemy` unconditionally depends on official `dmpython` (`Requires-Dist: dmPython`). That package has no macOS wheel, so `pip install dmSQLAlchemy` on a Mac will try to install Dameng's driver and fail.

Keep `dmSQLAlchemy`, prevent the resolver from installing official `dmpython` on macOS, and install `dmpython-jdbc` instead. The import name stays `dmPython`.

### uv

```toml
[project]
dependencies = [
    "dmsqlalchemy",
    "dmpython>=2.5.32; sys_platform != 'darwin'",
    "dmpython-jdbc>=2.5.32; sys_platform == 'darwin'",
]

[tool.uv]
override-dependencies = [
    "dmpython ; sys_platform != 'darwin'",
]
```

`override-dependencies` rewrites `dmSQLAlchemy`'s `dmpython` requirement so it is skipped on macOS. `dmpython-jdbc` then provides the `dmPython` module.

`dmSQLAlchemy.extensions` calls `importlib.metadata.version("dmPython")`. This package installs a `.pth` hook so that lookup returns the shim version `2.5.32` without needing setuptools/`pkg_resources`.

### pip on macOS

```bash
pip install "dmSQLAlchemy" --no-deps
pip install "SQLAlchemy>1.4.54" dmpython-jdbc
```

## Using as dmAsync's dmPython backend

The shim supports the basic connection and cursor API used by `dmAsync==1.0.0`:
`connect`, `execute`, `executemany`, `fetchone`/`fetchmany`/`fetchall`, async
iteration, `commit`, `rollback`, and `ping`. dmAsync calls the synchronous shim
through `asyncio.to_thread` for these database operations; connection creation
and closing remain synchronous in dmAsync 1.0.0.

For a development checkout on macOS:

```bash
python -m pip install . "async-timeout>=4,<6"
python -m pip install "dmAsync==1.0.0" --no-deps
```

`dmAsync` unconditionally requires official `dmPython`, so use the same
`[tool.uv].override-dependencies` configuration shown above when using uv.
Add `dmAsync==1.0.0` and `async-timeout>=4,<6` to your project dependencies;
dmAsync 1.0.0 imports `async_timeout` but does not declare it in its metadata.
The runtime version alias does not replace these resolver settings.

```python
import asyncio
import os
import dmAsync


async def main():
    conn = await dmAsync.connect(
        host=os.environ["DM_HOST"],
        port=int(os.environ.get("DM_PORT", "5236")),
        user=os.environ["DM_USER"],
        password=os.environ["DM_PASSWORD"],
        autoCommit=False,
        login_timeout=5000,  # Milliseconds, forwarded to dmPython.
    )
    cur = await conn.cursor()
    try:
        await cur.execute("SELECT 1")
        print(await cur.fetchone())
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await cur.close()
        await conn.close()


asyncio.run(main())
```

`Connection.version` reports the server version. Identifier limits come from
JDBC metadata (`None` when unknown). `stmtcachesize` is `0` because the shim does
not implement a Python statement cache; setting a nonzero size is unsupported.
`status` reports shim liveness (`1` open, `0` closed), not a DPI transaction code.
Assignments to `autocommit` update the JDBC connection.

JDBC operations are serialized per connection across worker threads. Use one
connection per concurrent task: a lock does not isolate transactions or preserve
an execute/fetch sequence shared by several tasks. Cancelling an await does not
stop JDBC work already running in a thread; wait for that work to finish before
reusing or closing its connection. `callproc`, `callfunc`, explicit `prepare`,
`mogrify`, scrolling, holdable cursors and multiple result sets remain unsupported
and raise `NotSupportedError`. This does not establish full compatibility with
SQLAlchemy's separate `dm+dmasync://` dialect or dmAsync's connection pool.

### Adapter tests

With the dependencies above installed, run:

```bash
python -m unittest discover -s tests -v
```

Tests use the real dmAsync wrapper with a SQLite-backed double at the
JayDeBeApi boundary. They cover initialization, CRUD, transactions, cursor
lifecycle and per-connection locking without requiring a Dameng server.

For real-server verification, see [live Dameng E2E tests](tests/e2e/README.md).
With the dedicated test credentials configured, `bash tests/e2e/test.sh` builds
and tests the installed wheel against DM8, including binary/LOB round trips and
cross-connection transaction visibility.

## Limits

Stored-procedure OUT binds (`cursor.var`) and streaming LOB I/O are not supported. ORM CRUD is covered.

## License

The Python shim is MIT. `DmJdbcDriver18-*.jar` is Dameng's official JDBC driver and is not covered by MIT.
