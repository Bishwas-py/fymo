"""
Build command for Fymo projects
"""

import os
import subprocess
import sys
from pathlib import Path
from fymo.utils.colors import Color
from fymo.bundler.runtime_builder import ensure_svelte_runtime
from fymo.build.pipeline import BuildPipeline, BuildError


def build_project(output: str = 'dist', minify: bool = False):
    """Build the project for production."""
    project_root = Path.cwd()

    if os.environ.get("FYMO_NEW_PIPELINE") == "1":
        Color.print_info("Building with new pipeline (esbuild + Node sidecar)")
        try:
            BuildPipeline(project_root=project_root).build(dev=False)
        except BuildError as e:
            Color.print_error(str(e))
            raise SystemExit(1)
        Color.print_success(f"Built to {project_root / 'dist'}/")
        return

    # Legacy path
    Color.print_info(f"Building project to {output}/")
    ensure_svelte_runtime(project_root)
    Color.print_success("Project built successfully!")


def build_runtime():
    """Build just the Svelte runtime"""
    project_root = Path.cwd()
    Color.print_info("Building Svelte runtime...")
    
    # Use the bundled build script from the framework
    package_dir = Path(__file__).parent.parent.parent
    build_script = package_dir / 'bundler' / 'js' / 'build_runtime.js'
    
    if not build_script.exists():
        Color.print_error(f"Build script not found at {build_script}")
        return False
    
    try:
        result = subprocess.run(
            ['node', str(build_script)],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            Color.print_success("Svelte runtime built successfully!")
            return True
        else:
            Color.print_error(f"Build failed: {result.stderr}")
            return False
            
    except FileNotFoundError:
        Color.print_error("Node.js not found. Please install Node.js.")
        return False
    except Exception as e:
        Color.print_error(f"Build error: {e}")
        return False
