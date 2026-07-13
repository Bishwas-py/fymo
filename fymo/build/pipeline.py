"""Python orchestrator for the Node-side build script."""
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fymo.build.discovery import discover_routes, discover_all_layouts
from fymo.build.entry_generator import write_client_entries
from fymo.build.composition_generator import generate_ssr_tree
from fymo.build.hygiene import check_directory_hygiene, format_hygiene_error
from fymo.build.manifest import Manifest, RouteAssets, RemoteModuleAssets, LayoutRefAsset, LayoutAssets
from fymo.remote.discovery import discover_remote_modules
from fymo.remote.codegen import emit_module, emit_runtime


class BuildError(RuntimeError):
    """Raised when the build pipeline fails."""


@dataclass
class BuildResult:
    ok: bool
    manifest_path: Path


class BuildPipeline:
    """Orchestrates: discover -> generate entries -> invoke esbuild -> write manifest."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.dist_dir = project_root / "dist"
        self.cache_dir = project_root / ".fymo" / "entries"
        self.build_script = Path(__file__).resolve().parent / "js" / "build.mjs"

    def build(self, dev: bool = False) -> BuildResult:
        # Pure filesystem check, no external dependency -- runs before the
        # node check so a misplaced file is reported even in an environment
        # where node isn't installed at all, rather than being masked by a
        # "node executable not found" error that doesn't mention the more
        # fundamental structural issue.
        hygiene_violations = check_directory_hygiene(self.project_root)
        if hygiene_violations:
            raise BuildError(format_hygiene_error(hygiene_violations))

        if shutil.which("node") is None:
            raise BuildError("node executable not found on PATH")

        templates_dir = self.project_root / "app" / "templates"
        routes = discover_routes(templates_dir)
        if not routes:
            raise BuildError(f"no routes found under {templates_dir}")

        client_entry_paths = write_client_entries(routes, self.cache_dir, self.project_root, dev=dev)

        all_layouts = discover_all_layouts(templates_dir)
        layout_client_entries = {
            f"_layout-{ref.id}": ref.svelte_path for ref in all_layouts
        }

        global_css_path = templates_dir / "_global.css"
        global_css_entry = {"_global": global_css_path} if global_css_path.is_file() else {}

        # SSR entry points: composed tree file when a route has a layout
        # chain, else the raw leaf (unchanged behavior).
        ssr_entries = []
        for r in routes:
            tree_path = generate_ssr_tree(r, self.cache_dir)
            ssr_entries.append({"name": r.name, "entryPath": str(tree_path or r.entry_path)})

        # Codegen for app/remote/*.py — produces dist/client/_remote/<name>.{js,d.ts}
        remote_out = self.dist_dir / "client" / "_remote"
        project_root_str = str(self.project_root)
        import sys as _sys
        _added = project_root_str not in _sys.path
        if _added:
            _sys.path.insert(0, project_root_str)
        # When auth is enabled, the active providers' remote functions
        # (e.g. password's signup/login/logout/me under `auth`) ship as part of
        # the normal manifest — discovered from the providers, not hardcoded.
        auth_cfg = self._auth_config()
        remote_cfg = self._remote_config()
        try:
            remote_modules = discover_remote_modules(
                self.project_root, auth_config=auth_cfg, remote_config=remote_cfg,
            )
        except ValueError as e:
            raise BuildError(f"remote module discovery failed: {e}")
        finally:
            if _added and project_root_str in _sys.path:
                _sys.path.remove(project_root_str)
        if remote_modules:
            emit_runtime(remote_out)
            for module_name, fns in remote_modules.items():
                emit_module(module_name, fns, remote_out)

        # Codegen for app/broadcasts/*.py — dist/client/_broadcast/<name>.{js,d.ts}
        from fymo.broadcast.codegen import emit_broadcast_client
        emit_broadcast_client(self.project_root, self.dist_dir)

        remote_assets: dict[str, RemoteModuleAssets] = {}
        for module_name, fns in remote_modules.items():
            if not fns:
                continue
            any_fn = next(iter(fns.values()))
            remote_assets[module_name] = RemoteModuleAssets(
                hash=any_fn.module_hash,
                fns=sorted(fns.keys()),
            )

        config = {
            "projectRoot": str(self.project_root),
            "distDir": str(self.dist_dir),
            "routes": ssr_entries,
            "clientEntries": {
                **{name: str(path) for name, path in client_entry_paths.items()},
                **{name: str(path) for name, path in layout_client_entries.items()},
                **{name: str(path) for name, path in global_css_entry.items()},
            },
            "dev": dev,
        }

        proc = subprocess.run(
            ["node", str(self.build_script), json.dumps(config)],
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0 or not proc.stdout:
            raise BuildError(
                f"esbuild failed (exit {proc.returncode})\n"
                f"stdout: {proc.stdout}\n"
                f"stderr: {proc.stderr}"
            )

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise BuildError(f"build script produced invalid JSON: {e}\nstdout: {proc.stdout[:500]}")

        if not result.get("ok"):
            raise BuildError(f"build failed: {result.get('error')}\n{result.get('stack', '')}")

        manifest = self._build_manifest(routes, result, remote_assets, all_layouts, bool(global_css_entry))
        manifest.write(self.dist_dir / "manifest.json")
        return BuildResult(ok=True, manifest_path=self.dist_dir / "manifest.json")

    def _auth_config(self) -> dict:
        """Read fymo.yml's `auth:` section without booting FymoApp."""
        return self._read_yaml_section("auth")

    def _remote_config(self) -> dict:
        """Read fymo.yml's `remote:` section without booting FymoApp.

        Holds `explicit_optin` — must be threaded to `discover_remote_modules`
        the same way `fymo.core.server.FymoApp` threads it to the router at
        runtime (`_remote_router._explicit_optin`), or discovery and dispatch
        disagree on what's exposed.
        """
        return self._read_yaml_section("remote")

    def _read_yaml_section(self, key: str) -> dict:
        fymo_yml = self.project_root / "fymo.yml"
        if not fymo_yml.is_file():
            return {}
        try:
            import yaml
            data = yaml.safe_load(fymo_yml.read_text()) or {}
        except Exception:
            return {}
        return data.get(key) or {}

    def _build_manifest(
        self, routes, esbuild_result, remote_assets: dict | None = None,
        all_layouts=None, has_global_css: bool = False,
    ) -> Manifest:
        all_layouts = all_layouts or []
        client_meta = esbuild_result.get("client", {}).get("outputs", {})
        dist_dir_abs = self.dist_dir.resolve()
        project_root_abs = self.project_root.resolve()

        def abs_out(out_path: str) -> Path:
            p = Path(out_path)
            if p.is_absolute():
                return p
            return (project_root_abs / p).resolve()

        client_by_route = {}
        css_by_route = {}
        layout_client = {}
        layout_css = {}
        global_css_out = None
        for out_path, info in client_meta.items():
            entry_point = info.get("entryPoint")
            if entry_point is None:
                continue
            abs_path = abs_out(out_path)
            try:
                rel_to_dist = abs_path.relative_to(dist_dir_abs)
            except ValueError:
                continue
            entry_name = Path(entry_point).name
            if not str(rel_to_dist).endswith(".js") and not str(rel_to_dist).endswith(".css"):
                continue

            matched_route = next((r for r in routes if entry_name == f"{r.name}.client.js"), None)
            if matched_route is not None:
                client_by_route[matched_route.name] = str(rel_to_dist).replace("\\", "/")
                css_bundle = info.get("cssBundle")
                if css_bundle:
                    try:
                        css_rel = abs_out(css_bundle).relative_to(dist_dir_abs)
                        css_by_route[matched_route.name] = str(css_rel).replace("\\", "/")
                    except ValueError:
                        pass
                continue

            # Layout entries are keyed in clientEntries as "_layout-<id>" but
            # their source file is the raw _layout.svelte (no per-route stub
            # like routes get from entry_generator.py), so esbuild's metafile
            # `entryPoint` is the .svelte source path -- its basename never
            # matches "_layout-<id>.js". `ref.id` is an unsanitized directory
            # name (see discovery.py), so it can itself contain "." -- e.g.
            # resource dirs "a" and "a.b" both -- which would make a
            # string-prefix match on the hashed output filename ambiguous
            # (out_name.startswith(f"_layout-{ref.id}.")). Match by path
            # identity instead: resolve entry_point the same way abs_out()
            # resolves other paths here, and compare it to ref.svelte_path,
            # mirroring the route branch's identity match on entry_name.
            if not str(rel_to_dist).endswith(".js"):
                matched_layout = None
            else:
                entry_point_abs = abs_out(entry_point)
                matched_layout = next(
                    (ref for ref in all_layouts if entry_point_abs == ref.svelte_path.resolve()),
                    None,
                )
            if matched_layout is not None:
                layout_client[matched_layout.id] = str(rel_to_dist).replace("\\", "/")
                css_bundle = info.get("cssBundle")
                if css_bundle:
                    try:
                        css_rel = abs_out(css_bundle).relative_to(dist_dir_abs)
                        layout_css[matched_layout.id] = str(css_rel).replace("\\", "/")
                    except ValueError:
                        pass
                continue

            if has_global_css and entry_name == "_global.css" and str(rel_to_dist).endswith(".css"):
                global_css_out = str(rel_to_dist).replace("\\", "/")

        chunks = []
        for p in client_meta:
            if Path(p).name.startswith("chunk-") and p.endswith(".js"):
                try:
                    rel = abs_out(p).relative_to(dist_dir_abs)
                    chunks.append(str(rel).replace("\\", "/"))
                except ValueError:
                    pass

        route_assets = {}
        for r in routes:
            if r.name not in client_by_route:
                raise BuildError(f"esbuild produced no client output for route '{r.name}'")
            route_assets[r.name] = RouteAssets(
                ssr=f"ssr/{r.name}.mjs",
                client=client_by_route[r.name],
                css=css_by_route.get(r.name),
                preload=chunks,
                layout_chain=[
                    LayoutRefAsset(level=ref.level, id=ref.id, controller_module=ref.controller_module)
                    for ref in r.layout_chain
                ],
                uses_layout_shell=bool(r.layout_chain),
            )

        for ref in all_layouts:
            if ref.id not in layout_client:
                raise BuildError(f"esbuild produced no client output for layout '{ref.id}'")

        layouts_assets = {
            ref.id: LayoutAssets(client=layout_client[ref.id], css=layout_css.get(ref.id))
            for ref in all_layouts
        }

        return Manifest(
            routes=route_assets,
            build_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            remote_modules=remote_assets or {},
            layouts=layouts_assets,
            global_css=global_css_out,
        )
