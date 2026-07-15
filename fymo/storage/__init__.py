"""Fymo storage: a pluggable seam for where binary blobs (media, uploads,
generated files) actually live.

    from fymo.storage.base import StorageProvider
    from fymo.storage.registry import build_storage_provider

The fymo.yml `storage:` section selects a provider (built-in `local`, or a
`class:` dotted path to a custom one). See `fymo.storage.base.StorageProvider`
for the Protocol.

App code (a remote function, a job) never calls `build_storage_provider`
directly. It reaches the same provider `FymoApp` built at startup through
the process-wide accessor below:

    from fymo.storage import get_storage_provider

    get_storage_provider().write("videos/clip.webm", data)

`get_storage_provider()` mirrors `fymo.jobs.get_job_provider()` and
`fymo.broadcast.get_broadcast_provider()`: a no-arg singleton, installed by
`init_storage_provider(project_root, storage_config)` (called by `FymoApp`
at startup, and by `fymo jobs-worker` for the separate worker process). One
deliberate difference from those two: storage has no default provider (see
`fymo.storage.registry`'s docstring), so `get_storage_provider()` raises
instead of silently constructing a local-disk fallback when nothing has
initialized it yet.

`write(key, data)` takes a complete `bytes` payload, there is no streaming
append. Something that produces bytes incrementally, like a Playwright
recording running live, can't call it until the recording is finished. The
pattern is: record to a scratch path on local disk (e.g. a temp file, or
`app/data/tmp/`), then read the finished file and call `write()` once with
the whole thing. That's also the pattern that keeps working once storage
stops being local disk (#17, S3/R2 providers): those backends don't offer a
"keep appending to this key" operation either, a live recording has to land
somewhere writable before it becomes a single `write()` call.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from fymo.storage.base import StorageProvider

__all__ = [
    "StorageProvider",
    "set_storage_provider",
    "get_storage_provider",
    "init_storage_provider",
    "reset_storage_provider",
]

# --- process-wide provider singleton -------------------------------------
#
# Mirrors fymo.jobs' and fymo.broadcast's provider singletons: FymoApp calls
# init_storage_provider() at startup (whenever storage: is configured, not
# only when media: is also configured, see fymo/core/server.py), and
# fymo jobs-worker does the same for its own separate process. App code then
# calls get_storage_provider() from anywhere without wiring anything itself.

_provider: Optional[Any] = None
_lock = threading.Lock()


def set_storage_provider(provider: Any) -> None:
    """Replace the process-wide StorageProvider singleton."""
    global _provider
    with _lock:
        _provider = provider


def get_storage_provider() -> Any:
    """Return the process-wide StorageProvider.

    Unlike `get_job_provider()`/`get_broadcast_provider()`, there is no
    default to fall back to, storage has none on purpose (see
    `fymo.storage.registry`'s docstring). Raises `RuntimeError` if
    `init_storage_provider()` hasn't run in this process yet.
    """
    with _lock:
        if _provider is None:
            raise RuntimeError(
                "storage is not initialized — FymoApp calls init_storage_provider() "
                "at startup when storage: is configured in fymo.yml; a separate "
                "process (e.g. a job worker) must call "
                "fymo.storage.init_storage_provider(project_root, storage_config) itself"
            )
        return _provider


def init_storage_provider(project_root: Path, storage_config: Any) -> Any:
    """Build the configured StorageProvider, install it as the process-wide
    singleton, and return it. Raises `StorageConfigError` (see
    `fymo.storage.registry`) if `storage_config` is falsy, there is no
    default provider.

    Called once by FymoApp at startup (mirrors `fymo.jobs.init_job_provider`
    and `fymo.broadcast.init_broadcasts`), and by `fymo jobs-worker` for its
    own separate process.
    """
    from fymo.storage.registry import build_storage_provider

    provider = build_storage_provider(storage_config, project_root)
    set_storage_provider(provider)
    return provider


def reset_storage_provider() -> None:
    """Test-only: clear the shared StorageProvider so each test gets
    isolation. Not meant to be called from application code."""
    global _provider
    with _lock:
        _provider = None
