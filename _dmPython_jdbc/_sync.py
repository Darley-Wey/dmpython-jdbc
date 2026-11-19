"""Per-connection locking shared by Connection and Cursor."""
from functools import wraps


def serialized(method):
    """Serialize JDBC access across dmAsync's worker threads per connection."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return locked
