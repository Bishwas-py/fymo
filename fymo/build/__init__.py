"""Build pipeline for Fymo: produces dist/ from app/templates/."""
from fymo.build.discovery import discover_routes, Route
from fymo.build.manifest import Manifest, RouteAssets
from fymo.build.pipeline import BuildPipeline, BuildError, BuildResult

__all__ = [
    "discover_routes", "Route",
    "Manifest", "RouteAssets",
    "BuildPipeline", "BuildError", "BuildResult",
]
