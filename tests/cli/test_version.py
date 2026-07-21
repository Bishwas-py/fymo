"""fymo.__version__ / `fymo --version` report the installed version (issue #47).

The version has exactly one source of truth, pyproject.toml, read at runtime
through importlib.metadata. A second hardcoded copy in fymo/__init__.py went
stale at 0.1.0 while releases marched on; these pin that it can never drift
again (any hardcoded string would fail the metadata comparison on the next
bump).
"""
from importlib.metadata import version as installed_version

from click.testing import CliRunner

import fymo
from fymo.cli.main import cli


def test_dunder_version_matches_installed_metadata():
    assert fymo.__version__ == installed_version("fymo")


def test_cli_version_flag_reports_installed_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert installed_version("fymo") in result.output
