"""Build pipeline for Fymo: produces dist/ from app/templates/."""
from fymo.build.discovery import discover_routes, Route

__all__ = ["discover_routes", "Route"]
