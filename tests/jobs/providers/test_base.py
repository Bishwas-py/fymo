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
