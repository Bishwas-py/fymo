"""ProcrastinateJobProvider tests that need neither Postgres nor the
procrastinate package — misconfiguration must fail with clear, actionable
errors, not raw tracebacks (unlike test_procrastinate.py, which is gated
on TEST_DATABASE_URL)."""
import sys

import pytest

from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider


def test_id_is_procrastinate():
    assert ProcrastinateJobProvider().id == "procrastinate"


def test_submit_with_missing_database_url_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    provider = ProcrastinateJobProvider()
    provider.register_tasks({"x": lambda: None})
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        provider.submit("x")


def test_run_worker_with_missing_database_url_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    provider = ProcrastinateJobProvider()
    provider.register_tasks({})
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        provider.run_worker()


def test_missing_procrastinate_package_raises_an_install_hint(monkeypatch):
    """`jobs: provider: procrastinate` without `pip install
    fymo[procrastinate]` must say exactly that — not ModuleNotFoundError.
    Setting sys.modules['procrastinate'] to None makes `import
    procrastinate` fail even when the package is installed."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    monkeypatch.setitem(sys.modules, "procrastinate", None)
    provider = ProcrastinateJobProvider()
    provider.register_tasks({"x": lambda: None})

    with pytest.raises(RuntimeError, match=r"fymo\[procrastinate\]"):
        provider.submit("x")
    with pytest.raises(RuntimeError, match=r"fymo\[procrastinate\]"):
        provider.run_worker()
