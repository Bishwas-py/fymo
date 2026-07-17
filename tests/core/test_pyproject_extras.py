"""The auth provider extras died with the framework-owned auth model
(issue #80 phase 6): external providers are separate packages you call
from app/auth/ code, never fymo extras, so `clerk`/`oidc`/`oauth` must
not exist and pyjwt must appear nowhere in pyproject.toml. The jobs
extras (procrastinate/postgres) stay: psycopg is still a real optional
dependency of the job queue.
"""
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repo requires-python >=3.11
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_auth_provider_extras_are_gone():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    for name in ("clerk", "oidc", "oauth"):
        assert name not in extras, f"fymo[{name}] extra must not exist anymore"


def test_jobs_extras_survive():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    assert "procrastinate" in extras
    assert "postgres" in extras
    assert any("psycopg" in dep for dep in extras["procrastinate"])


def test_pyjwt_appears_nowhere_in_pyproject():
    data = _load_pyproject()
    everything = []
    everything.extend(data["project"]["dependencies"])
    for deps in data["project"].get("optional-dependencies", {}).values():
        everything.extend(deps)
    for deps in data.get("dependency-groups", {}).values():
        everything.extend(str(d) for d in deps)
    joined = " ".join(everything).lower()
    assert "pyjwt" not in joined
    assert "cryptography" not in joined
