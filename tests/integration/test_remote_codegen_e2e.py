"""End-to-end: BuildPipeline must produce .js + .d.ts under dist/client/_remote/."""
import shutil
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_build_emits_remote_artifacts(example_app: Path):
    # Add a minimal remote module to the example app
    remote_dir = example_app / "app" / "remote"
    remote_dir.mkdir(parents=True, exist_ok=True)
    (remote_dir / "__init__.py").write_text("")
    (remote_dir / "test_mod.py").write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'\n"
    )

    BuildPipeline(project_root=example_app).build(dev=False)

    out = example_app / "dist" / "client" / "_remote"
    assert (out / "__runtime.js").is_file()
    assert (out / "test_mod.js").is_file()
    assert (out / "test_mod.d.ts").is_file()

    js = (out / "test_mod.js").read_text()
    assert "export const hello" in js
    assert "test_mod/hello" in js
