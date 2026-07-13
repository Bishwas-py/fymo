"""Tests for build_job_provider — mirrors fymo.auth.providers.registry's tests."""
import pytest

from fymo.jobs.providers.base import BaseJobProvider
from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider
from fymo.jobs.providers.registry import JobProviderConfigError, build_job_provider
from fymo.jobs.providers.threaded import ThreadedJobProvider


def test_defaults_to_threaded_when_unset():
    provider = build_job_provider(None)
    assert isinstance(provider, ThreadedJobProvider)


def test_builds_threaded_from_bare_string():
    provider = build_job_provider("threaded")
    assert isinstance(provider, ThreadedJobProvider)


def test_unknown_builtin_string_raises():
    with pytest.raises(JobProviderConfigError, match="unknown built-in job provider: 'nope'"):
        build_job_provider("nope")


def test_builds_procrastinate_from_bare_string():
    provider = build_job_provider("procrastinate")
    assert isinstance(provider, ProcrastinateJobProvider)


def test_builds_from_type_key():
    provider = build_job_provider({"type": "threaded"})
    assert isinstance(provider, ThreadedJobProvider)


def test_unknown_type_key_raises():
    with pytest.raises(JobProviderConfigError, match="unknown built-in job provider type: 'nope'"):
        build_job_provider({"type": "nope"})


def test_missing_type_or_class_key_raises():
    with pytest.raises(JobProviderConfigError, match="needs a 'type' or 'class' key"):
        build_job_provider({"queue": "default"})


def test_builds_from_dotted_class_path():
    provider = build_job_provider({"class": "fymo.jobs.providers.base.BaseJobProvider"})
    assert isinstance(provider, BaseJobProvider)


def test_bad_dotted_class_path_raises():
    with pytest.raises(JobProviderConfigError, match="could not be imported"):
        build_job_provider({"class": "totally.fake.module.Class"})


def test_invalid_config_type_raises():
    with pytest.raises(JobProviderConfigError, match="must be a string or object"):
        build_job_provider(123)
