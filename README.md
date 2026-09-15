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

From GitHub:

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

## Limits

Stored-procedure OUT binds (`cursor.var`) and streaming LOB I/O are not supported. ORM CRUD is covered.

## License

The Python shim is MIT. `DmJdbcDriver18-*.jar` is Dameng's official JDBC driver and is not covered by MIT.
