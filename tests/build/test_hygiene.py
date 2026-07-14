"""Directory-hygiene validation: app/controllers/ is Python-only,
app/templates/ and app/components/ are frontend-only. A misplaced file
doesn't mechanically break anything (Python never imports a stray .svelte,
esbuild never bundles a stray .py) -- which is exactly why it needs an
explicit check instead of relying on something erroring on its own."""
from pathlib import Path

from fymo.build.hygiene import (
    check_directory_hygiene,
    check_lib_directory_warnings,
    format_hygiene_error,
)


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


# check_lib_directory_warnings (soft, not a build error)


def test_no_app_lib_dir_produces_no_warnings(tmp_path: Path):
    assert check_lib_directory_warnings(tmp_path) == []


def test_app_lib_with_only_ts_files_produces_no_warnings(tmp_path: Path):
    (tmp_path / "app" / "lib").mkdir(parents=True)
    (tmp_path / "app" / "lib" / "auth.ts").write_text("export const x = 1;\n")

    assert check_lib_directory_warnings(tmp_path) == []


def test_py_file_in_app_lib_produces_a_warning(tmp_path: Path):
    (tmp_path / "app" / "lib").mkdir(parents=True)
    (tmp_path / "app" / "lib" / "oops.py").write_text("x = 1\n")

    warnings = check_lib_directory_warnings(tmp_path)
    assert len(warnings) == 1
    assert "app/lib/oops.py" in warnings[0]
    assert "app/support" in warnings[0]


def test_py_file_nested_in_app_lib_subdir_is_caught(tmp_path: Path):
    (tmp_path / "app" / "lib" / "nested").mkdir(parents=True)
    (tmp_path / "app" / "lib" / "nested" / "oops.py").write_text("x = 1\n")

    warnings = check_lib_directory_warnings(tmp_path)
    assert len(warnings) == 1
    assert "app/lib/nested/oops.py" in warnings[0]


def test_multiple_py_files_in_app_lib_all_reported(tmp_path: Path):
    (tmp_path / "app" / "lib").mkdir(parents=True)
    (tmp_path / "app" / "lib" / "a.py").write_text("x = 1\n")
    (tmp_path / "app" / "lib" / "b.py").write_text("x = 1\n")

    assert len(check_lib_directory_warnings(tmp_path)) == 2


def test_check_lib_directory_warnings_does_not_affect_hard_errors(tmp_path: Path):
    """The warning check and the existing hard-error check are independent:
    a .py file in app/lib/ must not show up in check_directory_hygiene()'s
    result, and a hard-error violation elsewhere must not show up in the
    warning check's result."""
    (tmp_path / "app" / "lib").mkdir(parents=True)
    (tmp_path / "app" / "lib" / "oops.py").write_text("x = 1\n")
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "oops.svelte").write_text("<div></div>")

    hard_violations = check_directory_hygiene(tmp_path)
    assert len(hard_violations) == 1
    assert "app/controllers/oops.svelte" in hard_violations[0]

    soft_warnings = check_lib_directory_warnings(tmp_path)
    assert len(soft_warnings) == 1
    assert "app/lib/oops.py" in soft_warnings[0]
