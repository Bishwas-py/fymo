import json
import time
from pathlib import Path
import pytest
from fymo.build.dev_orchestrator import DevOrchestrator
from fymo.core.sidecar import Sidecar


def _wait_for_manifest(app: Path, seconds: float = 20) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if (app / "dist" / "manifest.json").exists():
            return
        time.sleep(0.1)
    pytest.fail("manifest never written")


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
def test_dev_built_ssr_renders_with_project_svelte(example_app: Path):
    """Regression: `fymo dev` must compile Svelte with the *project's*
    toolchain, not fymo's own node_modules.

    When the project pins a different Svelte than fymo does, compiling with
    fymo's Svelte emits lifecycle calls (push/pop) that the project's Svelte
    runtime — which esbuild bundles for SSR — no longer exports at that path.
    The bundle then calls `(void 0)()` and every render throws
    `(void 0) is not a function`. Drive the real sidecar to prove the
    dev-built SSR actually renders.
    """
    orch = DevOrchestrator(project_root=example_app)
    orch.start()
    try:
        _wait_for_manifest(example_app)
        dist = example_app / "dist"
        assert (dist / "ssr" / "todos.mjs").is_file()

        sidecar = Sidecar(dist)
        sidecar.start()
        try:
            out = sidecar.render(
                "todos",
                {"leafProps": {}, "layoutProps": {"root": {}, "resource": {}}},
            )
        finally:
            sidecar.stop()
        assert out["body"].strip(), "SSR body should be non-empty"
    finally:
        orch.stop()


@pytest.mark.usefixtures("node_available")
def test_dev_manifest_includes_remote_modules(blog_app: Path):
    """Regression: `fymo dev`'s manifest must include remote_modules, same
    as `fymo build`'s.

    DevOrchestrator never discovered app/remote/*.py (or auth providers')
    remote functions at all, so every manifest `fymo dev` wrote omitted
    remote_modules entirely — even overwriting a good manifest a prior
    `fymo build` had produced. Any SSR prop referencing a remote function
    (e.g. a controller passing a remote callable to a template, as
    app/controllers/signin.py does with login/signup) then
    crashed with "remote module '...' has no hash in manifest" — and
    `fymo serve` afterward inherited the same broken manifest file, since
    serve only reads whatever's on disk rather than rebuilding it.
    """
    orch = DevOrchestrator(project_root=blog_app)
    orch.start()
    try:
        _wait_for_manifest(blog_app)
        manifest = json.loads((blog_app / "dist" / "manifest.json").read_text())
        remote_modules = manifest.get("remote_modules", {})

        assert "posts" in remote_modules, f"expected 'posts' in remote_modules, got {list(remote_modules)}"
        assert remote_modules["posts"]["hash"]
        assert "create_post" in remote_modules["posts"]["fns"]
        assert "list_posts" in remote_modules["posts"]["fns"]

        # auth is enabled in blog_app's fymo.yml -> the password provider's
        # remote functions (signup/login/logout/me) must also be discovered,
        # exactly like BuildPipeline already does.
        assert "auth" in remote_modules, f"expected 'auth' in remote_modules, got {list(remote_modules)}"
        assert "login" in remote_modules["auth"]["fns"]

        # And the client-side stub files those hashes point at must actually
        # exist, or the client bundle can't resolve $remote/posts either.
        assert (blog_app / "dist" / "client" / "_remote" / "posts.js").is_file()
        assert (blog_app / "dist" / "client" / "_remote" / "auth.js").is_file()
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
