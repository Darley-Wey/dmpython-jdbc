"""Run live tests in a separate process from unit-test monkeypatches."""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import time
import unittest

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.e2e"))
    parser.add_argument("--report", type=Path, default=Path("tests/e2e/reports/latest.json"))
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    if os.environ.get("DM_E2E_ALLOW_WRITE") != "1":
        parser.error("Live tests require DM_E2E_ALLOW_WRITE=1 and dedicated E2E credentials")
    required = ("HOST", "PORT", "USER", "PASSWORD", "SCHEMA")
    if any(not os.environ.get("DM_E2E_" + key) for key in required):
        parser.error("Missing E2E connection settings")
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern="test_live_*.py")
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and bool(result.testsRun) and not result.skipped
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": os.environ["DM_E2E_HOST"] + ":" + os.environ["DM_E2E_PORT"],
        "schema": os.environ["DM_E2E_SCHEMA"],
        "python": sys.version.split()[0],
        "packages": {name: version(name) for name in ("dmAsync", "dmpython-jdbc", "JayDeBeApi", "JPype1")},
        "tests_run": result.testsRun,
        "failures": [str(test) for test, _ in result.failures],
        "errors": [str(test) for test, _ in result.errors],
        "skipped": [str(test) for test, _ in result.skipped],
        "seconds": round(time.monotonic() - started, 3),
        "passed": bool(passed),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"E2E report: {args.report}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
