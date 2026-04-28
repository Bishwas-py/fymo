"""
Build command for Fymo projects
"""

from pathlib import Path
from fymo.utils.colors import Color
from fymo.build.pipeline import BuildPipeline, BuildError


def build_project(output: str = 'dist', minify: bool = False):
    """Build the project for production."""
    project_root = Path.cwd()
    Color.print_info("Building")
    try:
        BuildPipeline(project_root=project_root).build(dev=False)
    except BuildError as e:
        Color.print_error(str(e))
        raise SystemExit(1)
    Color.print_success(f"Built to {project_root / 'dist'}/")


def build_runtime():
    """Deprecated: kept for backwards compat with `fymo build-runtime`."""
    Color.print_info(
        "`fymo build-runtime` is deprecated; the runtime is bundled "
        "per-route by `fymo build`."
    )
    return True
