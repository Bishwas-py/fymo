"""`fymo new` output is pinned byte-for-byte (issue #89 phase 3).

The scaffold moved from inline string literals in new.py onto template
files rendered through fymo.cli.render. The move must not change a
single output byte: this fixture was captured from the inline-literal
implementation (sha256 per file, plus the full directory set including
empty dirs, plus file modes so server.py stays executable). If a test
here fails after a deliberate scaffold change, regenerate the fixture
and say so in the commit; if it fails during a refactor, the refactor
altered output and is wrong.
"""
import hashlib
import json
from pathlib import Path

import pytest

from fymo.cli.commands.new import create_project

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "new_scaffold_baseline.json").read_text()
)


def _snapshot(root: Path):
    files = {}
    dirs = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            dirs.append(rel)
        else:
            files[rel] = {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "mode": oct(p.stat().st_mode & 0o777),
            }
    return files, sorted(dirs)


@pytest.mark.parametrize("label", ["auth", "no_auth"])
def test_scaffold_is_byte_identical_to_baseline(label, tmp_path, monkeypatch):
    expected = FIXTURE[label]
    monkeypatch.chdir(tmp_path)
    create_project(expected["project_name"], auth=(label == "auth"))
    files, dirs = _snapshot(tmp_path / expected["project_name"])

    assert sorted(files) == sorted(expected["files"]), "scaffold file set changed"
    assert dirs == expected["dirs"], "scaffold directory set changed"
    for rel, meta in expected["files"].items():
        assert files[rel]["sha256"] == meta["sha256"], f"content changed: {rel}"
        assert files[rel]["mode"] == meta["mode"], f"mode changed: {rel}"
