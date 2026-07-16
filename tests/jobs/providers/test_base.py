"""Tests for the JobProvider seam (mirrors AuthProvider's base contract)."""
import pytest

from fymo.jobs.providers.base import BaseJobProvider, JobProvider


def test_base_provider_register_tasks_is_inert_by_default():
    provider = BaseJobProvider()
    provider.register_tasks({"anything": lambda: None})  # must not raise


def test_base_provider_submit_raises_not_implemented():
    provider = BaseJobProvider()
    with pytest.raises(NotImplementedError):
        provider.submit("some_task")


def test_base_provider_satisfies_the_protocol():
    provider = BaseJobProvider()
    assert isinstance(provider, JobProvider)


def test_base_provider_run_worker_raises_a_clear_error():
    provider = BaseJobProvider()
    with pytest.raises(RuntimeError, match="has no separate worker process"):
        provider.run_worker()


def test_base_provider_job_counts_returns_none():
    """None is the seam's documented "this provider doesn't track job
    state" signal, and the default, so existing custom providers stay
    valid without implementing the status surface."""
    assert BaseJobProvider().job_counts() is None


def test_base_provider_list_recent_jobs_returns_none():
    assert BaseJobProvider().list_recent_jobs() is None
    assert BaseJobProvider().list_recent_jobs(limit=5) is None


def test_base_provider_close_is_inert_by_default():
    BaseJobProvider().close()  # must not raise


def test_base_provider_owns_no_schema_objects_by_default():
    """A provider that creates nothing in the database (threaded, custom
    in-memory queues) declares nothing, and the schema CLI stays quiet."""
    assert BaseJobProvider().owned_schema_objects() == ()
