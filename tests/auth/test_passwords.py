"""scrypt password hashing — round-trip + tamper rejection."""
import pytest
from fymo.auth.passwords import hash_password, verify_password


def test_round_trip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_wrong_password_rejected():
    h = hash_password("secret123")
    assert verify_password("secret124", h) is False


def test_unique_salt_per_hash():
    a = hash_password("hello")
    b = hash_password("hello")
    assert a != b  # different salts
    assert verify_password("hello", a)
    assert verify_password("hello", b)


def test_hash_format_is_parseable():
    h = hash_password("x")
    parts = h.split("$")
    assert parts[0] == "scrypt"
    assert len(parts) == 6


def test_garbage_stored_value_returns_false():
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "scrypt$bad") is False
    assert verify_password("anything", "") is False


def test_empty_plaintext_rejected_on_hash():
    with pytest.raises(ValueError):
        hash_password("")


def test_empty_plaintext_rejected_on_verify():
    h = hash_password("real")
    assert verify_password("", h) is False
