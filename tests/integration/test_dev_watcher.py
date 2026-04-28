import time
from pathlib import Path
import pytest
from fymo.build.dev_orchestrator import DevOrchestrator


@pytest.mark.usefixtures("node_available")
def test_orchestrator_writes_initial_manifest(example_app: Path):
    orch = DevOrchestrator(project_root=example_app)
    orch.start()
    try:
        # wait for first build to complete (max 15s)
        deadline = time.time() + 15
        while time.time() < deadline:
            if (example_app / "dist" / "manifest.json").exists():
                break
            time.sleep(0.1)
        else:
            pytest.fail("manifest never written")
    finally:
        orch.stop()


@pytest.mark.usefixtures("node_available")
def test_orchestrator_rebuilds_on_change(example_app: Path):
    orch = DevOrchestrator(project_root=example_app)
    orch.start()
    try:
        # wait for first build
        deadline = time.time() + 15
        while time.time() < deadline and not (example_app / "dist" / "manifest.json").exists():
            time.sleep(0.1)
        first_mtime = (example_app / "dist" / "manifest.json").stat().st_mtime

        # trigger rebuild
        target = example_app / "app" / "templates" / "todos" / "index.svelte"
        target.write_text(target.read_text() + "<!-- changed -->")

        deadline = time.time() + 10
        while time.time() < deadline:
            if (example_app / "dist" / "manifest.json").stat().st_mtime > first_mtime:
                return  # success
            time.sleep(0.1)
        pytest.fail("manifest mtime did not change after edit")
    finally:
        orch.stop()
