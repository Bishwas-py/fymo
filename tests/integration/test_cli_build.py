import os
import subprocess
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_fymo_build_with_flag_uses_new_pipeline(example_app: Path):
    env = {**os.environ, "FYMO_NEW_PIPELINE": "1"}
    proc = subprocess.run(
        ["fymo", "build"],
        cwd=example_app,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (example_app / "dist" / "manifest.json").is_file()
    assert (example_app / "dist" / "sidecar.mjs").is_file()


