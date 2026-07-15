"""Discover and introspect functions in app/remote/*.py."""
import hashlib
import importlib
import inspect
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fymo.remote.mode import resolve_remote_mode


def file_hash(path: Path) -> str:
    """Return a 12-char lowercase hex SHA-256 prefix of the file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


@dataclass(frozen=True)
class RemoteFunction:
    """A top-level callable from app/remote/<module>.py."""
    module: str
    name: str
    fn: Callable[..., Any]
    signature: inspect.Signature
    hints: dict[str, Any]  # includes 'return' if annotated
    module_hash: str


def _ensure_parent_packages(project_root: Path) -> None:
    """Ensure app and app.remote packages are imported from the given project_root.

    If stale cached entries exist (pointing to a different root), evict and
    re-import them so that subsequent import_module("app.remote.<x>") resolves
    correctly.
    """
    import sys as _sys

    for pkg in ("app", "app.remote"):
        cached = _sys.modules.get(pkg)
        if cached is not None:
            # Check whether the cached package file lives under project_root.
            spec = getattr(cached, "__spec__", None)
            origin = getattr(spec, "origin", None) if spec else None
            if origin is None:
                # No origin — evict and re-import.
                del _sys.modules[pkg]
            else:
                pkg_path = Path(origin).resolve()
                try:
                    pkg_path.relative_to(project_root.resolve())
                except ValueError:
                    # Origin is outside project_root — stale cache, evict.
                    del _sys.modules[pkg]
        if pkg not in _sys.modules:
            importlib.import_module(pkg)


def discover_remote_modules(
    project_root: Path,
    *,
    auth_config: "dict | None" = None,
    remote_config: "dict | None" = None,
) -> dict[str, dict[str, RemoteFunction]]:
    """Walk app/remote/*.py and return {module_name: {fn_name: RemoteFunction}}.

    Modules and functions starting with underscore are excluded (private).
    Each non-private function MUST have type-annotated parameters; the
    function discovery raises ValueError if any parameter is untyped.

    When `auth_config` has `enabled: true`, the active auth providers'
    remote functions are added too (e.g. password's under `auth`), discovered
    from the providers rather than any hardcoded module.

    `remote_config` holds the `remote:` section of fymo.yml, resolved through
    `fymo.remote.mode.resolve_remote_mode`. Under `remote.mode: strict` (or
    the deprecated `explicit_optin: true`), only app-module functions
    decorated with `@remote` (fymo.remote.decorators.remote, which stamps
    `__fymo_remote__ = True`) are discovered — everything else in
    app/remote/*.py is treated as a private helper. Default is implicit
    (every public typed function is discovered, today's back-compat
    behavior). This only applies to app modules; provider/system remote
    functions (below) always ship regardless of the mode.
    """
    out: dict[str, dict[str, RemoteFunction]] = {}
    explicit_optin = resolve_remote_mode(remote_config).strict

    remote_dir = project_root / "app" / "remote"
    if remote_dir.is_dir():
        _ensure_parent_packages(project_root)

        for py in sorted(remote_dir.glob("*.py")):
            if py.name == "__init__.py" or py.stem.startswith("_"):
                continue
            module_name = py.stem
            mod_hash = file_hash(py)
            full = f"app.remote.{module_name}"
            if full in importlib.sys.modules:
                mod = importlib.reload(importlib.sys.modules[full])
            else:
                mod = importlib.import_module(full)
            out[module_name] = _collect_module_functions(
                mod, module_name=module_name, expected_module=full, mod_hash=mod_hash,
                explicit_optin=explicit_optin,
            )

    if auth_config and auth_config.get("enabled"):
        from fymo.auth.providers.registry import build_providers, system_remote_modules
        providers = build_providers(auth_config.get("providers"))
        for module_name, fns in system_remote_modules(providers).items():
            out[module_name] = _collect_from_callables(
                module_name, fns, mod_hash=_functions_hash(fns),
            )

    return out


def is_exposed_remote_fn(obj, expected_module: str, explicit_optin: bool) -> bool:
    """Single source of truth for 'may this attribute be called remotely':
    it must be a function DEFINED in expected_module (not imported into
    it), and when explicit opt-in is on, carry __fymo_remote__ = True.
    Both discovery (build-time codegen) and the router (runtime dispatch)
    call this — they once implemented it independently and could drift.
    """
    if not inspect.isfunction(obj):
        return False
    if getattr(obj, "__module__", None) != expected_module:
        return False
    if explicit_optin and not getattr(obj, "__fymo_remote__", False):
        return False
    return True


def _collect_module_functions(
    mod, *, module_name: str, expected_module: str, mod_hash: str,
    explicit_optin: bool = False,
) -> dict[str, RemoteFunction]:
    fns: dict[str, RemoteFunction] = {}
    for name, obj in vars(mod).items():
        if name.startswith("_"):
            continue
        if not is_exposed_remote_fn(obj, expected_module, explicit_optin):
            continue
        sig = inspect.signature(obj)
        try:
            hints = typing.get_type_hints(obj, include_extras=True)
        except Exception as e:
            raise ValueError(
                f"{module_name}: cannot resolve type hints for {name!r}: {e}"
            )
        for pname in sig.parameters:
            if pname not in hints:
                raise ValueError(
                    f"{module_name}: please annotate parameter {pname!r} of function {name!r}"
                )
        fns[name] = RemoteFunction(
            module=module_name, name=name, fn=obj, signature=sig, hints=hints,
            module_hash=mod_hash,
        )
    return fns


def _functions_hash(fns: dict[str, Callable]) -> str:
    """Content hash for a set of provider callables: the source files they're
    defined in. Changes when the code changes, so the endpoint URL cache-busts."""
    files = sorted({
        inspect.getsourcefile(fn) for fn in fns.values() if inspect.getsourcefile(fn)
    })
    h = hashlib.sha256()
    for f in files:
        h.update(Path(f).read_bytes())
    return h.hexdigest()[:12]


def _collect_from_callables(
    module_name: str, fns: dict[str, Callable], *, mod_hash: str,
) -> dict[str, RemoteFunction]:
    """Build RemoteFunction entries from an explicit {name: callable} map
    (provider-curated, so no module scanning or __module__ filtering)."""
    out: dict[str, RemoteFunction] = {}
    for name, obj in fns.items():
        sig = inspect.signature(obj)
        hints = typing.get_type_hints(obj, include_extras=True)
        for pname in sig.parameters:
            if pname not in hints:
                raise ValueError(
                    f"{module_name}: please annotate parameter {pname!r} of function {name!r}"
                )
        out[name] = RemoteFunction(
            module=module_name, name=name, fn=obj, signature=sig, hints=hints,
            module_hash=mod_hash,
        )
    return out
