"""The BroadcastProvider seam — third repeat of the auth/jobs pattern.

A provider is pure transport, below the developer-facing API: it moves an
opaque payload string from `publish()` in one process to every
`listen()`er of the same channel key in any other process. Channel
resolution, auth guards, arg typing, and SSE framing all live above the
seam, so swapping the transport (postgres → redis → custom) never touches
app code or the generated client.
"""
from __future__ import annotations

from typing import Iterator, Optional, Protocol, Tuple, runtime_checkable
import threading

from fymo.core.schema import SchemaObject


@runtime_checkable
class BroadcastProvider(Protocol):
    id: str

    def publish(self, key: str, payload: str) -> None: ...
    def listen(self, key: str, ready: Optional[threading.Event] = None) -> Iterator[str]: ...


class BaseBroadcastProvider:
    """Inert defaults so a provider only implements what it needs."""

    id: str = ""

    def publish(self, key: str, payload: str) -> None:
        """Deliver `payload` to every current listener of `key`.
        Fire-and-forget: no listeners means the payload is dropped."""
        raise NotImplementedError

    def listen(self, key: str, ready: Optional[threading.Event] = None) -> Iterator[Optional[str]]:
        """Yield each payload published to `key` until the consumer closes
        the generator. Sets `ready` (when given) once the subscription is
        actually established — publishes before that point may be missed;
        publishes after it must not be.

        Yields `None` as an idle tick every ~15s of silence so the caller
        can emit an SSE keepalive — which doubles as disconnect detection:
        writing the keepalive to a gone client raises, closing this
        generator and releasing the provider's resources."""
        raise NotImplementedError

    def owned_schema_objects(self) -> Tuple[SchemaObject, ...]:
        """The database objects this provider creates for itself (`fymo
        schema provider-tables`). The built-in postgres provider is pure
        LISTEN/NOTIFY and creates none, so this default stands for it. Kept
        off the BroadcastProvider Protocol for the same isinstance()
        compatibility reason as BaseJobProvider.owned_schema_objects."""
        return ()
