"""Make importlib.metadata.version("dmPython") resolve to this shim."""

from __future__ import annotations

import importlib.metadata as metadata

_DRIVER_VERSION = "2.5.32"


def _is_dmpython(name: str) -> bool:
    normalized = name.lower().replace("-", "").replace("_", "").replace(".", "")
    return normalized == "dmpython"


if not getattr(metadata, "_dmpython_jdbc_alias", False):
    _orig_distribution = metadata.distribution

    def version(distribution_name: str) -> str:
        try:
            return _orig_distribution(distribution_name).version
        except metadata.PackageNotFoundError:
            if _is_dmpython(distribution_name):
                return _DRIVER_VERSION
            raise

    metadata.version = version
    metadata._dmpython_jdbc_alias = True
