"""Run the real dmAsync wrapper against the shim, with SQLite at the JDBC boundary.

This exercises the adapter contract and transactions without a Dameng server.
Install dmAsync with --no-deps and install async-timeout and JayDeBeApi separately.
"""

import asyncio
from contextlib import contextmanager
import sqlite3
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

import _dmPython_jdbc as shim

# The production dmPython loader selects JDBC on macOS. Use that same backend
# on other test platforms without attempting to load the native Dameng driver.
with patch.dict(sys.modules, {"dmPython": shim}):
    import dmAsync


class SQLiteJDBC:
    """A small JayDeBeApi connection double backed by real SQL transactions."""

    def __init__(self):
        self.sql = sqlite3.connect(":memory:", check_same_thread=False)
        self._converters = {}
        self.is_closed = False
        self.active = 0
        self.max_active = 0
        self.delay = 0
        self.threads = set()
        self._counter_lock = threading.Lock()
        metadata = Mock()
        metadata.getDatabaseProductVersion.return_value = "8.1.4.99"
        metadata.getMaxColumnNameLength.return_value = 128
        metadata.getMaxTableNameLength.return_value = 256
        self.jconn = Mock()
        self.jconn.getMetaData.return_value = metadata
        self.jconn.isClosed.side_effect = lambda: self.is_closed
        self.jconn.getAutoCommit.side_effect = lambda: self.sql.isolation_level is None
        self.jconn.setAutoCommit.side_effect = self.set_autocommit

    def set_autocommit(self, enabled):
        self.sql.isolation_level = None if enabled else "DEFERRED"

    @contextmanager
    def access(self):
        with self._counter_lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.threads.add(threading.get_ident())
        try:
            if self.delay:
                time.sleep(self.delay)
            yield
        finally:
            with self._counter_lock:
                self.active -= 1

    def cursor(self):
        return SQLiteCursor(self)

    def commit(self):
        with self.access():
            self.sql.commit()

    def rollback(self):
        with self.access():
            self.sql.rollback()

    def close(self):
        with self.access():
            self.sql.close()
            self.is_closed = True


class SQLiteCursor:
    def __init__(self, connection):
        self.connection = connection
        self.cursor = connection.sql.cursor()

    @property
    def description(self):
        return self.cursor.description

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def execute(self, sql, parameters=None):
        sql = {
            "SELECT CASE_SENSITIVE()": "SELECT 1",
            "SELECT SCOPE_IDENTITY()": "SELECT last_insert_rowid()",
        }.get(sql, sql)
        with self.connection.access():
            self.cursor.execute(sql, parameters or ())

    def executemany(self, sql, parameters):
        with self.connection.access():
            self.cursor.executemany(sql, parameters)

    def fetchone(self):
        with self.connection.access():
            return self.cursor.fetchone()

    def fetchmany(self, size):
        with self.connection.access():
            return [] if size == 0 else self.cursor.fetchmany(size)

    def fetchall(self):
        with self.connection.access():
            return self.cursor.fetchall()

    def close(self):
        self.cursor.close()


class DmAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backends = []
        self.connections = []

        def connect_jdbc(*args):
            backend = SQLiteJDBC()
            self.backends.append(backend)
            return backend

        self.jdbc_connect = self.enterContext(patch("jaydebeapi.connect", side_effect=connect_jdbc))
        self.enterContext(patch("jaydebeapi._jdbc_name_to_const", {"TIMESTAMP": 93}))

    async def asyncTearDown(self):
        for connection in self.connections:
            await connection.close()
        for backend in self.backends:
            if not backend.is_closed:
                backend.close()

    async def connect(self, **kwargs):
        connection = await dmAsync.connect(
            host="localhost", port=5236, user="test", password="test",
            schema="PUBLIC", login_timeout=5000, **kwargs,
        )
        self.connections.append(connection)
        return connection

    async def test_initialization_and_connection_state(self):
        connection = await self.connect()
        self.assertEqual(connection.version, "8.1.4.99")
        self.assertEqual(connection.server_version, connection.version)
        self.assertEqual(connection.max_identifier_length, 128)
        self.assertEqual(connection.stmtcachesize, 0)
        self.assertIsNone(connection.outputtypehandler)
        self.assertEqual(connection.status, 1)
        self.assertTrue(connection.autocommit)
        args = self.jdbc_connect.call_args.args
        self.assertEqual(args[0], "dm.jdbc.driver.DmDriver")
        self.assertIn("loginTimeout=5", args[1])
        self.assertIn("socketTimeout=0", args[1])
        await connection.ping(False)
        await connection.close()
        self.assertTrue(connection.raw.closed)
        self.assertEqual(connection.status, 0)
        await connection.get_closed()
        self.assertTrue(connection.closed)

    async def test_crud_commit_rollback_and_iteration(self):
        connection = await self.connect(autoCommit=False)
        cursor = await connection.cursor()
        try:
            self.assertIn("name=None", repr(cursor))
            self.assertFalse(cursor.scrollable)
            self.assertFalse(cursor.withhold)
            await cursor.executedirect("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
            await cursor.executemany("INSERT INTO items VALUES (?, ?)", [(1, "one"), (2, "two")])
            self.assertEqual(cursor.rowcount, 2)
            await connection.commit()
            await cursor.execute("UPDATE items SET name=:name WHERE id=:id", {"name": "changed", "id": 1})
            await connection.rollback()
            await cursor.execute("SELECT id, name FROM items ORDER BY id")
            self.assertEqual(cursor.rownumber, 0)
            self.assertEqual(cursor.description[0][0], "id")
            self.assertEqual(await cursor.fetchmany(0), [])
            self.assertEqual(await cursor.next(), (1, "one"))
            self.assertEqual(cursor.rownumber, 1)
            cursor.arraysize = 1
            self.assertEqual(await cursor.fetchmany(), [(2, "two")])
            self.assertEqual(cursor.rownumber, 2)
            await cursor.execute("SELECT name FROM items ORDER BY id")
            self.assertEqual([row async for row in cursor], [("one",), ("two",)])
            self.assertEqual(cursor.query, "SELECT name FROM items ORDER BY id")
            await cursor.execute("DELETE FROM items WHERE id=?", [1])
            await connection.commit()
            await cursor.execute("SELECT id FROM items")
            self.assertEqual(await cursor.fetchall(), [(2,)])
        finally:
            await cursor.close()

    async def test_autocommit_changes_reach_jdbc(self):
        connection = await self.connect(autoCommit=False)
        cursor = await connection.cursor()
        try:
            await cursor.execute("CREATE TABLE items (id INTEGER)")
            connection.autocommit = True
            self.assertTrue(self.backends[0].jconn.getAutoCommit())
            await cursor.execute("INSERT INTO items VALUES (1)")
            await connection.rollback()
            connection.autocommit = False
            await cursor.execute("INSERT INTO items VALUES (2)")
            await connection.rollback()
            await cursor.execute("SELECT id FROM items")
            self.assertEqual(await cursor.fetchall(), [(1,)])
            connection.raw.autoCommit = True
            self.assertTrue(connection.autocommit)
        finally:
            await cursor.close()

    async def test_async_context_managers_close_resources(self):
        async with await self.connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                self.assertEqual(await cursor.fetchone(), (1,))
            self.assertTrue(cursor.raw.closed)
        self.assertTrue(connection.raw.closed)

    async def test_sequential_calls_can_move_between_workers(self):
        connection = await self.connect()
        cursor = await connection.cursor()
        try:
            await cursor.execute("SELECT 42")
            self.assertEqual(await cursor.fetchone(), (42,))
            self.assertTrue(self.backends[0].threads - {threading.get_ident()})
        finally:
            await cursor.close()

    async def test_jdbc_operations_on_one_connection_are_serialized(self):
        connection = await self.connect()
        cursors = [await connection.cursor() for _ in range(4)]
        self.backends[0].delay = 0.01
        try:
            # Distinct cursors avoid sharing a result set. Application tasks
            # must still own separate connections for independent transactions.
            await asyncio.gather(*(cursor.execute("SELECT 1") for cursor in cursors))
            self.assertEqual(self.backends[0].max_active, 1)
            self.assertEqual(await asyncio.gather(*(c.fetchone() for c in cursors)), [(1,)] * 4)
        finally:
            self.backends[0].delay = 0
            for cursor in cursors:
                await cursor.close()

    async def test_connections_do_not_share_a_global_lock(self):
        first, second = await self.connect(), await self.connect()
        barrier = threading.Barrier(2, timeout=3)

        def meet():
            barrier.wait()

        with patch.object(self.backends[0], "commit", side_effect=meet), patch.object(
            self.backends[1], "commit", side_effect=meet
        ):
            await asyncio.gather(first.commit(), second.commit())

    async def test_unsupported_cursor_apis_raise_dbapi_error(self):
        connection = await self.connect()
        cursor = await connection.cursor()
        try:
            for method, args in [(cursor.callproc, ("p",)), (cursor.callfunc, ("f",)),
                                 (cursor.prepare, ("SELECT 1",)), (cursor.scroll, (1,)),
                                 (cursor.nextset, ())]:
                with self.subTest(method=method.__name__):
                    with self.assertRaises(shim.NotSupportedError):
                        await method(*args)
            with self.assertRaises(shim.NotSupportedError):
                cursor.scrollable = True
            with self.assertRaises(shim.NotSupportedError):
                cursor.withhold = True
            with self.assertRaises(shim.NotSupportedError):
                cursor.mogrify("SELECT ?", [1])
            with self.assertRaises(shim.NotSupportedError):
                connection.raw.stmtcachesize = 10
            connection.raw.stmtcachesize = 0
        finally:
            await cursor.close()

    async def test_closed_cursor_and_driver_closed_connection(self):
        connection = await self.connect()
        cursor = await connection.cursor()
        await cursor.execute("SELECT 1")
        await cursor.close()
        with self.assertRaisesRegex(shim.InterfaceError, "not connected"):
            await cursor.fetchone()
        self.backends[0].jconn.isClosed.side_effect = None
        self.backends[0].jconn.isClosed.return_value = True
        self.assertEqual(connection.status, 0)
        with self.assertRaisesRegex(shim.InterfaceError, "not connected"):
            await connection.cursor()

    async def test_unknown_identifier_length_is_not_invented(self):
        backend = SQLiteJDBC()
        self.backends.append(backend)
        metadata = backend.jconn.getMetaData.return_value
        metadata.getMaxColumnNameLength.return_value = 0
        metadata.getMaxTableNameLength.return_value = 0
        self.assertIsNone(shim.Connection(backend).max_identifier_length)


if __name__ == "__main__":
    unittest.main()
