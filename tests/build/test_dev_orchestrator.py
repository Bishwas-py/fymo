"""DevOrchestrator.start() must apply the same directory-hygiene check as
BuildPipeline.build() -- `fymo dev` reads the live source tree just like
`fymo build` does, so a misplaced file should be caught there too."""
from pathlib import Path

import pytest

from fymo.build.dev_orchestrator import DevOrchestrator


def test_start_fails_on_svelte_file_in_controllers(example_app: Path):
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    with pytest.raises(RuntimeError, match="app/controllers/oops.svelte"):
        DevOrchestrator(example_app).start()


def test_start_fails_on_py_file_in_components(example_app: Path):
    (example_app / "app" / "components").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "components" / "oops.py").write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="app/components/oops.py"):
        DevOrchestrator(example_app).start()


def test_hygiene_check_runs_even_without_node_on_path(example_app: Path, monkeypatch):
    """Same ordering rationale as the BuildPipeline test: a pure filesystem
    check shouldn't be masked by (or wait on) the node-availability check."""
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    monkeypatch.setattr("fymo.build.dev_orchestrator.shutil.which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="app/controllers/oops.svelte"):
        DevOrchestrator(example_app).start()
