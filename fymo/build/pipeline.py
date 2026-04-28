"""Python orchestrator for the Node-side build script."""
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fymo.build.discovery import discover_routes
from fymo.build.entry_generator import write_client_entries
from fymo.build.manifest import Manifest, RouteAssets, RemoteModuleAssets
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
        if shutil.which("node") is None:
            raise BuildError("node executable not found on PATH")

        templates_dir = self.project_root / "app" / "templates"
        routes = discover_routes(templates_dir)
        if not routes:
            raise BuildError(f"no routes found under {templates_dir}")

        client_entry_paths = write_client_entries(routes, self.cache_dir, self.project_root, dev=dev)

        # Codegen for app/remote/*.py — produces dist/client/_remote/<name>.{js,d.ts}
        remote_out = self.dist_dir / "client" / "_remote"
        project_root_str = str(self.project_root)
        import sys as _sys
        _added = project_root_str not in _sys.path
        if _added:
            _sys.path.insert(0, project_root_str)
        try:
            remote_modules = discover_remote_modules(self.project_root)
        except ValueError as e:
            raise BuildError(f"remote module discovery failed: {e}")
        finally:
            if _added and project_root_str in _sys.path:
                _sys.path.remove(project_root_str)
        if remote_modules:
            emit_runtime(remote_out)
            for module_name, fns in remote_modules.items():
                emit_module(module_name, fns, remote_out)

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
            "routes": [
                {"name": r.name, "entryPath": str(r.entry_path)} for r in routes
            ],
            "clientEntries": {
                name: str(path) for name, path in client_entry_paths.items()
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

        manifest = self._build_manifest(routes, result, remote_assets)
        manifest.write(self.dist_dir / "manifest.json")
        return BuildResult(ok=True, manifest_path=self.dist_dir / "manifest.json")

    def _build_manifest(self, routes, esbuild_result, remote_assets: dict | None = None) -> Manifest:
        # Resolve hashed client filenames from the metafile.
        client_meta = esbuild_result.get("client", {}).get("outputs", {})
        # esbuild metafile keys are relative to the project root (its cwd).
        # Compute absolute path via project_root, then make relative to dist_dir.
        dist_dir_abs = self.dist_dir.resolve()
        project_root_abs = self.project_root.resolve()

        def abs_out(out_path: str) -> Path:
            """Resolve an esbuild output path (relative to project root) to absolute."""
            p = Path(out_path)
            if p.is_absolute():
                return p
            return (project_root_abs / p).resolve()

        client_by_route = {}
        css_by_route = {}
        for out_path, info in client_meta.items():
            entry_point = info.get("entryPoint")
            if entry_point is None:
                continue
            abs_path = abs_out(out_path)
            try:
                rel_to_dist = abs_path.relative_to(dist_dir_abs)
            except ValueError:
                continue
            for r in routes:
                if Path(entry_point).name == f"{r.name}.client.js":
                    if str(rel_to_dist).endswith(".js"):
                        client_by_route[r.name] = str(rel_to_dist).replace("\\", "/")
                        css_bundle = info.get("cssBundle")
                        if css_bundle:
                            try:
                                css_rel = abs_out(css_bundle).relative_to(dist_dir_abs)
                                css_by_route[r.name] = str(css_rel).replace("\\", "/")
                            except ValueError:
                                pass

        # Preload chunks: any output whose path starts with client/chunk-
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
            )

        return Manifest(
            routes=route_assets,
            build_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            remote_modules=remote_assets or {},
        )
