"""The utilities' whole point is cleanup: global registries must be exactly
as found after any combination of fymo.testing blocks."""
from pathlib import Path

import pytest

import fymo.broadcast as broadcast_mod
import fymo.jobs as jobs_mod
import fymo.storage as storage_mod
from fymo.auth import current_uid
from fymo.auth.identity import registered_identity_resolvers
from fymo.remote.context import _current_event
from fymo.testing import acting_as, init_providers, signed_in


def _snapshot():
    return {
        "resolvers": registered_identity_resolvers(),
        "storage": storage_mod._provider,
        "jobs": jobs_mod._job_provider,
        "broadcast_provider": broadcast_mod._provider,
        "broadcast_channels": broadcast_mod._channels,
        "event": _current_event.get(),
    }


def test_two_utilities_back_to_back_leave_registries_as_found(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text("name: t\nstorage: {provider: local}\n")
    before = _snapshot()

    with signed_in("u_one"):
        assert current_uid() == "u_one"

    with init_providers(tmp_path):
        storage_mod.get_storage_provider()

    assert _snapshot() == before


def test_combined_usage_then_clean(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text("name: t\nstorage: {provider: local}\n")
    before = _snapshot()

    with init_providers(tmp_path):
        with signed_in("u_alice"):
            with acting_as("u_bob"):
                assert current_uid() == "u_bob"
                storage_mod.get_storage_provider().write("k.txt", b"v")
            assert current_uid() == "u_alice"

    assert _snapshot() == before
    with pytest.raises(RuntimeError):
        storage_mod.get_storage_provider()
    with pytest.raises(RuntimeError):
        current_uid()
