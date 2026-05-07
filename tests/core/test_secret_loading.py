"""FymoApp identity-secret resolution: env var, .fymo/secret.key, prod failure."""
import os
from pathlib import Path
import pytest
from fymo.core.server import _load_identity_secret


def test_loads_secret_from_env_var(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FYMO_SECRET", "x" * 32)
    secret = _load_identity_secret(tmp_path, dev=False)
    assert secret == b"x" * 32


def test_rejects_too_short_env_var(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FYMO_SECRET", "short")
    with pytest.raises(RuntimeError, match="shorter than 16 characters"):
        _load_identity_secret(tmp_path, dev=False)


def test_dev_mode_auto_generates_secret_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("FYMO_SECRET", raising=False)
    secret = _load_identity_secret(tmp_path, dev=True)
    assert len(secret) >= 16
    # Persisted to disk
    secret_file = tmp_path / ".fymo" / "secret.key"
    assert secret_file.is_file()
    assert secret_file.read_bytes() == secret


def test_dev_mode_reuses_existing_secret_file(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("FYMO_SECRET", raising=False)
    secret_file = tmp_path / ".fymo" / "secret.key"
    secret_file.parent.mkdir(parents=True)
    existing = b"persisted-32-byte-secret-blob---"
    secret_file.write_bytes(existing)
    secret = _load_identity_secret(tmp_path, dev=True)
    assert secret == existing


def test_prod_without_env_or_keyfile_raises(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("FYMO_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="FYMO_SECRET environment variable is required"):
        _load_identity_secret(tmp_path, dev=False)


def test_prod_with_keyfile_works(monkeypatch, tmp_path: Path):
    """If a previous dev run wrote .fymo/secret.key, prod can pick it up."""
    monkeypatch.delenv("FYMO_SECRET", raising=False)
    secret_file = tmp_path / ".fymo" / "secret.key"
    secret_file.parent.mkdir(parents=True)
    secret_file.write_bytes(b"some-32-byte-secret-blob--------")
    secret = _load_identity_secret(tmp_path, dev=False)
    assert secret == b"some-32-byte-secret-blob--------"
