"""Shared pre-esbuild build-configuration preparation for `fymo build` and
`fymo dev`.

`BuildPipeline.build()` and `DevOrchestrator.start()` used to re-derive the
same sequence line for line: hygiene check, route discovery,
write_client_entries, layout discovery + `_layout-<id>` entries,
`_global.css` detection, remote-module discovery (incl. the sys.path
insert/remove dance) + emit_runtime/emit_module, emit_broadcast_client, SSR
tree composition -- diverging only at the esbuild invocation itself
(subprocess.run + strict manifest for `fymo build`, Popen + streaming +
lenient manifest for `fymo dev`). This exact duplication pattern already
produced the dev-manifest hydration bug that `manifest_matching.py` was
extracted to fix (see its docstring for that story) -- `prepare_build_config`
now owns the whole pre-esbuild sequence so the two entry points cannot drift
on it again.
"""
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from fymo.broadcast.codegen import emit_broadcast_client
from fymo.build.composition_generator import generate_ssr_tree
from fymo.build.discovery import discover_routes, discover_all_layouts
from fymo.build.entry_generator import write_client_entries
from fymo.build.hygiene import (
    check_directory_hygiene,
    check_lib_directory_warnings,
    check_remote_exposure_hygiene,
    check_storage_required_for_media,
    format_hygiene_error,
    format_remote_exposure_error,
)
from fymo.build.manifest import RemoteModuleAssets
from fymo.remote.codegen import emit_module, emit_runtime
from fymo.remote.discovery import discover_remote_modules
from fymo.remote.mode import RemoteModeConfigError, uses_deprecated_remote_flags
from fymo.utils.colors import Color


class BuildError(RuntimeError):
    """Raised when the build pipeline fails."""


@dataclass(frozen=True)
class BuildConfig:
    """Everything both entry points need before invoking esbuild."""
    routes: list                      # discover_routes result
    all_layouts: list                 # discover_all_layouts result
    has_global_css: bool
    ssr_entries: list                 # [{"name", "entryPath"}] -- composed tree or raw leaf
    client_entries: dict              # {name: str(path)} routes + _layout-* + _global
    remote_assets: dict               # {module: RemoteModuleAssets}


def read_yaml_section(project_root: Path, key: str) -> dict:
    """Read one top-level section of fymo.yml without booting FymoApp.

    Missing file or unparseable YAML both resolve to `{}` rather than
    raising -- this is a best-effort read used only to thread config (e.g.
    `auth:`, `remote:`) into build-time discovery, not the runtime config
    loader (see `fymo.core.config.ConfigManager` for that).
    """
    fymo_yml = project_root / "fymo.yml"
    if not fymo_yml.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(fymo_yml.read_text()) or {}
    except Exception:
        return {}
    return data.get(key) or {}


