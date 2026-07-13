"""Directory-hygiene validation: app/controllers/ is Python-only,
app/templates/ and app/components/ are frontend-only. A misplaced file
doesn't mechanically break anything (Python never imports a stray .svelte,
esbuild never bundles a stray .py) -- which is exactly why it needs an
explicit check instead of relying on something erroring on its own."""
from pathlib import Path

from fymo.build.hygiene import check_directory_hygiene, format_hygiene_error


def test_clean_project_has_no_violations(tmp_path: Path):
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "home.py").write_text("def getContext(): return {}\n")
    (tmp_path / "app" / "templates" / "home").mkdir(parents=True)
    (tmp_path / "app" / "templates" / "home" / "index.svelte").write_text("<div></div>")
    (tmp_path / "app" / "components").mkdir(parents=True)
    (tmp_path / "app" / "components" / "Nav.svelte").write_text("<nav></nav>")

    assert check_directory_hygiene(tmp_path) == []


def test_missing_directories_do_not_error(tmp_path: Path):
    """A fresh/minimal project without app/components/ (or even
    app/controllers/) at all must not be treated as a violation -- only
    files that ARE present and misplaced count."""
    assert check_directory_hygiene(tmp_path) == []


def test_svelte_file_in_controllers_is_a_violation(tmp_path: Path):
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "oops.svelte").write_text("<div></div>")

    violations = check_directory_hygiene(tmp_path)
    assert len(violations) == 1
    assert "app/controllers/oops.svelte" in violations[0]
    assert ".svelte" in violations[0]


def test_svelte_file_nested_in_controllers_subdir_is_caught(tmp_path: Path):
    """Controllers can be nested (e.g. layout controllers under a resource
    subdirectory) -- the check must be recursive, not top-level only."""
    (tmp_path / "app" / "controllers" / "posts").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "posts" / "oops.svelte").write_text("<div></div>")

    violations = check_directory_hygiene(tmp_path)
    assert len(violations) == 1
    assert "app/controllers/posts/oops.svelte" in violations[0]


def test_py_file_in_templates_is_a_violation(tmp_path: Path):
    (tmp_path / "app" / "templates" / "home").mkdir(parents=True)
    (tmp_path / "app" / "templates" / "home" / "oops.py").write_text("x = 1\n")

    violations = check_directory_hygiene(tmp_path)
    assert len(violations) == 1
    assert "app/templates/home/oops.py" in violations[0]
    assert ".py" in violations[0]


def test_py_file_in_components_is_a_violation(tmp_path: Path):
    (tmp_path / "app" / "components").mkdir(parents=True)
    (tmp_path / "app" / "components" / "oops.py").write_text("x = 1\n")

    violations = check_directory_hygiene(tmp_path)
    assert len(violations) == 1
    assert "app/components/oops.py" in violations[0]


def test_multiple_violations_all_reported_at_once(tmp_path: Path):
    """Don't stop at the first violation -- report everything in one pass
    so a developer doesn't have to re-run the build once per misplaced file."""
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    (tmp_path / "app" / "templates").mkdir(parents=True)
    (tmp_path / "app" / "templates" / "oops.py").write_text("x = 1\n")
    (tmp_path / "app" / "components").mkdir(parents=True)
    (tmp_path / "app" / "components" / "oops2.py").write_text("x = 1\n")

    violations = check_directory_hygiene(tmp_path)
    assert len(violations) == 3


def test_format_hygiene_error_lists_every_violation():
    msg = format_hygiene_error(["app/controllers/oops.svelte: bad", "app/templates/oops.py: bad"])
    assert "app/controllers/oops.svelte: bad" in msg
    assert "app/templates/oops.py: bad" in msg
    assert "Python-only" in msg
    assert "frontend-only" in msg
