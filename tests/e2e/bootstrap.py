"""Provision only the isolated DMPYTHON_E2E database deployed by compose.yaml.

Run on the macOS test client after installing the working-tree wheel.
Administrator secrets stay on the Windows/WSL host and are never printed.
"""

import argparse
from io import StringIO
import os
from pathlib import Path
import re
import subprocess

from dotenv import dotenv_values
import dmPython


def remote_read(host, path):
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host,
         f"wsl -d Ubuntu -u root -- cat /opt/dmpython-e2e/{path}"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", default="nancal")
    parser.add_argument("--env-file", type=Path, default=Path(".env.e2e"))
    args = parser.parse_args()
    text = remote_read(args.ssh_host, "e2e.env") + "\n"
    config = dotenv_values(stream=StringIO(text))
    admin_password = remote_read(args.ssh_host, "secrets/sysdba_password.txt")
    password = config["DM_E2E_PASSWORD"]
    if not re.fullmatch(r"[A-Za-z0-9_]{16,48}", password):
        raise RuntimeError("Unexpected generated password format")
    if config["DM_E2E_USER"] != "DMPYTHON_E2E" or config["DM_E2E_SCHEMA"] != "DMPYTHON_E2E":
        raise RuntimeError("Refusing to provision outside DMPYTHON_E2E")
    if args.env_file.exists() and args.env_file.read_text() != text:
        raise RuntimeError("Local E2E configuration differs; refusing to overwrite it")

    admin = dmPython.connect(
        host=config["DM_E2E_HOST"], port=int(config["DM_E2E_PORT"]),
        user="SYSDBA", password=admin_password, autoCommit=True,
        login_timeout=5000, connection_timeout=30,
    )
    try:
        with admin.cursor() as cursor:
            cursor.execute("SELECT NAME FROM V$DATABASE")
            if cursor.fetchone()[0] != "DMPYTHON_E2E":
                raise RuntimeError("Refusing to provision a database not named DMPYTHON_E2E")
            cursor.execute("SELECT COUNT(*) FROM DBA_USERS WHERE USERNAME=?", ["DMPYTHON_E2E"])
            if cursor.fetchone()[0] == 0:
                cursor.execute(f'CREATE USER DMPYTHON_E2E IDENTIFIED BY "{password}" DEFAULT TABLESPACE MAIN')
                cursor.execute("GRANT CREATE SESSION, CREATE TABLE TO DMPYTHON_E2E")
            cursor.execute("SELECT COUNT(*) FROM DBA_TABLES WHERE OWNER=? AND TABLE_NAME=?",
                           ["DMPYTHON_E2E", "E2E_TARGET"])
            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE TABLE DMPYTHON_E2E.E2E_TARGET (TARGET VARCHAR(64) NOT NULL)")
                cursor.execute("INSERT INTO DMPYTHON_E2E.E2E_TARGET VALUES (?)", ["dmpython-jdbc-e2e"])
            print(f"Provisioned DMPYTHON_E2E; server version: {admin.server_version}")
    finally:
        admin.close()

    # Verify the least-privilege account before saving client configuration.
    conn = dmPython.connect(
        host=config["DM_E2E_HOST"], port=int(config["DM_E2E_PORT"]),
        user="DMPYTHON_E2E", password=password, schema="DMPYTHON_E2E",
        autoCommit=True, login_timeout=5000, connection_timeout=30,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT TARGET FROM E2E_TARGET")
            if cursor.fetchall() != [("dmpython-jdbc-e2e",)]:
                raise RuntimeError("E2E database sentinel is missing or incorrect")
    finally:
        conn.close()
    if not args.env_file.exists():
        fd = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(text)
    print(f"Verified test account; credentials saved to {args.env_file} (not displayed)")


if __name__ == "__main__":
    main()
