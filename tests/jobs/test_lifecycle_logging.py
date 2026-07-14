"""Per-job lifecycle logging: started/succeeded/failed with duration.

Job ARGUMENTS must never appear in log output (PII rule)."""
import json as jsonlib
import logging
import time
from pathlib import Path

import pytest

import fymo.core.logging as fymo_logging
from fymo.core.logging import configure
from fymo.jobs.lifecycle import run_with_lifecycle
from fymo.jobs.providers.threaded import ThreadedJobProvider
from fymo.jobs import reset_shared_runner


@pytest.fixture(autouse=True)
def _reset_logging_and_runner():
    yield
    reset_shared_runner()
    root = logging.getLogger()
    if fymo_logging._installed_handler is not None:
        root.removeHandler(fymo_logging._installed_handler)
        fymo_logging._installed_handler.close()
        fymo_logging._installed_handler = None
    root.setLevel(logging.WARNING)
    # run_worker() caps the "procrastinate" logger's level as a side effect
    # (see ProcrastinateJobProvider.run_worker) -- process-global state that
    # must not leak between tests in this file.
    logging.getLogger("procrastinate").setLevel(logging.NOTSET)


def _configure_file(tmp_path: Path, level: str = "debug") -> Path:
    log_file = tmp_path / "jobs.log"
    configure(dev=False, config={
        "destination": "file", "file": str(log_file), "level": level, "format": "json",
    })
    return log_file


def _json_lines(log_file: Path) -> list:
    return [jsonlib.loads(line) for line in log_file.read_text().strip().splitlines()]


# ---------------- run_with_lifecycle ----------------


def test_success_logs_started_and_succeeded_with_duration(tmp_path: Path):
    log_file = _configure_file(tmp_path)
    result = run_with_lifecycle("send_email", lambda to: f"sent:{to}", args=("x@y.z",))
    assert result == "sent:x@y.z"
    lines = _json_lines(log_file)
    assert {"job": "send_email", "status": "started"} in [
        {k: v for k, v in l.items() if k in ("job", "status")} for l in lines
    ]
    done = [l for l in lines if l.get("status") == "succeeded"]
    assert len(done) == 1
    assert done[0]["job"] == "send_email"
    assert isinstance(done[0]["duration_ms"], float)


def test_failure_logs_failed_with_traceback_and_reraises(tmp_path: Path):
    log_file = _configure_file(tmp_path)

    def boom():
        raise RuntimeError("kaput")

    with pytest.raises(RuntimeError, match="kaput"):
        run_with_lifecycle("boom_job", boom)
    failed = [l for l in _json_lines(log_file) if l.get("status") == "failed"]
    assert len(failed) == 1
    assert "RuntimeError: kaput" in failed[0]["exc_info"]


def test_failure_swallowed_when_reraise_false(tmp_path: Path):
    log_file = _configure_file(tmp_path)

    def boom():
        raise RuntimeError("kaput")

    run_with_lifecycle("boom_job", boom, reraise=False)  # must not raise
    failed = [l for l in _json_lines(log_file) if l.get("status") == "failed"]
    assert len(failed) == 1


def test_job_arguments_never_logged(tmp_path: Path):
    log_file = _configure_file(tmp_path)
    secret = "hunter2-super-secret"
    run_with_lifecycle("login_job", lambda password: None, kwargs={"password": secret})
    assert secret not in log_file.read_text()


def test_started_is_debug_level_hidden_at_info(tmp_path: Path):
    log_file = _configure_file(tmp_path, level="info")
    run_with_lifecycle("quiet_job", lambda: None)
    statuses = [l["status"] for l in _json_lines(log_file)]
    assert "started" not in statuses
    assert "succeeded" in statuses


# ---------------- ThreadedJobProvider integration ----------------


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_threaded_provider_logs_lifecycle(tmp_path: Path):
    log_file = _configure_file(tmp_path)
    provider = ThreadedJobProvider()
    provider.register_tasks({"work": lambda: None})
    provider.submit("work")
    assert _wait_for(lambda: log_file.exists() and "succeeded" in log_file.read_text())


def test_threaded_provider_failed_job_logs_once(tmp_path: Path):
    """The lifecycle wrapper swallows (reraise=False) so JobRunner's own
    _log_if_failed doesn't produce a SECOND error line for the same job."""
    log_file = _configure_file(tmp_path)

    def boom():
        raise RuntimeError("kaput")

    provider = ThreadedJobProvider()
    provider.register_tasks({"boom": boom})
    provider.submit("boom")
    assert _wait_for(lambda: log_file.exists() and "failed" in log_file.read_text())
    lines = _json_lines(log_file)
    error_lines = [l for l in lines if l.get("status") == "failed" or l.get("level") == "ERROR"]
    assert len(error_lines) == 1


