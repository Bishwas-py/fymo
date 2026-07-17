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


def _read_fymo_yml(project_root: Path) -> dict:
    """Best-effort raw read of the whole fymo.yml, same posture as
    prepare.read_yaml_section (missing file or unparseable YAML resolve to
    `{}`), but returning the full mapping: check_media_key_removed below
    needs key *presence*, and read_yaml_section's `or {}` normalization
    can't tell `media: []` apart from no `media:` key at all."""
    fymo_yml = project_root / "fymo.yml"
    if not fymo_yml.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(fymo_yml.read_text()) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def check_media_key_removed(project_root: Path) -> List[str]:
    """Top-level `media:` was folded into `storage.expose` (issue #76), hard
    break with no shim. A config still carrying the old key must fail
    `fymo build`/`fymo dev` with the migration text, mirroring the boot-time
    refusal in fymo.core.config.ConfigManager, never be silently ignored."""
    from fymo.core.config import MEDIA_KEY_REMOVED_ERROR

    if "media" in _read_fymo_yml(project_root):
        return [MEDIA_KEY_REMOVED_ERROR]
    return []


def check_storage_required_for_expose(project_root: Path) -> List[str]:
    """`storage.expose` entries always resolve the files they serve through
    a StorageProvider (fymo.storage.registry), and storage has no default
    provider on purpose (see fymo/storage/registry.py's docstring):
    silently writing to local disk is exactly the footgun that works in
    dev and quietly loses data behind a load balancer in production. So
    expose entries with no provider selected would only fail once
    FymoApp.__init__ runs; catching it here at build time points at the
    fix (set storage.provider) before that happens."""
    from fymo.build.prepare import read_yaml_section
    from fymo.core.expose import EXPOSE_WITHOUT_PROVIDER_ERROR

    storage_config = read_yaml_section(project_root, "storage")
    if (
        isinstance(storage_config, dict)
        and (storage_config.get("expose") or [])
        and not any(key in storage_config for key in ("provider", "type", "class"))
    ):
        return [EXPOSE_WITHOUT_PROVIDER_ERROR]
    return []


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

    A no-op (returns []) whenever `fymo.remote.mode.resolve_remote_mode`
    resolves `hygiene_enforced=False` for the given config: that covers
    `remote.mode: strict` (an unmarked function is already excluded from the
    manifest and the router by `discovery.is_exposed_remote_fn`, so there's
    nothing silently exposed to warn about), `remote.mode: implicit-legacy`,
    and the deprecated `explicit_optin`/`allow_implicit` spellings of both.

    Lets `RemoteModeConfigError` propagate uncaught (an invalid `mode:`
    value, or `mode:` combined with a deprecated key) so the caller
    (`fymo/build/prepare.py`) can surface it as a distinct `BuildError`
    rather than folding it into "found unmarked functions".

    Imports every app/remote/*.py module to apply the exact same exposure
    rule discovery uses at codegen time (`is_exposed_remote_fn` with
    explicit_optin=False, i.e. "what would ship if opt-in were off"), so
    this can never drift from what the manifest/router actually expose.
    """
    from fymo.remote.mode import resolve_remote_mode

    if not resolve_remote_mode(remote_config).hygiene_enforced:
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
        "it (unsafe, temporary), set remote.mode: implicit-legacy in fymo.yml."
    )


def check_auth_enforcement_hygiene(project_root: Path, auth_config: "dict | None") -> List[str]:
    """Return one violation per app/remote/*.py function decorated with
    @require_auth for which nobody could ever actually authenticate (issue
    #29). require_auth itself fails closed correctly: no session means 401,
    every time, regardless of why there's no session. The gap is upstream of
    that. Nothing stops an app from shipping @require_auth while auth.enabled
    is false, or while every configured provider has declined via
    `required: auto` (its is_configured() classmethod returned False, see
    fymo/auth/providers/base.py). Either way, the endpoint can never
    authenticate anyone, and a real app was found papering over exactly
    that: a hand-rolled wrapper that treated "auth isn't configured" as
    "must be local dev" and quietly skipped the check instead.

    Note this only catches providers that actually implement is_configured()
    (custom providers are the common case today, see docs/deployment.md's
    `required: auto` section). BaseProvider.is_configured() defaults to
    True, and none of the built-in google/oidc/clerk providers override it
    yet, so a built-in provider with a missing client-id/secret env var
    still constructs (with blank credentials) and counts as active here,
    even though it can't actually authenticate anyone at runtime. That gap
    lives in the providers themselves, not this check.

    Scans for the __fymo_require_auth__ marker fymo.auth.context.require_auth
    stamps on its wrapper, the same way check_remote_exposure_hygiene scans
    for __fymo_remote__. Returns [] immediately when nothing is marked, so
    apps that don't use @require_auth pay no cost and see no noise regardless
    of their auth config.
    """
    remote_dir = project_root / "app" / "remote"
    if not remote_dir.is_dir():
        return []

    from fymo.remote.discovery import _ensure_parent_packages

    guarded_sites: List[str] = []
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
                if getattr(obj, "__fymo_require_auth__", False):
                    guarded_sites.append(f"{py.relative_to(project_root)}: {name}")
    finally:
        if added and project_root_str in sys.path:
            sys.path.remove(project_root_str)

    if not guarded_sites:
        return []

    auth_config = auth_config or {}
    if not auth_config.get("enabled"):
        return [f"{site} is decorated with @require_auth but auth.enabled is not true in fymo.yml"
                for site in guarded_sites]

    from fymo.auth.providers.registry import build_providers

    providers = build_providers(auth_config.get("providers"))
    if not providers:
        return [
            f"{site} is decorated with @require_auth but auth.providers resolves to "
            "zero active providers (every entry with required: auto declined)"
            for site in guarded_sites
        ]

    return []


def _collect_require_auth_routes(routes_config: dict) -> "List[tuple]":
    """Return [(route_label, require_auth_value)] for every route in the raw
    fymo.yml `routes:` mapping that carries require_auth. The route named
    `signin` is excluded: it is auto-public (the redirect target), so its
    require_auth is ignored at boot and must not demand enforcement here."""
    entries: List[tuple] = []
    root_spec = routes_config.get("root")
    if isinstance(root_spec, dict) and root_spec.get("require_auth"):
        entries.append(("root", root_spec["require_auth"]))
    for entry in routes_config.get("resources") or []:
        if isinstance(entry, dict) and entry.get("require_auth"):
            name = entry.get("name")
            if name != "signin":
                entries.append((name or "<unnamed resource>", entry["require_auth"]))
    for key, value in routes_config.items():
        if key in ("root", "resources"):
            continue
        if isinstance(value, dict) and value.get("require_auth"):
            if key.lstrip("/") != "signin":
                entries.append((key, value["require_auth"]))
    return entries


def check_page_auth_hygiene(project_root: Path) -> List[str]:
    """Return violations for route-level require_auth that could never be
    enforced at request time (issue #80 phase 2): a route carries
    require_auth but app/auth/ registers no @identify resolver, or a
    dotted-path guard cannot be imported.

    Deliberately NOT dev-lenient, unlike check_auth_enforcement_hygiene.
    That check tolerates dev because @require_auth decorators typically land
    in code before the auth config exists (mid-setup is the normal dev
    state). Route-level require_auth is the opposite direction: it is added
    to fymo.yml deliberately, after auth exists, and with no resolver every
    protected page becomes an unconditional redirect to a signin page that
    can never establish an identity, a mysterious redirect loop in the
    browser. Failing `fymo dev` loudly with the fix beats debugging that.
    Mid-setup apps simply do not set require_auth yet.

    Imports app/auth/*.py the same way check_remote_exposure_hygiene imports
    app/remote/*.py, then inspects the identify registry through its public
    accessor. Only resolvers whose defining file lives under project_root
    count: the registry is process-global and another project loaded earlier
    in the same process must not satisfy this project's check.
    """
    from fymo.build.prepare import read_yaml_section

    routes_config = read_yaml_section(project_root, "routes")
    if not isinstance(routes_config, dict):
        return []
    protected = _collect_require_auth_routes(routes_config)
    if not protected:
        return []

    violations: List[str] = []

    from fymo.auth.discovery import import_auth_modules
    from fymo.auth.identity import registered_identity_resolvers

    import_auth_modules(project_root)
    root = Path(project_root).resolve()

    def _defined_under_root(fn) -> bool:
        code = getattr(fn, "__code__", None)
        if code is None:
            return False
        try:
            Path(code.co_filename).resolve().relative_to(root)
        except (ValueError, OSError):
            return False
        return True

    if not any(_defined_under_root(fn) for fn in registered_identity_resolvers()):
        route_list = ", ".join(sorted({label for label, _ in protected}))
        violations.append(
            f"route(s) {route_list} set require_auth but app/auth/ registers "
            "no @identify resolver, so no request can ever resolve an identity "
            "and every visit redirects to signin forever. Add a resolver "
            "(a function decorated with @identify from fymo.auth, returning "
            "fymo.auth.Identity(uid=...) or None) in an app/auth/*.py module, "
            "or remove require_auth from the route(s)."
        )

    project_root_str = str(project_root)
    added = project_root_str not in sys.path
    if added:
        sys.path.insert(0, project_root_str)
    try:
        from fymo.core.page_auth import resolve_guard
        for label, value in protected:
            if not isinstance(value, str):
                continue
            try:
                resolve_guard(value)
            except Exception as e:
                violations.append(
                    f"route {label!r}: require_auth guard {value!r} cannot be "
                    f"imported: {e} (fix the dotted path or define the guard, "
                    "e.g. app.auth.guards.require_admin)"
                )
    finally:
        if added and project_root_str in sys.path:
            sys.path.remove(project_root_str)

    return violations


def format_page_auth_error(violations: List[str]) -> str:
    bullet_list = "\n".join(f"  - {v}" for v in violations)
    return (
        "Unenforceable route-level require_auth found:\n" + bullet_list +
        "\n\nrequire_auth in fymo.yml is enforced through the @identify "
        "resolver chain in app/auth/. Every value must be `true` or an "
        "importable dotted guard path, and at least one resolver must exist."
    )


def format_auth_enforcement_error(violations: List[str]) -> str:
    bullet_list = "\n".join(f"  - {v}" for v in violations)
    return (
        "@require_auth site(s) that nobody can ever authenticate against:\n" + bullet_list +
        "\n\nWith auth off or zero active providers, these endpoints either stay "
        "permanently unreachable or (more dangerously) invite app code to route "
        "around @require_auth instead of fixing the underlying config. Enable "
        "auth.enabled and configure at least one provider in fymo.yml, or remove "
        "@require_auth from the function(s) above if the guard is no longer needed."
    )
