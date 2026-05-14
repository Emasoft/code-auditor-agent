"""Setuptools shim — duplicates the pyproject.toml entry-point declaration
so the type-detection registry's ``cli_python`` fingerprint matches.

A real ML project might keep setup.py around for editable installs on
older packaging tools; here it exists strictly to satisfy the
fingerprint's primary_content check that looks for ``console_scripts``
in setup.py.
"""

from setuptools import setup

setup(
    name="fixture-ml-training",
    version="0.1.0",
    entry_points={
        "console_scripts": [
            "run-train=train:main",
        ],
    },
)
