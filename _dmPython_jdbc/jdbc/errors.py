"""JDBC failures as DBAPI exceptions."""
from ..exceptions import DatabaseError, InterfaceError


def to_dbapi_error(exc):
    """The DBAPI exception to raise for a failed JDBC statement.

    dmSQLAlchemy.is_disconnect only treats InterfaceError("not connected") as a
    dropped connection, so closed-connection failures take that shape and the
    pool can discard and reconnect.
    """
    msg = str(exc)
    # Dameng JDBC uses these Chinese phrases for a closed connection.
    if "尚未建立" in msg or "已经关闭" in msg or "not connected" in msg.lower() or "connection closed" in msg.lower():
        return InterfaceError("not connected")
    return DatabaseError(msg)
