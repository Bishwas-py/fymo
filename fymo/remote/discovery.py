"""Discover and introspect functions in app/remote/*.py."""
import hashlib
import importlib
import inspect
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


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


def discover_remote_modules(project_root: Path) -> dict[str, dict[str, RemoteFunction]]:
    """Walk app/remote/*.py and return {module_name: {fn_name: RemoteFunction}}.

    Modules and functions starting with underscore are excluded (private).
    Each non-private function MUST have type-annotated parameters; the
    function discovery raises ValueError if any parameter is untyped.
    """
    remote_dir = project_root / "app" / "remote"
    if not remote_dir.is_dir():
        return {}

    _ensure_parent_packages(project_root)

    out: dict[str, dict[str, RemoteFunction]] = {}
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

        fns: dict[str, RemoteFunction] = {}
        for name, obj in vars(mod).items():
            if name.startswith("_"):
                continue
            # Only plain functions defined in this module (not classes or imports)
            if not inspect.isfunction(obj):
                continue
            if getattr(obj, "__module__", None) != full:
                continue
            sig = inspect.signature(obj)
            try:
                hints = typing.get_type_hints(obj, include_extras=True)
            except Exception as e:
                raise ValueError(
                    f"app/remote/{module_name}.py: cannot resolve type hints for "
                    f"{name!r}: {e}"
                )
            for pname in sig.parameters:
                if pname not in hints:
                    raise ValueError(
                        f"app/remote/{module_name}.py: please annotate parameter "
                        f"{pname!r} of function {name!r}"
                    )
            fns[name] = RemoteFunction(
                module=module_name, name=name, fn=obj, signature=sig, hints=hints,
                module_hash=mod_hash,
            )
        out[module_name] = fns
    return out
