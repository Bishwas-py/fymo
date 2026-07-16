"""The utilities' whole point is cleanup: global registries must be exactly
as found after any combination of fymo.testing blocks."""
from pathlib import Path

import pytest

import fymo.broadcast as broadcast_mod
import fymo.jobs as jobs_mod
import fymo.storage as storage_mod
from fymo.auth import context as auth_context
from fymo.auth.context import current_user
from fymo.remote.context import _current_event
from fymo.testing import acting_as, init_providers, make_user, signed_in


def _snapshot():
    return {
        "resolvers": list(auth_context._session_resolvers),
        "storage": storage_mod._provider,
        "jobs": jobs_mod._job_provider,
        "broadcast_provider": broadcast_mod._provider,
        "broadcast_channels": broadcast_mod._channels,
        "event": _current_event.get(),
    }


def test_two_utilities_back_to_back_leave_registries_as_found(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text("name: t\nstorage: {provider: local}\n")
    before = _snapshot()

    with signed_in(make_user(email="one@example.com")) as one:
        assert current_user() is one

    with init_providers(tmp_path):
        storage_mod.get_storage_provider()

    assert _snapshot() == before


def test_combined_usage_then_clean(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text("name: t\nstorage: {provider: local}\n")
    before = _snapshot()

    alice = make_user(email="alice@example.com")
    bob = make_user(email="bob@example.com")
    with init_providers(tmp_path):
        with signed_in(alice):
            with acting_as(bob):
                assert current_user() is bob
                storage_mod.get_storage_provider().write("k.txt", b"v")
            assert current_user() is alice

    assert _snapshot() == before
    with pytest.raises(RuntimeError):
        storage_mod.get_storage_provider()
    with pytest.raises(RuntimeError):
        current_user()
