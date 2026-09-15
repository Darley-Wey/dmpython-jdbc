# dmpython-jdbc

macOS 上的达梦 `dmPython` 兼容层。官方驱动没有 macOS 版，这里用 JayDeBeApi + 达梦 JDBC 实现 DBAPI 子集，让 `dmSQLAlchemy` 的 `dm+dmPython://` 方言能在本机跑起来。

**发行名是 `dmpython-jdbc`，import 名仍是 `dmPython`。** 业务代码不用改。

- macOS：使用本包的 JDBC shim
- 其它平台：把 `import dmPython` 转发给已安装的官方驱动

## 安装

PyPI：

```bash
pip install dmpython-jdbc
```

跨平台项目（Linux/Windows 用官方驱动，macOS 用本包）：

```toml
[project]
dependencies = [
    "dmpython>=2.5.32; sys_platform != 'darwin'",
    "dmpython-jdbc>=2.5.32; sys_platform == 'darwin'",
]
```

从 GitHub 安装：

```bash
pip install "dmpython-jdbc @ git+https://github.com/Darley-Wey/dmpython-jdbc.git"
```

uv：

```toml
[tool.uv.sources]
dmpython-jdbc = { git = "https://github.com/Darley-Wey/dmpython-jdbc.git" }
```

需要钉到某个提交或 tag 时，在 URL 后加 `@<ref>`，例如 `@main` 或 `@v2.5.32`。

## 运行依赖

- Python >= 3.12
- JDK（macOS 可用 `brew install openjdk`）。`JAVA_HOME` 会自动探测 `/opt/homebrew/opt/openjdk` 和 `/usr/local/opt/openjdk`
- 达梦 JDBC 驱动已打包进 wheel；也可用环境变量 `DM_JDBC_JAR` 覆盖

## 限制

不支持存储过程出参（`cursor.var`）、LOB 流式读写等高级特性，覆盖 ORM CRUD 即可。

## 许可证

Python 兼容层使用 MIT。仓库中的 `DmJdbcDriver18-*.jar` 是达梦官方 JDBC 驱动，版权归达梦数据库所有，不受 MIT 覆盖。
