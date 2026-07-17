"""Build-time checks for storage exposure. The retired top-level `media:`
key must fail the build with the migration text (check_media_key_removed),
and `storage.expose` with no provider selected must fail at build time too
(check_storage_required_for_expose): exposed entries resolve files through
the configured StorageProvider and storage has no default provider on
purpose, see fymo/storage/registry.py's docstring."""
from pathlib import Path

from fymo.build.hygiene import check_media_key_removed, check_storage_required_for_expose


def _write_fymo_yml(project_root: Path, body: str) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "fymo.yml").write_text(body)


def test_top_level_media_key_is_a_violation(tmp_path: Path):
    _write_fymo_yml(tmp_path, (
        "media:\n"
        "  - prefix: /media/videos/\n"
        "    dir: videos\n"
        "    extensions: [webm]\n"
    ))
    violations = check_media_key_removed(tmp_path)
    assert len(violations) == 1
    assert "storage.expose" in violations[0]
    assert "prefix/dir/extensions" in violations[0]


def test_empty_media_key_is_still_a_violation(tmp_path: Path):
    """`media: []` still carries the removed key; the build must name the
    new shape rather than silently ignoring it."""
    _write_fymo_yml(tmp_path, "media: []\n")
    assert len(check_media_key_removed(tmp_path)) == 1


def test_no_media_key_is_clean(tmp_path: Path):
    _write_fymo_yml(tmp_path, "name: some_app\n")
    assert check_media_key_removed(tmp_path) == []


def test_missing_fymo_yml_is_clean(tmp_path: Path):
    assert check_media_key_removed(tmp_path) == []
    assert check_storage_required_for_expose(tmp_path) == []


def test_expose_without_provider_is_a_violation(tmp_path: Path):
    _write_fymo_yml(tmp_path, (
        "storage:\n"
        "  expose:\n"
        "    - prefix: /media/videos/\n"
        "      dir: videos\n"
        "      extensions: [webm]\n"
    ))
    violations = check_storage_required_for_expose(tmp_path)
    assert len(violations) == 1
    assert "storage.provider" in violations[0]


def test_expose_with_provider_has_no_violations(tmp_path: Path):
    _write_fymo_yml(tmp_path, (
        "storage:\n"
        "  provider: local\n"
        "  expose:\n"
        "    - prefix: /media/videos/\n"
        "      dir: videos\n"
        "      extensions: [webm]\n"
    ))
    assert check_storage_required_for_expose(tmp_path) == []


def test_storage_without_expose_has_no_violations(tmp_path: Path):
    """storage: without expose entries is the write-only case (a job writing
    files, nothing served); provider validation for that path stays where it
    always was, in the registry at startup."""
    _write_fymo_yml(tmp_path, "storage:\n  provider: local\n")
    assert check_storage_required_for_expose(tmp_path) == []


def test_empty_expose_list_has_no_violations(tmp_path: Path):
    _write_fymo_yml(tmp_path, "storage:\n  expose: []\n")
    assert check_storage_required_for_expose(tmp_path) == []


def test_bare_string_storage_has_no_violations(tmp_path: Path):
    _write_fymo_yml(tmp_path, "storage: local\n")
    assert check_storage_required_for_expose(tmp_path) == []
