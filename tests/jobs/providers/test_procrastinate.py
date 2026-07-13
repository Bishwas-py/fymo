"""Tests for ProcrastinateJobProvider against a real Postgres database.

Skipped entirely if TEST_DATABASE_URL isn't set — Procrastinate needs a
real Postgres instance (no in-memory/SQLite mode), unlike the rest of
fymo's test suite. Point it at any throwaway Postgres, e.g. the same
container a consuming app's tests already use.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs TEST_DATABASE_URL pointing at a real Postgres instance",
)


@pytest.fixture
def database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture(autouse=True)
def _apply_schema(database_url):
    import procrastinate
    from procrastinate import exceptions, schema
    connector = procrastinate.SyncPsycopgConnector(conninfo=database_url)
    connector.open()
    try:
        schema.SchemaManager(connector).apply_schema()
    except exceptions.ConnectorException as e:
        # Fine if a previous run already applied it — apply_schema isn't
        # idempotent (CREATE TYPE has no IF NOT EXISTS), but re-running
        # against a database that already has the tables is harmless.
        if "already exists" not in str(e.__cause__):
            raise
    connector.close()


def test_submit_defers_a_job_and_a_worker_can_execute_it(database_url, monkeypatch):
    """The real end-to-end proof: defer through the provider (sync
    connector, as a fymo request would), then run an actual Procrastinate
    worker (async connector, as the separate `fymo jobs-worker` process
    would) and confirm it really executes the task."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider

    result = {}

    def add_numbers(a, b):
        result["sum"] = a + b

    provider = ProcrastinateJobProvider()
    provider.register_tasks({"add_numbers": add_numbers})
    provider.submit("add_numbers", 2, b=3)

    # Run a real worker (separate App, async connector) to pick up and
    # execute the deferred job, mirroring what `fymo jobs-worker` does.
    import procrastinate
    worker_connector = procrastinate.PsycopgConnector(conninfo=database_url)
    worker_app = procrastinate.App(connector=worker_connector)
    worker_app.task(name="add_numbers")(add_numbers)
    worker_app.run_worker(wait=False, listen_notify=False)

    assert result == {"sum": 5}


def test_submit_binds_positional_args_to_task_parameter_names(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider
    import procrastinate

    result = {}

    def greet(name, greeting):
        result["message"] = f"{greeting}, {name}!"

    provider = ProcrastinateJobProvider()
    provider.register_tasks({"greet": greet})
    provider.submit("greet", "Ada", "Hello")  # both positional

    worker_connector = procrastinate.PsycopgConnector(conninfo=database_url)
    worker_app = procrastinate.App(connector=worker_connector)
    worker_app.task(name="greet")(greet)
    worker_app.run_worker(wait=False, listen_notify=False)

    assert result == {"message": "Hello, Ada!"}


def test_submit_raises_on_unknown_task(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider
    provider = ProcrastinateJobProvider()
    provider.register_tasks({})
    with pytest.raises(ValueError, match="unknown job task: 'nope'"):
        provider.submit("nope")


def test_run_worker_drains_the_queue_and_returns_when_wait_is_false(database_url, monkeypatch):
    """`fymo jobs-worker` calls run_worker() and expects it to block forever
    (wait=True is the real default), but for this test we want it to drain
    whatever's queued and return so the test doesn't hang — exactly the
    `wait=False, listen_notify=False` shape proven live against this same
    container before this provider was written."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider

    result = {}

    def add_numbers(a, b):
        result["sum"] = a + b

    provider = ProcrastinateJobProvider()
    provider.register_tasks({"add_numbers": add_numbers})
    provider.submit("add_numbers", 2, b=3)

    provider.run_worker(wait=False, listen_notify=False)

    assert result == {"sum": 5}
