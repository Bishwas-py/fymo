"""`@task` marker for app/jobs/*.py functions.

Backward compat is required: an undecorated top-level function must keep
being discovered and registered exactly as before, this is NOT a breaking
change. The only behavior difference is a one-line deprecation-style log
warning for undecorated functions, suggesting `@task` be added.
"""
import logging
from pathlib import Path

from fymo.jobs import task
from fymo.jobs.discovery import discover_job_tasks


def _scaffold(tmp_path: Path, module_source: str) -> Path:
    jobs_dir = tmp_path / "app" / "jobs"
    jobs_dir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (jobs_dir / "__init__.py").write_text("")
    (jobs_dir / "runs.py").write_text(module_source)
    return tmp_path


def test_task_decorator_marks_function_and_returns_it_unchanged():
    def fn(x: int) -> int:
        return x

    marked = task(fn)

    assert marked is fn
    assert marked.__fymo_task__ is True


def test_task_decorated_function_is_discovered_and_registered(tmp_path: Path):
    project = _scaffold(
        tmp_path,
        "from fymo.jobs import task\n"
        "@task\n"
        "def do_work(x):\n    return x * 2\n",
    )
    tasks = discover_job_tasks(project)
    assert set(tasks.keys()) == {"do_work"}
    assert tasks["do_work"](21) == 42


def test_undecorated_function_is_still_discovered_and_registered(tmp_path: Path):
    """Backward compat: a bare top-level function must keep working exactly
    as it did before @task existed."""
    project = _scaffold(tmp_path, "def do_work(x):\n    return x * 2\n")
    tasks = discover_job_tasks(project)
    assert set(tasks.keys()) == {"do_work"}
    assert tasks["do_work"](21) == 42


def test_undecorated_function_logs_a_deprecation_warning(tmp_path: Path, caplog):
    project = _scaffold(tmp_path, "def do_work(x):\n    return x * 2\n")
    with caplog.at_level(logging.WARNING, logger="fymo.jobs"):
        discover_job_tasks(project)
    messages = [r.getMessage() for r in caplog.records]
    assert any("do_work" in m and "@task" in m for m in messages)


def test_task_decorated_function_does_not_log_a_warning(tmp_path: Path, caplog):
    project = _scaffold(
        tmp_path,
        "from fymo.jobs import task\n"
        "@task\n"
        "def do_work(x):\n    return x * 2\n",
    )
    with caplog.at_level(logging.WARNING, logger="fymo.jobs"):
        discover_job_tasks(project)
    assert caplog.records == []


def test_mixed_module_only_warns_for_the_undecorated_function(tmp_path: Path, caplog):
    project = _scaffold(
        tmp_path,
        "from fymo.jobs import task\n"
        "@task\n"
        "def marked(x):\n    return x\n"
        "def unmarked(x):\n    return x\n",
    )
    with caplog.at_level(logging.WARNING, logger="fymo.jobs"):
        tasks = discover_job_tasks(project)
    assert set(tasks.keys()) == {"marked", "unmarked"}
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    assert "unmarked" in messages[0]
