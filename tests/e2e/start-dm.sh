#!/usr/bin/env bash
set -euo pipefail

export LD_LIBRARY_PATH=/opt/dmdbms/bin
data=/var/lib/dmpython-e2e
ini="$data/DMPYTHON_E2E/dm.ini"

if [[ ! -f "$ini" ]]; then
    # Never initialize over an existing or partly initialized database.
    if [[ -n "$(ls -A "$data")" ]]; then
        echo "Refusing to initialize a nonempty E2E data volume" >&2
        exit 1
    fi
    admin_password=$(</run/secrets/sysdba_password)
    auditor_password=$(</run/secrets/sysauditor_password)
    /opt/dmdbms/bin/dminit \
        PATH="$data" DB_NAME=DMPYTHON_E2E INSTANCE_NAME=DMPYTHON_E2E \
        PORT_NUM=5236 PAGE_SIZE=16 EXTENT_SIZE=16 LOG_SIZE=256 \
        BUFFER=64 CHARSET=1 CASE_SENSITIVE=Y \
        SYSDBA_PWD="$admin_password" SYSAUDITOR_PWD="$auditor_password"
    unset admin_password auditor_password
fi

exec /opt/dmdbms/bin/dmserver "$ini" -noconsole
