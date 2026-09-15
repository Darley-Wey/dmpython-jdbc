"""Pick the official Dameng driver or the macOS JDBC shim."""

import _dmpython_metadata  # noqa: F401

import importlib.machinery
import importlib.util
import sys
from pathlib import Path


if sys.platform == "darwin":
    from _dmPython_jdbc import *  # noqa: F403
else:
    shim_dir = Path(__file__).resolve().parent
    search_paths = [
        path
        for path in sys.path
        if Path(path or ".").resolve() != shim_dir
    ]
    spec = importlib.machinery.PathFinder.find_spec(__name__, search_paths)
    if spec is None or spec.loader is None:
        raise ImportError(
            "This platform requires the official Dameng dmPython driver, "
            "which was not found on sys.path"
        )

    native_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native_module)
    sys.modules[__name__] = native_module
    globals().update(native_module.__dict__)
