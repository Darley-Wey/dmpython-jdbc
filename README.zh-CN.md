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

从 Git 安装：

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

## 作为 dmAsync 的 dmPython 后端

本包支持 `dmAsync==1.0.0` 使用的基础连接和游标接口：`connect`、`execute`、
`executemany`、`fetchone`/`fetchmany`/`fetchall`、异步迭代、`commit`、`rollback`
和 `ping`。dmAsync 使用 `asyncio.to_thread` 调用同步 shim 完成这些数据库操作；
dmAsync 1.0.0 的建连和关闭仍是同步操作。

macOS 上在开发版仓库目录中安装：

```bash
python -m pip install . "async-timeout>=4,<6"
python -m pip install "dmAsync==1.0.0" --no-deps
```

`dmAsync` 无条件依赖官方 `dmPython`，因此使用 uv 时，需要保留上文的
`[tool.uv].override-dependencies` 配置，并在项目依赖中加入 `dmAsync==1.0.0`
和 `async-timeout>=4,<6`。dmAsync 1.0.0 导入了 `async_timeout`，但没有在包元数据中
声明该依赖。运行时的版本别名不能代替这些依赖解析配置。

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
        login_timeout=5000,  # 毫秒，直接传给 dmPython。
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

`Connection.version` 返回服务端版本；标识符长度限制从 JDBC 元数据读取，未知时
返回 `None`。shim 不实现 Python 层语句缓存，因此 `stmtcachesize` 为 `0`，
不支持设为非零值。`status` 表示 shim 连接状态（`1` 开启、`0` 关闭），不是 DPI
事务状态码。修改 `autocommit` 会同步到 JDBC 连接。

同一连接的 JDBC 操作会在线程间串行执行。并发任务应各自持有连接：锁无法隔离事务，
也无法保证多个任务共享游标时 execute/fetch 的先后关系。取消 await 不会终止线程中
已经开始的 JDBC 操作；重新使用或关闭该连接前，应等待操作结束。`callproc`、
`callfunc`、显式 `prepare`、`mogrify`、游标滚动、跨提交保留游标以及多结果集仍不支持，
调用会抛出 `NotSupportedError`。这些适配不代表已完整验证 SQLAlchemy 的
`dm+dmasync://` 方言或 dmAsync 连接池。

### 适配测试

安装上述依赖后执行：

```bash
python -m unittest discover -s tests -v
```

测试使用真实 dmAsync 包，在 JayDeBeApi 边界用 SQLite 模拟数据库，覆盖初始化、
CRUD、事务、游标生命周期和连接级锁，不需要达梦服务器。

真库验证见 [达梦端到端测试说明](tests/e2e/README.md)。配置专用测试账号后，执行
`bash tests/e2e/test.sh` 即可构建并测试实际安装的 wheel，覆盖二进制/LOB 数据往返、
跨连接事务可见性等。
## 限制

不支持存储过程出参（`cursor.var`）、LOB 流式读写等高级特性，覆盖 ORM CRUD 即可。

## 许可证

Python 兼容层使用 MIT。仓库中的 `DmJdbcDriver18-*.jar` 是达梦官方 JDBC 驱动，版权归达梦数据库所有，不受 MIT 覆盖。
