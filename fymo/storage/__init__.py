"""Fymo storage: a pluggable seam for where binary blobs (media, uploads,
generated files) actually live.

    from fymo.storage.base import StorageProvider
    from fymo.storage.registry import build_storage_provider

The fymo.yml `storage:` section selects a provider (built-in `local`, or a
`class:` dotted path to a custom one). See `fymo.storage.base.StorageProvider`
for the Protocol.
"""
