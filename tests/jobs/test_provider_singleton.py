"""Tests for the process-wide JobProvider singleton and its config-driven
init helper — mirrors fymo.jobs's existing get_shared_runner()/
set_shared_runner() tests (test_job_runner.py) for the JobRunner singleton."""
from pathlib import Path

import pytest

from fymo.jobs import (
    get_job_provider,
    init_job_provider,
    reset_job_provider,
    set_job_provider,
)
from fymo.jobs.providers.threaded import ThreadedJobProvider


@pytest.fixture(autouse=True)
def _reset():
    reset_job_provider()
    yield
    reset_job_provider()


def test_get_job_provider_defaults_to_threaded():
    provider = get_job_provider()
    assert isinstance(provider, ThreadedJobProvider)


def test_get_job_provider_is_a_process_wide_singleton_by_default():
    assert get_job_provider() is get_job_provider()


def test_set_job_provider_overrides_the_default():
    custom = ThreadedJobProvider()
    set_job_provider(custom)
    assert get_job_provider() is custom


def test_init_job_provider_discovers_and_registers_app_jobs(tmp_path: Path):
    jobs_dir = tmp_path / "app" / "jobs"
    jobs_dir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").touch()
    (jobs_dir / "__init__.py").touch()
    marker = tmp_path / "ran.marker"
    (jobs_dir / "example.py").write_text(
        f"from pathlib import Path\n"
        f"def do_thing(x: int) -> None:\n"
        f"    Path({str(marker)!r}).write_text(str(x))\n"
    )

    provider = init_job_provider(tmp_path, None)

    assert isinstance(provider, ThreadedJobProvider)
    assert get_job_provider() is provider

    provider.submit("do_thing", 42)
    import time
    content = ""
    for _ in range(500):
        # Poll for *content*, not existence: write_text creates the file
        # empty before writing, so an exists() check can win that race on a
        # slow runner and read "".
        if marker.exists():
            content = marker.read_text()
            if content:
                break
        time.sleep(0.01)
    assert content == "42"


def test_init_job_provider_with_no_app_jobs_dir_still_works(tmp_path: Path):
    provider = init_job_provider(tmp_path, None)
    assert isinstance(provider, ThreadedJobProvider)
    with pytest.raises(ValueError, match="unknown job task"):
        provider.submit("nope")
