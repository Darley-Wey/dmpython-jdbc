"""JDBC layer: what the DBAPI objects need to know about Java, JayDeBeApi and
Dameng's JDBC driver.

  driver          locate the JDK and the driver JAR, open connections
  converters      values between Python and JDBC
  sql             statement text as JDBC expects it
  generated_keys  the key an INSERT generated
  errors          JDBC failures as DBAPI exceptions

Nothing here imports the DBAPI objects; only the shared exceptions.
"""
