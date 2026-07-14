"""Python orchestrator for the Node-side build script."""
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from fymo.build.manifest import Manifest
from fymo.build.manifest_matching import match_esbuild_outputs
from fymo.build.prepare import BuildError, prepare_build_config


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
        build_config = prepare_build_config(self.project_root, self.dist_dir, self.cache_dir, dev)
        routes = build_config.routes
        all_layouts = build_config.all_layouts
        remote_assets = build_config.remote_assets

        esbuild_config = {
            "projectRoot": str(self.project_root),
            "distDir": str(self.dist_dir),
            "routes": build_config.ssr_entries,
            "clientEntries": build_config.client_entries,
            "dev": dev,
        }

        proc = subprocess.run(
            ["node", str(self.build_script), json.dumps(esbuild_config)],
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

        manifest = self._build_manifest(routes, result, remote_assets, all_layouts, build_config.has_global_css)
        manifest.write(self.dist_dir / "manifest.json")
        return BuildResult(ok=True, manifest_path=self.dist_dir / "manifest.json")

    def _build_manifest(
        self, routes, esbuild_result, remote_assets: dict | None = None,
        all_layouts=None, has_global_css: bool = False,
    ) -> Manifest:
        all_layouts = all_layouts or []
        client_meta = esbuild_result.get("client", {}).get("outputs", {})

        route_assets, layouts_assets, global_css_out = match_esbuild_outputs(
            client_outputs=client_meta,
            routes=routes,
            all_layouts=all_layouts,
            project_root=self.project_root,
            dist_dir=self.dist_dir,
            has_global_css=has_global_css,
        )

        # fymo build is strict: any route or layout esbuild didn't produce
        # output for is a hard failure, not a silent omission (unlike
        # fymo dev, which tolerates this transiently mid-rebuild).
        for r in routes:
            if r.name not in route_assets:
                raise BuildError(f"esbuild produced no client output for route '{r.name}'")
        for ref in all_layouts:
            if ref.id not in layouts_assets:
                raise BuildError(f"esbuild produced no client output for layout '{ref.id}'")

        return Manifest(
            routes=route_assets,
            build_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            remote_modules=remote_assets or {},
            layouts=layouts_assets,
            global_css=global_css_out,
        )
