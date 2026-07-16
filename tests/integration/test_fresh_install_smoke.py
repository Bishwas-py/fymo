"""End-to-end smoke test for issues #55 and #60 together.

Neither issue is visible from inside this monorepo's own editable checkout:
the repo root's own node_modules and fymo/'s own source tree both happen to
sit as directory ancestors of everything else, which is exactly what masks
both bugs in every other test in this suite. tests/integration/test_cli_build.py
already runs `fymo build` against a real project and passes today, even
though #60 was very much still open against a real `pip install` -- proof
that testing from inside the monorepo alone can't catch this class of bug.

This test instead builds a real wheel, pip installs it into a clean scratch
venv, and drives the actual documented quick start through that venv's own
`fymo` entrypoint:

    pip install fymo
    fymo new my_app
    cd my_app && npm install
    fymo build

The `npm install` step is stood in for by symlinking in
examples/blog_app's own already-installed, known-good node_modules (the same
convention tests/conftest.py's blog_app/example_app fixtures already use)
rather than a real network install, so this test stays fast and
network-independent; the scaffold's package.json contents (issue #55) are
covered by tests/cli/test_new.py's own assertions on the generated file, and
a real `npm install` against the scaffolded package.json was verified by
hand while fixing #55 -- 50 packages installed cleanly, all four missing
devDependencies now present.

Everything (built wheel, scratch venv, scaffolded project, dist output) is
created under tmp_path and explicitly removed at the end of the test, not
left for pytest's own tmp_path retention to eventually prune.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import BLOG_APP, REPO_ROOT


@pytest.mark.usefixtures("node_available")
def test_fresh_pip_install_new_and_build_end_to_end(tmp_path):
    nm = BLOG_APP / "node_modules"
    if not nm.is_dir():
        pytest.skip("examples/blog_app/node_modules not found — run npm install in examples/blog_app/")
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH — needed to build the wheel and create the scratch venv")

    dist_dir = tmp_path / "wheel_dist"
    venv_dir = tmp_path / "venv"
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    try:
        build_proc = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert build_proc.returncode == 0, f"uv build failed\nstdout: {build_proc.stdout}\nstderr: {build_proc.stderr}"
        wheels = list(dist_dir.glob("*.whl"))
        assert len(wheels) == 1, f"expected exactly one wheel, found: {wheels}"
        wheel = wheels[0]

        venv_proc = subprocess.run(
            ["uv", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
        )
        assert venv_proc.returncode == 0, f"uv venv failed\nstdout: {venv_proc.stdout}\nstderr: {venv_proc.stderr}"
        venv_python = venv_dir / "bin" / "python"
        venv_fymo = venv_dir / "bin" / "fymo"

        install_proc = subprocess.run(
            ["uv", "pip", "install", "--python", str(venv_python), str(wheel)],
            capture_output=True,
            text=True,
        )
        assert install_proc.returncode == 0, f"pip install failed\nstdout: {install_proc.stdout}\nstderr: {install_proc.stderr}"
        assert venv_fymo.is_file(), "fymo entrypoint not installed into the scratch venv"

        new_proc = subprocess.run(
            [str(venv_fymo), "new", "my_app"],
            cwd=work_dir,
            capture_output=True,
            text=True,
        )
        assert new_proc.returncode == 0, f"fymo new failed\nstdout: {new_proc.stdout}\nstderr: {new_proc.stderr}"
        project = work_dir / "my_app"
        assert (project / "package.json").is_file()

        package_json = json.loads((project / "package.json").read_text())
        dev_deps = package_json["devDependencies"]
        assert "esbuild-svelte" in dev_deps
        assert "svelte-preprocess" in dev_deps
        assert "typescript" in dev_deps
        assert "devalue" in package_json["dependencies"]

        (project / "node_modules").symlink_to(nm)

        build_run_proc = subprocess.run(
            [str(venv_fymo), "build"],
            cwd=project,
            capture_output=True,
            text=True,
        )
        assert "Cannot find package 'esbuild'" not in build_run_proc.stdout + build_run_proc.stderr
        assert build_run_proc.returncode == 0, (
            f"fymo build failed against a real pip install\n"
            f"stdout: {build_run_proc.stdout}\nstderr: {build_run_proc.stderr}"
        )
        assert (project / "dist" / "manifest.json").is_file()
        assert (project / "dist" / "sidecar.mjs").is_file()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
