"""Tests for fymo.remote.mode resolver (remote.mode tristate configuration)."""
import pytest

from fymo.remote.mode import (
    RemoteMode,
    RemoteModeConfigError,
    resolve_remote_mode,
    uses_deprecated_remote_flags,
)


class TestResolveRemoteMode:
    """Test the resolve_remote_mode function against the truth table."""

    def test_nothing_set(self):
        """When remote config is empty or None, use implicit mode with hygiene enforced."""
        assert resolve_remote_mode(None) == RemoteMode(strict=False, hygiene_enforced=True)
        assert resolve_remote_mode({}) == RemoteMode(strict=False, hygiene_enforced=True)

    def test_explicit_optin_true_deprecated(self):
        """explicit_optin: true (deprecated) -> strict mode, hygiene NOT enforced.

        Hygiene_enforced is False because once dispatch is gated, the hygiene scan
        becomes redundant and would only false-flag private helpers already gated by
        dispatch itself.
        """
        result = resolve_remote_mode({"explicit_optin": True})
        assert result == RemoteMode(strict=True, hygiene_enforced=False)

    def test_allow_implicit_true_deprecated(self):
        """allow_implicit: true (deprecated) -> implicit mode, hygiene NOT enforced."""
        result = resolve_remote_mode({"allow_implicit": True})
        assert result == RemoteMode(strict=False, hygiene_enforced=False)

    def test_mode_strict(self):
        """mode: strict -> strict mode, hygiene NOT enforced.

        Hygiene_enforced is False because once dispatch is gated, the hygiene scan
        becomes redundant and would only false-flag private helpers already gated by
        dispatch itself.
        """
        result = resolve_remote_mode({"mode": "strict"})
        assert result == RemoteMode(strict=True, hygiene_enforced=False)

    def test_mode_implicit_legacy(self):
        """mode: implicit-legacy -> implicit mode, hygiene NOT enforced."""
        result = resolve_remote_mode({"mode": "implicit-legacy"})
        assert result == RemoteMode(strict=False, hygiene_enforced=False)

    def test_mode_invalid_value(self):
        """mode with invalid value raises RemoteModeConfigError."""
        with pytest.raises(RemoteModeConfigError) as exc_info:
            resolve_remote_mode({"mode": "bogus"})
        error_msg = str(exc_info.value)
        assert "bogus" in error_msg
        assert "strict" in error_msg
        assert "implicit-legacy" in error_msg

    def test_mode_with_explicit_optin_conflict(self):
        """mode: combined with explicit_optin raises RemoteModeConfigError."""
        with pytest.raises(RemoteModeConfigError) as exc_info:
            resolve_remote_mode({"mode": "strict", "explicit_optin": True})
        error_msg = str(exc_info.value)
        assert "mode" in error_msg.lower()
        assert "explicit_optin" in error_msg

    def test_mode_with_allow_implicit_conflict(self):
        """mode: combined with allow_implicit raises RemoteModeConfigError."""
        with pytest.raises(RemoteModeConfigError) as exc_info:
            resolve_remote_mode({"mode": "strict", "allow_implicit": True})
        error_msg = str(exc_info.value)
        assert "mode" in error_msg.lower()
        assert "allow_implicit" in error_msg

    def test_explicit_optin_and_allow_implicit_both_set(self):
        """Both deprecated keys set (no mode:) preserves today's behavior.

        discovery uses explicit_optin (True), hygiene returns [] if EITHER is true
        (checks explicit_optin first). So: strict=True, hygiene_enforced=False.
        """
        result = resolve_remote_mode({"explicit_optin": True, "allow_implicit": True})
        assert result == RemoteMode(strict=True, hygiene_enforced=False)


class TestUsesDeprecatedRemoteFlags:
    """Test the uses_deprecated_remote_flags helper."""

    def test_explicit_optin_true(self):
        """explicit_optin: true is deprecated."""
        assert uses_deprecated_remote_flags({"explicit_optin": True})

    def test_explicit_optin_false_still_deprecated(self):
        """explicit_optin: false still counts as using the deprecated key."""
        assert uses_deprecated_remote_flags({"explicit_optin": False})

    def test_allow_implicit_true(self):
        """allow_implicit: true is deprecated."""
        assert uses_deprecated_remote_flags({"allow_implicit": True})

    def test_allow_implicit_false_still_deprecated(self):
        """allow_implicit: false still counts as using the deprecated key."""
        assert uses_deprecated_remote_flags({"allow_implicit": False})

    def test_empty_config(self):
        """Empty config does not use deprecated flags."""
        assert not uses_deprecated_remote_flags({})

    def test_none_config(self):
        """None config does not use deprecated flags."""
        assert not uses_deprecated_remote_flags(None)

    def test_mode_only(self):
        """mode: key alone does not trigger deprecation warning."""
        assert not uses_deprecated_remote_flags({"mode": "strict"})

    def test_both_deprecated_flags(self):
        """Both deprecated flags present still counts as using deprecated."""
        assert uses_deprecated_remote_flags({"explicit_optin": True, "allow_implicit": False})

    def test_mode_with_deprecated_flags(self):
        """Having mode: does not suppress deprecation detection."""
        assert uses_deprecated_remote_flags({"mode": "strict", "explicit_optin": True})
