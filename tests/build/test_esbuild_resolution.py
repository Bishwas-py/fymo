"""Issue #60: fymo/build/js/build.mjs and dev.mjs must resolve `esbuild` from
the *target project's* own node_modules, not from wherever the .mjs file
itself happens to live.

A bare `import { build } from 'esbuild'` is resolved by Node against the
importing file's own directory ancestry, never the project being built or
process.cwd(). Inside this monorepo that's invisible, because the repo root's
own node_modules sits as an ancestor of fymo/build/js/ too. Once fymo is a
real `pip install` (site-packages/fymo/build/js/), that ancestry never
reaches any node_modules at all.

These tests reproduce that by copying build.mjs (and its plugin/runtime
dependencies) to a scratch directory with no node_modules anywhere in its
own ancestry (pytest's tmp_path already guarantees this), simulating a real
install location, then pointing it at a project whose *only* copy of esbuild
lives in the project's own node_modules. A bare import can never find it from
there; the createRequire(project package.json)-based resolution can.
"""
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.conftest import BLOG_APP, REPO_ROOT

BUILD_JS_SRC = REPO_ROOT / "fymo" / "build" / "js"


def _install_build_js_outside_repo(tmp_path: Path) -> Path:
    """Copy fymo/build/js/ to a location with no node_modules ancestor,
    standing in for a real site-packages/fymo/build/js/ install."""
    dest = tmp_path / "installed_fymo_pkg" / "js"
    shutil.copytree(BUILD_JS_SRC, dest)
    return dest


def _make_project_with_only_its_own_esbuild(tmp_path: Path) -> Path:
    """A project directory whose node_modules is the only place `esbuild`
    (or esbuild-svelte/svelte-preprocess) can be found. Reuses
    examples/blog_app's already-installed, known-good node_modules rather
    than a real `npm install`, matching the existing blog_app/example_app
    fixture convention in tests/conftest.py."""
    nm = BLOG_APP / "node_modules"
    if not nm.is_dir():
        pytest.skip("examples/blog_app/node_modules not found — run npm install in examples/blog_app/")
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text(json.dumps({"name": "scratch-project", "type": "module"}))
    (project / "node_modules").symlink_to(nm)
    return project


def _run_build_script(script_path: Path, project_root: Path, dist_dir: Path) -> subprocess.CompletedProcess:
    config = {
        "projectRoot": str(project_root),
        "distDir": str(dist_dir),
        "routes": [],
        "clientEntries": {},
        "dev": False,
    }
    return subprocess.run(
        ["node", str(script_path), json.dumps(config)],
        cwd=project_root,
        capture_output=True,
        text=True,
    )


@pytest.mark.usefixtures("node_available")
def test_build_mjs_resolves_esbuild_from_project_not_from_its_own_install_location(tmp_path):
    installed_js = _install_build_js_outside_repo(tmp_path)
    project = _make_project_with_only_its_own_esbuild(tmp_path)
    dist_dir = tmp_path / "dist"

    proc = _run_build_script(installed_js / "build.mjs", project, dist_dir)

    assert "Cannot find package 'esbuild'" not in proc.stdout + proc.stderr
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    result = json.loads(proc.stdout)
    assert result["ok"] is True


@pytest.mark.usefixtures("node_available")
def test_build_mjs_bundles_route_runtimes_svelte_store_import_from_project(tmp_path):
    """A second, independently-discovered instance of the same root cause.

    fymo/build/js/runtime/route.js -- resolved by fymoRoutePlugin as the
    fixed target of every `$route` import -- has its own bare
    `import { writable } from 'svelte/store'`. It's not loaded by Node at
    all (createRequire can't help here); esbuild bundles it as ordinary
    source, and esbuild's own default module resolution walks up from
    route.js's own directory exactly the way Node's ESM resolver does. Once
    fymo is a real pip install, route.js's directory ancestry never reaches
    the target project's node_modules either, so any route that imports
    `$route` fails to build with "Could not resolve svelte/store", a
    completely real-world entry point (blog_app's route runtime uses
    `$route`), not a synthetic one.
    """
    installed_js = _install_build_js_outside_repo(tmp_path)
    project = _make_project_with_only_its_own_esbuild(tmp_path)
    dist_dir = tmp_path / "dist"

    entry = project / "uses_route.js"
    entry.write_text("import { route } from '$route';\nexport default route;\n")

    config = {
        "projectRoot": str(project),
        "distDir": str(dist_dir),
        "routes": [{"name": "home", "entryPath": str(entry)}],
        "clientEntries": {},
        "dev": False,
    }
    proc = subprocess.run(
        ["node", str(installed_js / "build.mjs"), json.dumps(config)],
        cwd=project,
        capture_output=True,
        text=True,
    )

    assert "Could not resolve" not in proc.stdout + proc.stderr
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    result = json.loads(proc.stdout)
    assert result["ok"] is True, result.get("error")


@pytest.mark.usefixtures("node_available")
def test_dev_mjs_resolves_esbuild_from_project_not_from_its_own_install_location(tmp_path):
    installed_js = _install_build_js_outside_repo(tmp_path)
    project = _make_project_with_only_its_own_esbuild(tmp_path)
    dist_dir = tmp_path / "dist"

    config = {
        "projectRoot": str(project),
        "distDir": str(dist_dir),
        "routes": [],
        "clientEntries": {},
        "dev": True,
    }
    proc = subprocess.Popen(
        ["node", str(installed_js / "dev.mjs"), json.dumps(config)],
        cwd=project,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # dev.mjs runs a persistent watcher and never exits on its own; a clean
    # "ready" event on stdout is proof the esbuild.context() calls it makes
    # at startup (which is where the bare import would have already thrown)
    # succeeded. If esbuild can't be resolved, the process crashes before
    # ever reaching this point and stdout hits EOF instead.
    saw_ready = False
    deadline = time.time() + 15
    try:
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            if '"type":"ready"' in line:
                saw_ready = True
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    stderr_output = proc.stderr.read()
    assert "Cannot find package 'esbuild'" not in stderr_output
    assert saw_ready, f"dev.mjs never emitted a ready event; stderr: {stderr_output}"
