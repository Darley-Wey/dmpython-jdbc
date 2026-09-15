# dmpython-jdbc

[English](README.md) | [简体中文](README.zh-CN.md)

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

如果项目还依赖 `dmSQLAlchemy`，见 [配合 dmSQLAlchemy](#配合-dmsqlalchemy)。该包会无条件拉取官方 `dmpython`。

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


## 配合 dmSQLAlchemy

`dmSQLAlchemy` 无条件依赖官方 `dmpython`（`Requires-Dist: dmPython`）。该包没有 macOS wheel，所以在 Mac 上 `pip install dmSQLAlchemy` 会尝试装达梦官方驱动并失败。

要保留 `dmSQLAlchemy`，又阻止解析器在 macOS 上装官方 `dmpython`，改装 `dmpython-jdbc`。import 名仍是 `dmPython`。

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

`override-dependencies` 会改写 `dmSQLAlchemy` 对 `dmpython` 的依赖，让它在 macOS 上被跳过；然后由 `dmpython-jdbc` 提供 `dmPython` 模块。

`dmSQLAlchemy.extensions` 会调用 `importlib.metadata.version("dmPython")`。本包会安装 `.pth` 钩子，让这次查询返回 shim 版本 `2.5.32`，不依赖 setuptools/`pkg_resources`。

### macOS 上的 pip

```bash
pip install "dmSQLAlchemy" --no-deps
pip install "SQLAlchemy>1.4.54" dmpython-jdbc
```

## 限制

不支持存储过程出参（`cursor.var`）、LOB 流式读写等高级特性，覆盖 ORM CRUD 即可。

## 许可证

Python 兼容层使用 MIT。仓库中的 `DmJdbcDriver18-*.jar` 是达梦官方 JDBC 驱动，版权归达梦数据库所有，不受 MIT 覆盖。
