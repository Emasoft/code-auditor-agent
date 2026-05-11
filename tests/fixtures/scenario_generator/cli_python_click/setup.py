"""Legacy setup.py shim — kept ONLY to satisfy the cli_python fingerprint.

The fingerprint in scripts/scenario_generator/detect_software_type.py
requires BOTH `[project.scripts]` in pyproject.toml AND `console_scripts`
in setup.py to fire (its `_content_match` is AND-across-specs). Shipping
both keeps cli_python detection deterministic for this fixture.
"""

from setuptools import setup

setup(
    name="mycli",
    entry_points={
        "console_scripts": ["mycli = cli:cli"],
    },
)