def prepare_build_config(project_root: Path, dist_dir: Path, cache_dir: Path, dev: bool) -> BuildConfig:
    """Run the full pre-esbuild sequence shared by `fymo build` and `fymo dev`.

    Raises `BuildError` for hygiene violations, a missing `node` executable,
    or remote-module discovery failures (`fymo build` only -- see the note
    on the ValueError handling below).

    Two intentional, pre-existing behavior differences between the callers
    are preserved here rather than unified, per this extraction's zero
    behavior-change mandate:

    - The "node not found" message text differs by caller ("node executable
      not found on PATH" for `fymo build`, "node not found on PATH" for
      `fymo dev`) -- neither caller's tests pin the exact wording, but this
      keeps both byte-for-byte identical to before the extraction.
    - `fymo build` fails fast with a BuildError when route discovery finds
      zero routes; `fymo dev` never had that check and silently proceeds.
      Likewise, `fymo build` catches `ValueError` from
      `discover_remote_modules` (raised for untyped remote-function
      parameters) and re-raises it as a clean `BuildError`; `fymo dev` has
      never caught it and lets it propagate raw. Both gaps are pre-existing
      in `fymo dev` (not introduced by this extraction) and are gated on
      `dev` here so behavior doesn't change.
    """
    # Pure filesystem check, no external dependency -- runs before the node
    # check so a misplaced file is reported even in an environment where
    # node isn't installed at all, rather than being masked by a "node
    # executable not found" error that doesn't mention the more fundamental
    # structural issue. Same ordering for both `fymo build` and `fymo dev`.
    hygiene_violations = check_directory_hygiene(project_root)
    if hygiene_violations:
        raise BuildError(format_hygiene_error(hygiene_violations))

    # Soft check, same point in the sequence as the hard one above but never
    # raises; see check_lib_directory_warnings' docstring for why app/lib/
    # doesn't get the hard-error treatment. Printed for both `fymo build` and
    # `fymo dev` since both call prepare_build_config.
    for warning in check_lib_directory_warnings(project_root):
        Color.print_warning(warning)

    # Read once, reused below for discover_remote_modules too: both need the
    # same `remote:` section, and re-reading fymo.yml a second time would
    # risk the two calls drifting if the file changes mid-build.
    remote_config = read_yaml_section(project_root, "remote")

    # remote.explicit_optin / remote.allow_implicit still work for one
    # deprecation cycle but are superseded by remote.mode; nudge toward the
    # new key without failing the build over it.
    if uses_deprecated_remote_flags(remote_config):
        Color.print_warning(
            "remote.explicit_optin and remote.allow_implicit are deprecated. "
            "Use remote.mode: strict or remote.mode: implicit-legacy instead."
        )

    # Also a pure-Python check (imports app/remote/*.py but does not touch
    # node/esbuild), so it runs alongside directory hygiene rather than
    # waiting on the node check below: a developer shipping an unguarded
    # endpoint should hear about it even on a machine without node installed.
    try:
        remote_exposure_violations = check_remote_exposure_hygiene(project_root, remote_config)
    except RemoteModeConfigError as e:
        raise BuildError(str(e))
    if remote_exposure_violations:
        raise BuildError(format_remote_exposure_error(remote_exposure_violations))

    storage_violations = check_storage_required_for_media(project_root)
    if storage_violations:
        raise BuildError("\n".join(storage_violations))

    if shutil.which("node") is None:
        raise BuildError("node not found on PATH" if dev else "node executable not found on PATH")

    templates_dir = project_root / "app" / "templates"
    routes = discover_routes(templates_dir)
    if not routes and not dev:
        raise BuildError(f"no routes found under {templates_dir}")

    client_entry_paths = write_client_entries(routes, cache_dir, project_root, dev=dev)

    all_layouts = discover_all_layouts(templates_dir)
    layout_client_entries = {
        f"_layout-{ref.id}": ref.svelte_path for ref in all_layouts
    }

    global_css_path = templates_dir / "_global.css"
    has_global_css = global_css_path.is_file()
    global_css_entry = {"_global": global_css_path} if has_global_css else {}

    # SSR entry points: composed tree file when a route has a layout chain,
    # else the raw leaf (unchanged behavior).
    ssr_entries = []
    for r in routes:
        tree_path = generate_ssr_tree(r, cache_dir)
        ssr_entries.append({"name": r.name, "entryPath": str(tree_path or r.entry_path)})

    # Codegen for app/remote/*.py -- produces dist/client/_remote/<name>.{js,d.ts}
    remote_out = dist_dir / "client" / "_remote"
    project_root_str = str(project_root)
    _added = project_root_str not in sys.path
    if _added:
        sys.path.insert(0, project_root_str)
    try:
        # When auth is enabled, the active providers' remote functions (e.g.
        # password's signup/login/logout/me under `auth`) ship as part of the
        # normal manifest -- discovered from the providers, not hardcoded.
        remote_modules = discover_remote_modules(
            project_root,
            auth_config=read_yaml_section(project_root, "auth"),
            remote_config=remote_config,
        )
    except ValueError as e:
        if dev:
            raise
        raise BuildError(f"remote module discovery failed: {e}")
    finally:
        if _added and project_root_str in sys.path:
            sys.path.remove(project_root_str)

    if remote_modules:
        emit_runtime(remote_out)
        for module_name, fns in remote_modules.items():
            # A module can now discover to zero functions, e.g. under
            # explicit_optin with every function in the file left unmarked,
            # a private-helpers-only module. emit_module indexes fns.values()
            # for the shared module_hash, which is undefined with nothing in
            # it, so skip rather than emit a pointless empty client module.
            if not fns:
                continue
            emit_module(module_name, fns, remote_out)

    # Codegen for app/broadcasts/*.py -- dist/client/_broadcast/<name>.{js,d.ts}
    emit_broadcast_client(project_root, dist_dir)

    remote_assets: dict[str, RemoteModuleAssets] = {}
    for module_name, fns in remote_modules.items():
        if not fns:
            continue
        any_fn = next(iter(fns.values()))
        remote_assets[module_name] = RemoteModuleAssets(
            hash=any_fn.module_hash,
            fns=sorted(fns.keys()),
        )

    client_entries = {
        **{name: str(path) for name, path in client_entry_paths.items()},
        **{name: str(path) for name, path in layout_client_entries.items()},
        **{name: str(path) for name, path in global_css_entry.items()},
    }

    return BuildConfig(
        routes=routes,
        all_layouts=all_layouts,
        has_global_css=has_global_css,
        ssr_entries=ssr_entries,
        client_entries=client_entries,
        remote_assets=remote_assets,
    )
