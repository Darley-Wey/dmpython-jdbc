# Live Dameng end-to-end tests

This suite calls the real `dmAsync==1.0.0` wrapper, the installed `dmPython`
shim, JPype/JayDeBeApi, and the bundled Dameng JDBC driver against a DM8 server.
It does not use the unit tests' SQLite double.

## Provisioned target (2026-11-11)

- Client: macOS, Python 3.13, JDK 26.
- Endpoint: `192.168.137.1:15236`.
- Database / instance / user / schema: `DMPYTHON_E2E`.
- Server: DM8 `8.1.4.6`, case-sensitive, UTF-8.
- WSL deployment: `/opt/dmpython-e2e`; container `dmpython-e2e-db`;
  named data volume `dmpython-e2e-data`; 2 CPU / 2 GiB memory limit.
- Image ID used on this host:
  `sha256:9a2d9aecc31372c8f7c765625f36987a54ce69aa015eb3d856cfa1e29b06811b`.
  It must contain `/opt/dmdbms/bin/dminit` and `dmserver`; the image's original
  startup script and any existing database volumes are not used.

## Run from the repository root on macOS

The provisioned client's `.env.e2e` contains the test account password, has mode
`0600`, and is Git-ignored. No administrator password is stored in the repository.
For another client, copy `.env.example` to the repository root as `.env.e2e`
and obtain the test account credentials from the deployment administrator.

```bash
bash tests/e2e/test.sh
```

This creates a separate `.venv-e2e`, installs the current working tree as a
non-editable wheel, runs the unit tests, and then runs the live suite in a new
Python process. `-I` ensures imports come from the installed wheel. It also
installs `async-timeout`, which dmAsync 1.0.0 imports but does not declare.

For subsequent runs using the already installed build:

```bash
.venv-e2e/bin/python -I tests/e2e/run.py --env-file .env.e2e
```

Environment variables override `.env.e2e` through `python-dotenv`. The runner
requires explicit `DM_E2E_ALLOW_WRITE=1`, the dedicated account/schema and the
`E2E_TARGET` sentinel. It creates random `E2E_<hex>` tables and drops only those
tables in teardown. The latest credential-free report is saved to
`tests/e2e/reports/latest.json`; errors, skipped tests and empty suites fail the run.

Coverage includes connection metadata and actual JDBC class identity, batch
and named binds, Unicode, BLOB/VARBINARY byte equality, microsecond timestamps,
NULLs, identity values, cross-connection commit/rollback visibility, autocommit,
concurrent independent transactions, database errors and closed handles.

## Host operation and reproducibility

The compose file deliberately requires `DM_E2E_IMAGE`; use a DM8 image you are
authorized to run. On the host, create `/opt/dmpython-e2e/secrets/` with mode
`0700` and generate separate strong passwords in `sysdba_password.txt`,
`sysauditor_password.txt`, and `app_password.txt` (files mode `0600`). Keep the
image ID in `/opt/dmpython-e2e/.env` and the client settings from `.env.example`
in `/opt/dmpython-e2e/e2e.env`, using the application password. Place
`compose.yaml`, `start-dm.sh` and `healthcheck.sh` alongside them, then run
`docker compose up -d --wait --wait-timeout 90`.
`start-dm.sh` refuses to initialize a nonempty data volume.
The health check executes a SQL query; an open TCP port alone is not considered ready.
