"""fymo.testing.init_providers: fymo.yml-driven provider bootstrap for bare test processes."""
from pathlib import Path

import pytest

import fymo.broadcast as broadcast_mod
import fymo.jobs as jobs_mod
import fymo.storage as storage_mod
from fymo.storage import get_storage_provider
from fymo.storage.providers.local import LocalStorageProvider
from fymo.testing import init_providers


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "fymo.yml").write_text(
        "name: scaffold\n"
        "storage:\n"
        "  provider: local\n"
        "  root: app/data/files\n"
    )
    return tmp_path


def test_storage_provider_works_inside_block(project: Path):
    with init_providers(project):
        provider = get_storage_provider()
        assert isinstance(provider, LocalStorageProvider)
        provider.write("hello.txt", b"hi")
        assert (project / "app" / "data" / "files" / "hello.txt").read_bytes() == b"hi"


def test_storage_raises_after_block(project: Path):
    with init_providers(project):
        get_storage_provider()
    with pytest.raises(RuntimeError):
        get_storage_provider()


def test_jobs_and_broadcasts_initialized(project: Path):
    from fymo.jobs import get_job_provider
    from fymo.jobs.providers.threaded import ThreadedJobProvider

    with init_providers(project):
        assert isinstance(get_job_provider(), ThreadedJobProvider)
        assert broadcast_mod.get_channels() == {}


def test_yields_the_built_providers(project: Path):
    with init_providers(project) as providers:
        assert providers.storage is get_storage_provider()
        assert providers.jobs is jobs_mod.get_job_provider()
        assert providers.broadcasts is broadcast_mod.get_broadcast_provider()


def test_no_storage_section_skips_storage(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text("name: bare\n")
    with init_providers(tmp_path) as providers:
        assert providers.storage is None
        with pytest.raises(RuntimeError):
            get_storage_provider()


def test_restores_prior_providers_exactly(project: Path):
    sentinel = object()
    storage_mod.set_storage_provider(sentinel)
    prior_jobs = jobs_mod._job_provider
    prior_bc = broadcast_mod._provider
    prior_channels = broadcast_mod._channels
    try:
        with init_providers(project):
            assert get_storage_provider() is not sentinel
        assert get_storage_provider() is sentinel
        assert jobs_mod._job_provider is prior_jobs
        assert broadcast_mod._provider is prior_bc
        assert broadcast_mod._channels is prior_channels
    finally:
        storage_mod.reset_storage_provider()


def test_cleanup_when_body_raises(project: Path):
    prior_storage = storage_mod._provider
    prior_jobs = jobs_mod._job_provider
    prior_bc = broadcast_mod._provider
    prior_channels = broadcast_mod._channels
    with pytest.raises(ValueError):
        with init_providers(project):
            raise ValueError("boom")
    assert storage_mod._provider is prior_storage
    assert jobs_mod._job_provider is prior_jobs
    assert broadcast_mod._provider is prior_bc
    assert broadcast_mod._channels is prior_channels


def test_partial_init_failure_restores_prior_storage(tmp_path: Path):
    from fymo.jobs.providers.registry import JobProviderConfigError

    (tmp_path / "fymo.yml").write_text(
        "name: broken\n"
        "storage: {provider: local}\n"
        "jobs: {provider: nosuchprovider}\n"
    )
    sentinel = object()
    storage_mod.set_storage_provider(sentinel)
    try:
        with pytest.raises(JobProviderConfigError):
            with init_providers(tmp_path):
                pass
        assert storage_mod._provider is sentinel
    finally:
        storage_mod.reset_storage_provider()


def test_missing_fymo_yml_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        with init_providers(tmp_path / "nowhere"):
            pass
