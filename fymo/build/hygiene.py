"""Directory-hygiene validation, shared by `fymo build` and `fymo dev`.

app/controllers/ is Python-only; app/templates/ and app/components/ are
frontend-only (.svelte/.ts). A misplaced file doesn't actually break
anything mechanically -- Python's controller loader never tries to import
a stray .svelte file, and esbuild never bundles a stray .py file sitting
in a template/component directory -- which is exactly what makes it easy
to miss without an explicit check: the file just silently does nothing,
instead of erroring where a developer would notice.
"""
import importlib
import sys
from pathlib import Path
from typing import List

_FRONTEND_ONLY_DIRS = ("templates", "components")


def check_directory_hygiene(project_root: Path) -> List[str]:
    """Return a list of human-readable violation messages (empty if none)."""
    violations: List[str] = []

    controllers_dir = project_root / "app" / "controllers"
    if controllers_dir.is_dir():
        for f in sorted(controllers_dir.rglob("*.svelte")):
            violations.append(
                f"{f.relative_to(project_root)}: .svelte file inside app/controllers/ "
                f"(Python-only -- move it to app/templates/ or app/components/)"
            )

    for dir_name in _FRONTEND_ONLY_DIRS:
        frontend_dir = project_root / "app" / dir_name
        if frontend_dir.is_dir():
            for f in sorted(frontend_dir.rglob("*.py")):
                violations.append(
                    f"{f.relative_to(project_root)}: .py file inside app/{dir_name}/ "
                    f"(frontend-only -- move it to app/controllers/, app/remote/, or app/lib/)"
                )

    return violations


def format_hygiene_error(violations: List[str]) -> str:
    bullet_list = "\n".join(f"  - {v}" for v in violations)
    return (
        "Directory hygiene violation(s) found:\n" + bullet_list +
        "\n\napp/controllers/ is Python-only; app/templates/ and app/components/ "
        "are frontend-only."
    )


# app/lib soft check.
#
# Deliberately separate from check_directory_hygiene()/format_hygiene_error()
# above: those are hard build failures, this is not. app/lib/ is the
# $lib/* tsconfig alias target, TypeScript/Svelte-only by convention, but a
# stray .py file there doesn't mechanically break the build the way a
# misplaced .svelte/.py does elsewhere (esbuild simply never touches it), so
# there's no reason to block the build over it. It's still worth flagging:
# app/support/ is the intended home for that code, and a .py file sitting
# unreachable in app/lib/ is easy to miss otherwise.

def check_lib_directory_warnings(project_root: Path) -> List[str]:
    """Return a list of human-readable warning messages for .py files found
    under app/lib/ (empty if none). Never raises and never fails a build;
    callers are expected to print these and continue."""
    warnings: List[str] = []

    lib_dir = project_root / "app" / "lib"
    if lib_dir.is_dir():
        for f in sorted(lib_dir.rglob("*.py")):
            warnings.append(
                f"{f.relative_to(project_root)}: .py file inside app/lib/ "
                f"(app/lib/ is TypeScript/Svelte-only, consider moving it to app/support/)"
            )

    return warnings


def check_remote_exposure_hygiene(project_root: Path, remote_config: "dict | None") -> List[str]:
    """Return one violation per app/remote/*.py function that implicit-mode
    discovery would expose to the browser but that carries no `@remote`
    marker (issue #8: file placement alone used to be the only thing
    deciding browser-callability, and a real app got that wrong: an
    internal storage helper landed in app/remote/ with no auth guard and
    turned out to be reachable over the wire).

    A no-op (returns []) when `remote.explicit_optin` is true, since in that
    mode an unmarked function is already excluded from the manifest and
    the router by `discovery.is_exposed_remote_fn`, so there's nothing
    silently exposed to warn about. Also a no-op when `remote.allow_implicit`
    is true, the documented-unsafe escape hatch for apps that aren't ready
    to migrate yet.

    Imports every app/remote/*.py module to apply the exact same exposure
    rule discovery uses at codegen time (`is_exposed_remote_fn` with
    explicit_optin=False, i.e. "what would ship if opt-in were off"), so
    this can never drift from what the manifest/router actually expose.
    """
    remote_config = remote_config or {}
    if remote_config.get("explicit_optin", False):
        return []
    if remote_config.get("allow_implicit", False):
        return []

    remote_dir = project_root / "app" / "remote"
    if not remote_dir.is_dir():
        return []

    from fymo.remote.discovery import _ensure_parent_packages, is_exposed_remote_fn

    violations: List[str] = []
    project_root_str = str(project_root)
    added = project_root_str not in sys.path
    if added:
        sys.path.insert(0, project_root_str)
    try:
        _ensure_parent_packages(project_root)
        for py in sorted(remote_dir.glob("*.py")):
            if py.name == "__init__.py" or py.stem.startswith("_"):
                continue
            module_name = py.stem
            full = f"app.remote.{module_name}"
            if full in sys.modules:
                mod = importlib.reload(sys.modules[full])
            else:
                mod = importlib.import_module(full)
            for name, obj in vars(mod).items():
                if name.startswith("_"):
                    continue
                # explicit_optin=False here on purpose: this asks "would
                # implicit mode expose this", not "is it exposed right now".
                if not is_exposed_remote_fn(obj, full, explicit_optin=False):
                    continue
                if getattr(obj, "__fymo_remote__", False):
                    continue
                violations.append(
                    f"{py.relative_to(project_root)}: {name} is browser-callable "
                    f"under implicit mode but has no @remote marker "
                    f"(add @remote or rename it with a leading underscore to keep it private)"
                )
    finally:
        if added and project_root_str in sys.path:
            sys.path.remove(project_root_str)

    return violations


def format_remote_exposure_error(violations: List[str]) -> str:
    bullet_list = "\n".join(f"  - {v}" for v in violations)
    return (
        "Unmarked remote function(s) would be exposed under implicit mode:\n" + bullet_list +
        "\n\nEvery public function in app/remote/*.py is browser-callable by default "
        "when remote.explicit_optin is false. Add @remote (from fymo.remote) to each "
        "function above that's meant to be an endpoint, or rename it with a leading "
        "underscore to keep it a private helper. To silence this check without fixing "
        "it (unsafe, temporary), set remote.allow_implicit: true in fymo.yml."
    )