# ---------------- ProcrastinateJobProvider integration ----------------


def test_procrastinate_run_worker_wraps_tasks_with_lifecycle(monkeypatch, tmp_path: Path):
    """run_worker must register lifecycle-wrapped callables (reraise=True)
    with the procrastinate App — verified against a stub App so no real
    Postgres/procrastinate is needed."""
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider

    registered = {}

    class StubApp:
        def __init__(self, connector):
            pass

        def task(self, name):
            def register(fn):
                registered[name] = fn
                return fn
            return register

        def run_worker(self, **kwargs):
            pass

    class StubProcrastinate:
        PsycopgConnector = lambda self=None, **kw: object()
        App = StubApp

    monkeypatch.setenv("DATABASE_URL", "postgres://stub")
    monkeypatch.setattr(
        "fymo.jobs.providers.procrastinate._import_procrastinate",
        lambda: StubProcrastinate(),
    )

    log_file = _configure_file(tmp_path)
    provider = ProcrastinateJobProvider()
    provider.register_tasks({"work": lambda: "done"})
    provider.run_worker()

    # The registered callable is the wrapper: invoking it produces
    # lifecycle logs and still returns the task's result.
    assert registered["work"]() == "done"
    assert "succeeded" in log_file.read_text()

    # And failures still PROPAGATE (procrastinate marks the job failed).
    provider.register_tasks({"boom": lambda: (_ for _ in ()).throw(RuntimeError("kaput"))})
    registered.clear()
    provider.run_worker()
    with pytest.raises(RuntimeError, match="kaput"):
        registered["boom"]()


def test_procrastinate_run_worker_caps_procrastinate_logger_to_warning(monkeypatch, tmp_path: Path):
    """procrastinate's own INFO lines echo job.call_string (every job
    kwarg) -- letting those through fymo's root-logger handler would leak
    job arguments. run_worker must cap the "procrastinate" logger to
    WARNING by default so errors still surface without the leak."""
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider

    class StubApp:
        def __init__(self, connector):
            pass

        def task(self, name):
            def register(fn):
                return fn
            return register

        def run_worker(self, **kwargs):
            pass

    class StubProcrastinate:
        PsycopgConnector = lambda self=None, **kw: object()
        App = StubApp

    monkeypatch.setenv("DATABASE_URL", "postgres://stub")
    monkeypatch.setattr(
        "fymo.jobs.providers.procrastinate._import_procrastinate",
        lambda: StubProcrastinate(),
    )

    procrastinate_logger = logging.getLogger("procrastinate")
    assert procrastinate_logger.level == logging.NOTSET
    try:
        _configure_file(tmp_path)
        provider = ProcrastinateJobProvider()
        provider.register_tasks({"work": lambda: "done"})
        provider.run_worker()

        assert procrastinate_logger.level == logging.WARNING
    finally:
        procrastinate_logger.setLevel(logging.NOTSET)


def test_procrastinate_run_worker_respects_explicit_info_level(monkeypatch, tmp_path: Path):
    """An app that explicitly opts into procrastinate's INFO logs (and
    accepts that they include job arguments) by calling setLevel(INFO)
    itself, before run_worker, must not have that choice silently
    overridden."""
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider

    class StubApp:
        def __init__(self, connector):
            pass

        def task(self, name):
            def register(fn):
                return fn
            return register

        def run_worker(self, **kwargs):
            pass

    class StubProcrastinate:
        PsycopgConnector = lambda self=None, **kw: object()
        App = StubApp

    monkeypatch.setenv("DATABASE_URL", "postgres://stub")
    monkeypatch.setattr(
        "fymo.jobs.providers.procrastinate._import_procrastinate",
        lambda: StubProcrastinate(),
    )

    procrastinate_logger = logging.getLogger("procrastinate")
    assert procrastinate_logger.level == logging.NOTSET
    try:
        procrastinate_logger.setLevel(logging.INFO)
        _configure_file(tmp_path)
        provider = ProcrastinateJobProvider()
        provider.register_tasks({"work": lambda: "done"})
        provider.run_worker()

        assert procrastinate_logger.level == logging.INFO
    finally:
        procrastinate_logger.setLevel(logging.NOTSET)
