"""`media:` always resolves the files it serves through a StorageProvider
(fymo.storage.registry), and storage has no default provider on purpose --
see fymo/storage/registry.py's docstring. `check_storage_required_for_media`
catches the resulting footgun (media: configured, storage: forgotten) at
build time, before it ever reaches a runtime StorageConfigError."""
from pathlib import Path

from fymo.build.hygiene import check_storage_required_for_media


def _write_fymo_yml(project_root: Path, body: str) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "fymo.yml").write_text(body)


def test_media_without_storage_is_a_violation(tmp_path: Path):
    _write_fymo_yml(tmp_path, (
        "media:\n"
        "  - prefix: /media/videos/\n"
        "    dir: data/videos\n"
        "    extensions: [webm]\n"
    ))
    violations = check_storage_required_for_media(tmp_path)
    assert len(violations) == 1
    assert "storage:" in violations[0]


def test_media_with_storage_has_no_violations(tmp_path: Path):
    _write_fymo_yml(tmp_path, (
        "media:\n"
        "  - prefix: /media/videos/\n"
        "    dir: data/videos\n"
        "    extensions: [webm]\n"
        "storage:\n"
        "  provider: local\n"
    ))
    assert check_storage_required_for_media(tmp_path) == []


def test_no_media_no_storage_has_no_violations(tmp_path: Path):
    """No `media:` section at all means storage is never required, which
    covers the vast majority of apps, pre-existing and new alike."""
    _write_fymo_yml(tmp_path, "name: some_app\n")
    assert check_storage_required_for_media(tmp_path) == []


def test_missing_fymo_yml_has_no_violations(tmp_path: Path):
    assert check_storage_required_for_media(tmp_path) == []


def test_empty_media_list_has_no_violations(tmp_path: Path):
    """`media: []` is functionally identical to no `media:` section at
    all, zero routes get registered either way, so storage is not
    required."""
    _write_fymo_yml(tmp_path, "media: []\n")
    assert check_storage_required_for_media(tmp_path) == []
