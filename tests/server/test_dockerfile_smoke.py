"""Lint-level smoke test for the production Dockerfile.

This does not build the image (no Docker daemon assumed in CI); it asserts
the Dockerfile is internally coherent and reflects fymo's real build/run
shape:

  - a node-based build stage that runs `fymo build` (compiles Svelte via
    esbuild into dist/, including dist/sidecar.mjs)
  - a runtime stage where `node` is available, because each gunicorn worker
    spawns its own Node sidecar process for SSR at request time
  - FYMO_SECRET referenced (production refuses to boot without it)
  - EXPOSE for the served port
  - a CMD/ENTRYPOINT invoking `fymo serve --prod`

It also checks docs/deployment.md exists and documents FYMO_SECRET
provisioning, since that's the other place operators look for this.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
DEPLOYMENT_DOCS = REPO_ROOT / "docs" / "deployment.md"


def _dockerfile_text() -> str:
    assert DOCKERFILE.is_file(), "Dockerfile is missing at repo root"
    return DOCKERFILE.read_text()


def test_dockerfile_exists():
    assert DOCKERFILE.is_file()


def test_dockerfile_has_node_build_stage_running_fymo_build():
    text = _dockerfile_text()
    assert "FROM node" in text, "expected a node-based build stage"
    assert "fymo build" in text, "build stage must run `fymo build`"


def test_dockerfile_runtime_stage_has_node_for_sidecar():
    text = _dockerfile_text()
    # The runtime stage must have Node available: each gunicorn worker
    # spawns `node dist/sidecar.mjs` for SSR. A python-only runtime image
    # would break SSR at request time.
    assert "node" in text.lower()
    lowered = text.lower()
    assert "sidecar" in lowered or "node dist/sidecar" in lowered or "nodejs" in lowered, (
        "Dockerfile should reflect that the runtime needs node for the "
        "per-worker SSR sidecar, not just the build stage"
    )


def test_dockerfile_runtime_keeps_node_modules_for_sidecar():
    # Regression test: dist/sidecar.mjs is NOT esbuild-bundled — it contains
    # a bare `import { render } from 'svelte/server'` that Node resolves
    # from node_modules at runtime. A runtime stage that deletes
    # node_modules boots fine and passes container liveness, but crashes
    # the sidecar with ERR_MODULE_NOT_FOUND on the first SSR render,
    # leaving /healthz permanently 503. node_modules must survive into the
    # runtime image; do not prune it (not even via `npm prune
    # --production`, since svelte/devalue may be devDependencies).
    text = _dockerfile_text()
    # Only look at actual instructions, not comment lines explaining what
    # NOT to do — a comment mentioning "npm prune" as a warning shouldn't
    # trip this check the way a real `RUN npm prune ...` instruction would.
    instruction_lines = "\n".join(
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    ).lower()
    forbidden_patterns = (
        "rm -rf ./node_modules",
        "rm -rf node_modules",
        "rm -rf /app/node_modules",
        "npm prune",
    )
    for pattern in forbidden_patterns:
        assert pattern not in instruction_lines, (
            f"Dockerfile must not delete/prune node_modules in the runtime "
            f"stage (found {pattern!r}) — the SSR sidecar resolves svelte/"
            f"devalue from node_modules at runtime, not from a bundled file"
        )


def test_dockerfile_runtime_stage_has_python():
    text = _dockerfile_text()
    # Split at the runtime stage marker so this only checks stage 2, not the
    # build stage (which also needs Python for the `fymo build` CLI).
    assert "AS runtime" in text, "expected a named runtime stage"
    runtime_stage = text.split("AS runtime", 1)[1]
    assert "python3" in runtime_stage.lower(), (
        "runtime stage must install python3 — fymo serve runs under a "
        "Python venv (gunicorn), not just Node"
    )


def test_dockerfile_references_fymo_secret():
    text = _dockerfile_text()
    assert "FYMO_SECRET" in text


def test_dockerfile_has_expose():
    text = _dockerfile_text()
    assert "EXPOSE" in text


def test_dockerfile_cmd_invokes_fymo_serve_prod():
    text = _dockerfile_text()
    assert "fymo serve" in text
    assert "--prod" in text
    assert ("CMD" in text) or ("ENTRYPOINT" in text)


def test_dockerignore_exists_and_excludes_junk():
    assert DOCKERIGNORE.is_file()
    text = DOCKERIGNORE.read_text()
    for entry in ("node_modules", ".git", "__pycache__", ".venv"):
        assert entry in text, f"expected .dockerignore to exclude {entry}"


def test_deployment_docs_exist_and_cover_secret_provisioning():
    assert DEPLOYMENT_DOCS.is_file()
    text = DEPLOYMENT_DOCS.read_text()
    assert "FYMO_SECRET" in text
    assert "/healthz" in text
    assert "trust_proxy" in text or "X-Forwarded-Proto" in text
