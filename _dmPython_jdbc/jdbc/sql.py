"""Statement text as JDBC expects it."""
import re

# Rewrite :name binds to JDBC `?`, skipping string literals and `::` casts.
_BIND_RE = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")
_INSERT_RE = re.compile(r"\s*insert\b", re.I)


def named_to_qmark(sql):
    """`sql` with its :name binds as `?`, and the names in bind order."""
    names = []
    result = []
    last = 0
    for m in _BIND_RE.finditer(sql):
        # Odd number of quotes before this match means we are inside a string.
        if (sql[:m.start()].count("'") % 2) == 1:
            continue
        result.append(sql[last:m.start()])
        result.append("?")
        names.append(m.group(1))
        last = m.end()
    result.append(sql[last:])
    return "".join(result), names


def is_insert(sql):
    return bool(_INSERT_RE.match(sql))
