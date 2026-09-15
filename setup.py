from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    def run(self):
        super().run()
        Path(self.build_lib, "dmpython_jdbc.pth").write_text(
            "import _dmpython_metadata\n", encoding="utf-8"
        )


setup(cmdclass={"build_py": build_py})
