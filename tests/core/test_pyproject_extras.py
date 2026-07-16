"""Named extras exist in pyproject.toml (issue #59): Clerk/OIDC/OAuth are
opt-in installs, never pulled in by a bare `pip install fymo`. Reads the
real pyproject.toml at the repo root rather than re-deriving the expected
values, so a future edit to the extras themselves doesn't have to also
touch this test to stay honest about intent -- it only pins the shape:
the three names must exist, and clerk must actually carry pyjwt.
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


def test_clerk_oidc_oauth_extras_are_all_defined():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    for name in ("clerk", "oidc", "oauth"):
        assert name in extras, f"fymo[{name}] extra is missing from pyproject.toml"


def test_clerk_extra_pulls_in_pyjwt_with_crypto():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    clerk_deps = " ".join(extras["clerk"])
    assert "pyjwt" in clerk_deps.lower()
    assert "crypto" in clerk_deps.lower()


def test_base_dependencies_never_mention_pyjwt_or_cryptography():
    """The core `dependencies` list (unlike optional-dependencies) is what a
    bare `pip install fymo` actually pulls in -- pyjwt/cryptography must
    never leak in there, or fymo[clerk] stops meaning anything."""
    deps = " ".join(_load_pyproject()["project"]["dependencies"]).lower()
    assert "pyjwt" not in deps
    assert "cryptography" not in deps
