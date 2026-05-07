"""Test fixtures for fymo.remote tests.

Installs a deterministic HMAC secret so tests that exercise the remote
router (which calls _ensure_uid) don't fail on the
`identity secret not configured` guard.
"""
import pytest
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _identity_secret_installed():
    set_secret(b"test-secret-32-bytes-of-padding!")
    yield
