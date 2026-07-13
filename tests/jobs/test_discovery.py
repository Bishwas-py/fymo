"""Tests for app/jobs/*.py task discovery."""
from pathlib import Path

from fymo.jobs.discovery import discover_job_tasks


def test_returns_empty_dict_when_no_jobs_dir(tmp_path: Path):
    assert discover_job_tasks(tmp_path) == {}


def test_discovers_top_level_functions(tmp_path: Path):
    jobs_dir = tmp_path / "app" / "jobs"
    jobs_dir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (jobs_dir / "__init__.py").write_text("")
    (jobs_dir / "runs.py").write_text(
        "def do_record_work(flow_id, run_id):\n    return flow_id, run_id\n"
        "def _private_helper():\n    pass\n"
    )
    tasks = discover_job_tasks(tmp_path)
    assert set(tasks.keys()) == {"do_record_work"}
    assert tasks["do_record_work"]("f1", "r1") == ("f1", "r1")


def test_skips_private_modules(tmp_path: Path):
    jobs_dir = tmp_path / "app" / "jobs"
    jobs_dir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (jobs_dir / "__init__.py").write_text("")
    (jobs_dir / "_helpers.py").write_text("def helper():\n    pass\n")
    assert discover_job_tasks(tmp_path) == {}


def test_two_project_roots_dont_collide(tmp_path_factory):
    root_a = tmp_path_factory.mktemp("proj_a")
    (root_a / "app" / "jobs").mkdir(parents=True)
    (root_a / "app" / "__init__.py").write_text("")
    (root_a / "app" / "jobs" / "__init__.py").write_text("")
    (root_a / "app" / "jobs" / "work.py").write_text("def task_a():\n    return 'a'\n")

    root_b = tmp_path_factory.mktemp("proj_b")
    (root_b / "app" / "jobs").mkdir(parents=True)
    (root_b / "app" / "__init__.py").write_text("")
    (root_b / "app" / "jobs" / "__init__.py").write_text("")
    (root_b / "app" / "jobs" / "work.py").write_text("def task_b():\n    return 'b'\n")

    tasks_a = discover_job_tasks(root_a)
    tasks_b = discover_job_tasks(root_b)
    assert tasks_a["task_a"]() == "a"
    assert tasks_b["task_b"]() == "b"
    # Stale attributes must not survive across roots: importlib.reload
    # reuses the module __dict__, so a naive reload leaks root_a's task_a
    # into root_b's discovery.
    assert set(tasks_a) == {"task_a"}
    assert set(tasks_b) == {"task_b"}
