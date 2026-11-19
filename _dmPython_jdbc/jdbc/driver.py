"""Locate the JDK and the Dameng JDBC driver, and open JayDeBeApi connections."""
import glob
import os

from ..exceptions import InterfaceError, OperationalError
from .converters import install_result_converters

DRIVER_CLASS = "dm.jdbc.driver.DmDriver"

# The driver JAR is packaged next to the top-level package's __init__.py.
_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_jar():
    jar = os.environ.get("DM_JDBC_JAR")
    if jar and os.path.exists(jar):
        return jar
    here = _PACKAGE_DIR
    packaged = sorted(glob.glob(os.path.join(here, "DmJdbcDriver*.jar")))
    if packaged:
        return packaged[-1]
    for base in (os.path.dirname(here), os.getcwd()):
        hits = sorted(glob.glob(os.path.join(base, "libs", "DmJdbcDriver*.jar"))) \
            or sorted(glob.glob(os.path.join(base, "DmJdbcDriver*.jar")))
        if hits:
            return hits[-1]
    raise InterfaceError("Dameng JDBC driver JAR not found; set DM_JDBC_JAR")


def ensure_java_home():
    if os.environ.get("JAVA_HOME"):
        return
    for cand in ("/opt/homebrew/opt/openjdk", "/usr/local/opt/openjdk"):
        if os.path.exists(os.path.join(cand, "bin", "java")):
            os.environ["JAVA_HOME"] = cand
            return


def open_connection(url, user, password):
    """A JayDeBeApi connection whose results come back in dmPython's shapes."""
    import jaydebeapi

    ensure_java_home()
    try:
        jconn = jaydebeapi.connect(DRIVER_CLASS, url, [user, password], find_jar())
        install_result_converters(jconn)
    except Exception as e:
        raise OperationalError(f"Dameng JDBC connection failed: {e}") from e
    return jconn
