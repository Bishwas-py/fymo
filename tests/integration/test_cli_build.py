import subprocess
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_fymo_build_produces_dist(example_app: Path):
    proc = subprocess.run(
        ["fymo", "build"],
        cwd=example_app,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (example_app / "dist" / "manifest.json").is_file()
    assert (example_app / "dist" / "sidecar.mjs").is_file()


