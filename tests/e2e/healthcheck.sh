#!/usr/bin/env bash
set -euo pipefail
export LD_LIBRARY_PATH=/opt/dmdbms/bin
password=$(</run/secrets/sysdba_password)
# Keep credentials off process arguments and out of Docker health-check logs.
output=$({
    printf 'CONNECT SYSDBA/"%s"@127.0.0.1:5236\n' "$password"
    printf "SET ECHO OFF\nSELECT 'DMPYTHON_E2E_READY' FROM DUAL;\nEXIT;\n"
} | /opt/dmdbms/bin/disql -S /nolog 2>&1)
unset password
grep -Eq '^[[:space:]]*[0-9]+[[:space:]]+DMPYTHON_E2E_READY[[:space:]]*$' <<< "$output"
