"""FymoApp.__init__ wires remote.mode into the router's dispatch gate
(fymo/core/server.py). An invalid remote: config must fail startup loudly,
the same posture as the existing StorageConfigError check a few lines below
it in the same function, see test_fymo_app_invalid_logging_config_fails_at_startup
in tests/core/test_logging.py for the sibling pattern this mirrors."""
from pathlib import Path

import pytest

from fymo.remote.mode import RemoteModeConfigError


def test_fymo_app_invalid_remote_mode_fails_at_startup(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text(
        "name: RemoteModeTest\nremote:\n  mode: bogus\n"
    )
    from fymo.core.server import FymoApp
    with pytest.raises(RemoteModeConfigError, match="bogus"):
        FymoApp(tmp_path, dev=True)


def test_fymo_app_mode_conflicting_with_deprecated_key_fails_at_startup(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text(
        "name: RemoteModeTest\nremote:\n  mode: strict\n  explicit_optin: true\n"
    )
    from fymo.core.server import FymoApp
    with pytest.raises(RemoteModeConfigError, match="explicit_optin"):
        FymoApp(tmp_path, dev=True)
