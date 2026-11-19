"""Convert values between Python and JDBC, in the shapes official dmPython uses."""
import datetime


def timestamp_to_datetime(result_set, column):
    """Convert a JDBC TIMESTAMP to the datetime shape official dmPython returns."""
    value = result_set.getTimestamp(column)
    if value is None:
        return None

    parsed = datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    return parsed.replace(microsecond=int(value.getNanos()) // 1000)


def binary_to_bytes(result_set, column):
    """Preserve binary column contents rather than stringifying a Java array."""
    value = result_set.getBytes(column)
    return None if value is None else bytes(value)


def install_result_converters(jconn):
    """Make `jconn` read timestamps and binary columns with the converters above."""
    import jaydebeapi

    # JayDeBeApi shares its default converter dictionary across connections.
    jconn._converters = jconn._converters.copy()
    for name, converter in (
        ("TIMESTAMP", timestamp_to_datetime),
        ("BINARY", binary_to_bytes),
        ("VARBINARY", binary_to_bytes),
        ("LONGVARBINARY", binary_to_bytes),
    ):
        type_code = jaydebeapi._jdbc_name_to_const.get(name)
        if type_code is not None:
            jconn._converters[type_code] = converter


def to_jdbc_parameter(value):
    # setObject otherwise selects a string conversion for Python bytes.
    if isinstance(value, (bytes, bytearray, memoryview)):
        import jaydebeapi
        return jaydebeapi.Binary(bytes(value))
    return value


def row_to_python(row):
    """jaydebeapi returns java.sql.Clob/Blob; official dmPython returns str/bytes.
    Normalize so ORM assignment does not fail."""
    if row is None:
        return None
    items = []
    for v in row:
        # JPype proxies look like _jp_java.sql.Clob or java.sql.Clob
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
