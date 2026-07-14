"""Remote mode resolution: collapse explicit_optin + allow_implicit into a tristate.

The remote: section of fymo.yml originally used two independent booleans:
- explicit_optin: true/false — gates whether only @remote-decorated functions dispatch
- allow_implicit: true/false — silences the build-time hygiene check (only read when
  explicit_optin is false)

These are not independent: they're one three-state decision wearing two boolean flags.
This module collapses them into a single remote.mode key with two valid values:
- strict: only @remote-decorated functions expose, hygiene check enforced
- implicit-legacy: all public functions expose, hygiene check silenced (unsafe, temporary)

The old boolean keys remain accepted for one deprecation cycle for back-compat, but
remote.mode is the canonical interface. Combining mode: with either deprecated key
is a hard config error (ambiguous).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class RemoteModeConfigError(Exception):
    """Raised when a remote.mode value is invalid or conflicts with deprecated keys."""


@dataclass(frozen=True)
class RemoteMode:
    """Resolved remote configuration state.

    strict: bool
        True if only @remote-decorated functions can dispatch (explicit opt-in mode).
        False if all public functions can dispatch (implicit mode).

    hygiene_enforced: bool
        True if fymo build hard-fails when discovering unmarked remote functions
        that would be exposed under implicit mode. False if the hygiene check is
        silenced (unsafe, for apps not yet ready to add @remote markers).
    """
    strict: bool
    hygiene_enforced: bool


def resolve_remote_mode(remote_config: Optional[Dict[str, Any]]) -> RemoteMode:
    """Resolve remote configuration into a RemoteMode triple.

    Implements the truth table from issue #25:
    - nothing set -> strict=False, hygiene_enforced=True (implicit, checked)
    - explicit_optin: true (deprecated) -> strict=True, hygiene_enforced=False
    - allow_implicit: true (deprecated) -> strict=False, hygiene_enforced=False
    - mode: strict -> strict=True, hygiene_enforced=False
    - mode: implicit-legacy -> strict=False, hygiene_enforced=False
    - mode: <other> -> raises RemoteModeConfigError
    - mode: combined with explicit_optin or allow_implicit -> raises RemoteModeConfigError
    - explicit_optin: true AND allow_implicit: true (no mode:) -> strict=True, hygiene_enforced=False
      (discovery uses explicit_optin, hygiene returns [] if EITHER flag is true, per today's behavior)

    Pure function, no I/O or side effects.
    """
    config = remote_config or {}

    # Check for conflicting configuration: mode: combined with deprecated keys.
    has_mode = "mode" in config
    has_explicit_optin = "explicit_optin" in config
    has_allow_implicit = "allow_implicit" in config

    if has_mode and (has_explicit_optin or has_allow_implicit):
        if has_explicit_optin:
            raise RemoteModeConfigError(
                "remote.mode conflicts with deprecated remote.explicit_optin. "
                "Use remote.mode: strict or remote.mode: implicit-legacy, not both."
            )
        if has_allow_implicit:
            raise RemoteModeConfigError(
                "remote.mode conflicts with deprecated remote.allow_implicit. "
                "Use remote.mode: strict or remote.mode: implicit-legacy, not both."
            )

    # Resolve the new mode: key if present.
    if has_mode:
        mode_val = config["mode"]
        if mode_val == "strict":
            return RemoteMode(strict=True, hygiene_enforced=False)
        elif mode_val == "implicit-legacy":
            return RemoteMode(strict=False, hygiene_enforced=False)
        else:
            raise RemoteModeConfigError(
                f"unknown remote.mode value: {mode_val!r}. "
                f"Valid values are 'strict' and 'implicit-legacy'."
            )

    # Fall back to deprecated keys. Both flags default to False if absent.
    explicit_optin = config.get("explicit_optin", False)
    allow_implicit = config.get("allow_implicit", False)

    # If either flag is true, apply its meaning. The discovery gate uses
    # explicit_optin; the hygiene check returns [] if EITHER is true (checks
    # explicit_optin first today). Preserve this exact behavior for back-compat.
    if explicit_optin:
        # Dispatch gate is on, hygiene check is off. Once dispatch is gated, the
        # hygiene scan is redundant; it would only false-flag private helpers that
        # are already safely non-dispatchable.
        return RemoteMode(strict=True, hygiene_enforced=False)
    elif allow_implicit:
        # Dispatch gate is off, hygiene check is off (this flag's whole purpose).
        return RemoteMode(strict=False, hygiene_enforced=False)
    else:
        # Neither flag set: implicit mode, but with hygiene check enforced (the default).
        return RemoteMode(strict=False, hygiene_enforced=True)


def uses_deprecated_remote_flags(remote_config: Optional[Dict[str, Any]]) -> bool:
    """Return True if the config uses deprecated explicit_optin or allow_implicit keys.

    Returns True if either key is present in the config (regardless of value),
    False otherwise. Does not trigger for the mode:-only case or when no config
    is present (neither keys nor mode: set).

    Used by the build system to decide whether to print a deprecation warning.
    """
    config = remote_config or {}
    return "explicit_optin" in config or "allow_implicit" in config
