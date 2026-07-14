"""fymo broadcasts — typed server→browser push, "intuitive like remote
functions".

An app declares channels in app/broadcasts/*.py (signature = subscribe
args, return annotation = payload type, body = subscribe-time auth guard),
publishes from anywhere server-side with `publish()`, and subscribes from
the browser via the generated `$broadcast/<module>` client (SSE under the
hood). Transport is pluggable (fymo.broadcast.providers); the default
needs nothing beyond the Postgres fymo apps already use.

Design notes: journal/journal_009.md
"""
from __future__ import annotations

import hashlib
import inspect
import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

__all__ = [
    "channel_key",
    "publish",
    "get_broadcast_provider",
    "set_broadcast_provider",
    "init_broadcasts",
    "reset_broadcasts",
]


def channel_key(module: str, channel: str, args: Dict[str, Any]) -> str:
    """Encode module + channel + subscribe-time args into a LISTEN/NOTIFY
    channel name: deterministic, collision-safe, and a valid Postgres
    identifier (≤ 63 chars). Different arg values → different keys, so
    subscribers with different run_ids never see each other's events."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(f"{module}.{channel}:{canonical}".encode()).hexdigest()[:24]
    return f"fymo_bc_{digest}"


# --- process-wide provider + channel registry ---------------------------
#
# Mirrors fymo.jobs' provider singleton: FymoApp calls init_broadcasts()
# at startup; app code then publishes from anywhere without wiring
# anything. The channel registry (from app/broadcasts/*.py discovery)
# lives here too, since publish() needs it to validate the channel and
# bind its args.

_provider: Optional[Any] = None
_channels: Optional[Dict[str, Tuple[str, Callable]]] = None
_lock = threading.Lock()


def set_broadcast_provider(provider: Any) -> None:
    """Replace the process-wide BroadcastProvider singleton."""
    global _provider
    with _lock:
        _provider = provider


def get_broadcast_provider() -> Any:
    """Return the process-wide BroadcastProvider, creating the default
    (PostgresBroadcastProvider) on first use."""
    global _provider
    with _lock:
        if _provider is None:
            from fymo.broadcast.providers.registry import build_broadcast_provider
            _provider = build_broadcast_provider(None)
        return _provider


def get_channels() -> Dict[str, Tuple[str, Callable]]:
    """The discovered channel registry ({name: (module, fn)}), or raise if
    init_broadcasts() hasn't run in this process."""
    if _channels is None:
        raise RuntimeError(
            "broadcasts are not initialized — FymoApp calls init_broadcasts() "
            "at startup; a separate process (e.g. a job worker) must call "
            "fymo.broadcast.init_broadcasts(project_root, config) itself"
        )
    return _channels


def init_broadcasts(project_root: Path, provider_config: Any) -> Any:
    """Discover app/broadcasts/*.py, build the configured provider, install
    both process-wide, and return the provider. Called by FymoApp at
    startup (and by `fymo jobs-worker`, so jobs can publish)."""
    global _provider, _channels
    from fymo.broadcast.discovery import discover_broadcast_channels
    from fymo.broadcast.providers.registry import build_broadcast_provider

    channels = discover_broadcast_channels(project_root)
    provider = build_broadcast_provider(provider_config)
    with _lock:
        _channels = channels
        _provider = provider
    return provider


def publish(channel: str, data: Any = None, **args: Any) -> None:
    """Publish `data` to everyone currently subscribed to `channel` with
    exactly these args. Fire-and-forget: no subscribers, no delivery, no
    error. `args` must match the channel function's declared signature —
    they select WHICH subscribers receive it; `data` is WHAT they receive.

        publish("run_status", run_id=run.id, data={"status": "passed"})
    """
    channels = get_channels()
    if channel not in channels:
        raise ValueError(f"unknown broadcast channel: {channel!r}")
    module, fn = channels[channel]
    bound = inspect.signature(fn).bind(**args)
    bound.apply_defaults()
    key = channel_key(module, channel, dict(bound.arguments))
    get_broadcast_provider().publish(key, json.dumps(data))


def reset_broadcasts() -> None:
    """Test-only: clear the provider and channel registry."""
    global _provider, _channels
    with _lock:
        _provider = None
        _channels = None
