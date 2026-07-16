"""`fymo schema provider-tables`, what the configured providers own.

Fymo providers can create real, permanent objects in the app's database
(Procrastinate's queue tables, most famously). A declarative schema diff
tool only knows the app's own schema file, so those objects look like
strays and the generated plan proposes DROP TABLE for the live job queue
(issue #51). This command enumerates every table/function/type/sequence/
index/trigger the providers configured in fymo.yml create, so an exclude
list (or schema fragment) can be generated instead of hand-maintained.

Design notes:
  * Only the CONFIGURED providers are consulted, the same registry
    resolution `fymo serve`/`fymo jobs-worker` use, never every provider
    fymo ships. Unconfigured subsystems fall back to their defaults
    (threaded jobs, postgres broadcasts), both of which own nothing.
  * No database connection is made and none is needed: declarations come
    from provider code and bundled package metadata. If a declaration
    needs an uninstalled optional dependency, the command exits 1 naming
    the extra rather than printing a partial list.
  * stdout carries only the object list (plain or --json) so it can be
    piped straight into tooling; every note or error goes to stderr.
  * Future providers/stores that create objects (e.g. an auth user store
    with fymo_* tables) join by implementing owned_schema_objects() and
    getting resolved in _configured_providers() below.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from fymo.core.config import ConfigManager
from fymo.core.schema import owned_schema_objects


def _configured_providers(config_manager: ConfigManager):
    from fymo.broadcast.providers.registry import build_broadcast_provider
    from fymo.jobs.providers.registry import build_job_provider

    return (
        build_job_provider(config_manager.get_jobs_config().get("provider")),
        build_broadcast_provider(config_manager.get_broadcasts_config().get("provider")),
    )


def run_provider_tables(project_root: Optional[Path] = None, as_json: bool = False) -> None:
    """Print the schema objects owned by the project's configured providers.

    Plain output is one `<kind> <name>` per line in the provider's own
    declaration order; --json emits a list of {kind, name, provider}
    objects. Empty ownership is a success (exit 0): empty stdout (or `[]`
    with --json) plus a stderr note."""
    project_root = Path(project_root) if project_root else Path.cwd()
    config_manager = ConfigManager(project_root)

    entries = []
    seen = set()
    try:
        for provider in _configured_providers(config_manager):
            for obj in owned_schema_objects(provider):
                if (obj.kind, obj.name) in seen:
                    continue
                seen.add((obj.kind, obj.name))
                entries.append((provider.id, obj))
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if as_json:
        print(json.dumps([
            {"kind": obj.kind, "name": obj.name, "provider": provider_id}
            for provider_id, obj in entries
        ]))
    else:
        for _, obj in entries:
            print(f"{obj.kind} {obj.name}")

    if not entries:
        print("no configured provider owns schema objects", file=sys.stderr)
