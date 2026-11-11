"""Opt-in end-to-end tests: real dmAsync -> dmPython shim -> JDBC -> DM8.

Use run.py to load .env.e2e. Only randomly named tables created by this run are
dropped; E2E_TARGET must already identify this as the dedicated test database.
"""

import asyncio
from datetime import datetime
import os
import re
import unittest
from uuid import uuid4

import dmAsync
import dmPython
import jpype


class LiveDmAsyncTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("DM_E2E_ALLOW_WRITE") != "1":
            raise unittest.SkipTest("Set DM_E2E_ALLOW_WRITE=1 for the dedicated E2E database")
        if os.environ.get("DM_E2E_USER") != "DMPYTHON_E2E" or os.environ.get("DM_E2E_SCHEMA") != "DMPYTHON_E2E":
            raise RuntimeError("E2E tests require the dedicated DMPYTHON_E2E account and schema")
        cls.settings = dict(
            host=os.environ["DM_E2E_HOST"], port=int(os.environ["DM_E2E_PORT"]),
            user=os.environ["DM_E2E_USER"], password=os.environ["DM_E2E_PASSWORD"],
            schema=os.environ["DM_E2E_SCHEMA"], login_timeout=5000, connection_timeout=30,
        )
        # This must be the installed public import, not a sys.modules test double.
        if dmAsync.connection.dmPython is not dmPython or dmPython.connect.__module__ != "_dmPython_jdbc":
            raise RuntimeError("E2E tests did not load the real dmPython JDBC shim")

    async def asyncSetUp(self):
        self.connections = []
        self.tables = []
        self.conn = await self.connect()
        try:
            with self.conn.raw.cursor() as cursor:
                cursor.execute("SELECT TARGET FROM E2E_TARGET")
                self.assertEqual(cursor.fetchall(), [("dmpython-jdbc-e2e",)])
        except Exception:
            await self.conn.close()
            raise

    async def asyncTearDown(self):
        errors = []
        for conn in self.connections:
            if not conn.raw.closed:
                await conn.rollback()
        for table in self.tables:
            try:
                with self.conn.raw.cursor() as cursor:
                    cursor.execute(f'DROP TABLE "{table}"')
            except Exception as error:
                errors.append(error)
        for conn in reversed(self.connections):
            await conn.close()
        if errors:
            raise RuntimeError(f"Could not clean up {len(errors)} E2E table(s)") from errors[0]

    async def connect(self, **kwargs):
        conn = await dmAsync.connect(**self.settings, autoCommit=kwargs.get("autoCommit", False))
        self.connections.append(conn)
        return conn

    async def table(self, columns="ID INTEGER PRIMARY KEY, NAME VARCHAR(128)"):
        table = "E2E_" + uuid4().hex[:20].upper()
        assert re.fullmatch(r"E2E_[A-F0-9]{20}", table)
        with self.conn.raw.cursor() as cursor:
            cursor.execute(f'CREATE TABLE "{table}" ({columns})')
        self.tables.append(table)
        return table

    async def scalar(self, conn, sql, params=None):
        cur = await conn.cursor()
        try:
            await cur.execute(sql, params)
            return (await cur.fetchone())[0]
        finally:
            await cur.close()

    async def test_metadata_and_real_jvm_driver(self):
        self.assertTrue(jpype.isJVMStarted())
        raw = self.conn.raw._jconn.jconn
        self.assertEqual(str(raw.getClass().getName()), "dm.jdbc.driver.DmdbConnection")
        self.assertEqual(self.conn.version, str(raw.getMetaData().getDatabaseProductVersion()))
        self.assertEqual(self.conn.max_identifier_length, 128)
        self.assertEqual(self.conn.stmtcachesize, 0)
        self.assertEqual(self.conn.status, 1)
        self.assertEqual(await self.scalar(self.conn, "SELECT USER FROM DUAL"), "DMPYTHON_E2E")
        await self.conn.ping(False)

    async def test_crud_batch_named_parameters_and_async_iteration(self):
        table = await self.table()
        cur = await self.conn.cursor()
        try:
            await cur.executemany(f'INSERT INTO "{table}" VALUES (?, ?)', [(1, "one"), (2, "二"), (3, "three")])
            self.assertEqual(cur.rowcount, 3)
            await self.conn.commit()
            await cur.execute(f'UPDATE "{table}" SET NAME=:name WHERE ID=:id', {"name": "updated", "id": 2})
            self.assertEqual(cur.rowcount, 1)
            await self.conn.commit()
            await cur.execute(f'SELECT ID, NAME FROM "{table}" ORDER BY ID')
            self.assertEqual(cur.description[0][0], "id")
            self.assertEqual(cur.rownumber, 0)
            self.assertEqual(await cur.fetchmany(0), [])
            self.assertEqual(await cur.next(), (1, "one"))
            cur.arraysize = 1
            self.assertEqual(await cur.fetchmany(), [(2, "updated")])
            self.assertEqual([row async for row in cur], [(3, "three")])
            self.assertEqual(cur.rownumber, 3)
            await cur.execute(f'DELETE FROM "{table}" WHERE ID=?', [3])
            await self.conn.commit()
            self.assertEqual(await self.scalar(self.conn, f'SELECT COUNT(*) FROM "{table}"'), 2)
        finally:
            await cur.close()

    async def test_commit_rollback_visibility_between_connections(self):
        table = await self.table()
        observer = await self.connect()
        cur = await self.conn.cursor()
        try:
            await cur.execute(f'INSERT INTO "{table}" VALUES (?, ?)', [1, "pending"])
            self.assertEqual(await self.scalar(self.conn, f'SELECT COUNT(*) FROM "{table}"'), 1)
            self.assertEqual(await self.scalar(observer, f'SELECT COUNT(*) FROM "{table}"'), 0)
            await self.conn.commit()
            self.assertEqual(await self.scalar(observer, f'SELECT COUNT(*) FROM "{table}"'), 1)
            await cur.execute(f'UPDATE "{table}" SET NAME=? WHERE ID=1', ["rolled back"])
            await self.conn.rollback()
            self.assertEqual(await self.scalar(observer, f'SELECT NAME FROM "{table}" WHERE ID=1'), "pending")
        finally:
            await cur.close()

    async def test_autocommit_reaches_server(self):
        table = await self.table()
        observer = await self.connect()
        cur = await self.conn.cursor()
        try:
            self.conn.autocommit = True
            self.assertTrue(self.conn.raw._jconn.jconn.getAutoCommit())
            await cur.execute(f'INSERT INTO "{table}" VALUES (?, ?)', [1, "committed"])
            self.assertEqual(await self.scalar(observer, f'SELECT COUNT(*) FROM "{table}"'), 1)
            self.conn.autocommit = False
            await cur.execute(f'INSERT INTO "{table}" VALUES (?, ?)', [2, "discarded"])
            await self.conn.rollback()
            self.assertEqual(await self.scalar(observer, f'SELECT COUNT(*) FROM "{table}"'), 1)
        finally:
            await cur.close()

    async def test_timestamp_unicode_binary_lob_and_null(self):
        table = await self.table("ID INTEGER PRIMARY KEY, TS TIMESTAMP(6), NAME VARCHAR(128), B BLOB, C CLOB, N VARCHAR(16)")
        timestamp = datetime(2026, 11, 11, 12, 34, 56, 123456)
        binary = bytes(range(256)) * 4
        text = "达梦 JDBC e2e 😀" * 1000
        cur = await self.conn.cursor()
        try:
            # JDBC accepts a SQL timestamp string without relying on JVM locale.
            await cur.execute(f'INSERT INTO "{table}" VALUES (?, ?, ?, ?, ?, ?)',
                              [1, timestamp.isoformat(" "), "中文 😀", binary, text, None])
            await self.conn.commit()
            await cur.execute(f'SELECT TS, NAME, B, C, N FROM "{table}" WHERE ID=1')
            row = await cur.fetchone()
            self.assertEqual(row, (timestamp, "中文 😀", binary, text, None))
            self.assertIsInstance(row[0], datetime)
            self.assertIsInstance(row[2], bytes)
            self.assertIsInstance(row[3], str)
        finally:
            await cur.close()

    async def test_identity_value(self):
        table = await self.table("ID INTEGER IDENTITY(1,1) PRIMARY KEY, NAME VARCHAR(128)")
        cur = await self.conn.cursor()
        try:
            await cur.execute(f'INSERT INTO "{table}" (NAME) VALUES (?)', ["identity"])
            identity = cur.lastrowid
            self.assertIsInstance(identity, int)
            self.assertEqual(identity, await self.scalar(self.conn, f'SELECT ID FROM "{table}"'))
            await self.conn.commit()
        finally:
            await cur.close()

    async def test_binary_batch_and_named_bindings(self):
        table = await self.table("ID INTEGER PRIMARY KEY, PAYLOAD VARBINARY(1024)")
        values = [bytes(range(256)), b"\x00\xff\x80", b"abc\x00def", None]
        cur = await self.conn.cursor()
        try:
            await cur.executemany(f'INSERT INTO "{table}" VALUES (?, ?)',
                                 [(1, values[0]), (2, bytearray(values[1]))])
            await cur.executemany(f'INSERT INTO "{table}" VALUES (:id, :data)',
                                 [{"id": 3, "data": memoryview(values[2])}, {"id": 4, "data": None}])
            await self.conn.commit()
            await cur.execute(f'SELECT PAYLOAD FROM "{table}" ORDER BY ID')
            rows = await cur.fetchall()
            self.assertEqual(rows, [(value,) for value in values])
            for row in rows[:3]:
                self.assertIsInstance(row[0], bytes)
        finally:
            await cur.close()

    async def test_parallel_connections_keep_transactions_separate(self):
        table = await self.table()
        conns = [await self.connect() for _ in range(4)]

        async def writer(conn, index):
            cur = await conn.cursor()
            try:
                for offset in range(5):
                    await cur.execute(f'INSERT INTO "{table}" VALUES (?, ?)', [index * 10 + offset, str(index)])
                if index % 2:
                    await conn.rollback()
                else:
                    await conn.commit()
            finally:
                await cur.close()

        await asyncio.wait_for(asyncio.gather(*(writer(c, i) for i, c in enumerate(conns))), 30)
        self.assertEqual(await self.scalar(self.conn, f'SELECT COUNT(*) FROM "{table}"'), 10)

    async def test_database_errors_and_closed_handles(self):
        table = await self.table()
        cur = await self.conn.cursor()
        try:
            await cur.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ["one"])
            await self.conn.commit()
            with self.assertRaises(dmPython.DatabaseError):
                await cur.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ["duplicate"])
            await self.conn.rollback()
            await cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            self.assertEqual(await cur.fetchone(), (1,))
            with self.assertRaises(dmPython.NotSupportedError):
                await cur.callproc("unsupported")
        finally:
            await cur.close()
        with self.assertRaisesRegex(dmPython.InterfaceError, "not connected"):
            await cur.fetchone()
        other = await self.connect()
        await other.close()
        self.assertEqual(other.status, 0)
        with self.assertRaisesRegex(dmPython.InterfaceError, "not connected"):
            await other.cursor()


if __name__ == "__main__":
    unittest.main()
