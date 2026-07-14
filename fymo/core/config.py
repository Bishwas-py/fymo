"""
Configuration management for Fymo applications
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional


def env_truthy(name: str) -> bool:
    """Shared FYMO_DEV-style env flag check ("1"/"true"/"yes"/"on")."""
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


class ConfigManager:
    """Manages configuration loading and access for Fymo applications"""
    
    def __init__(self, project_root: Path, initial_config: Optional[Dict[str, Any]] = None):
        """
        Initialize configuration manager
        
        Args:
            project_root: Root directory of the project
            initial_config: Initial configuration dictionary
        """
        self.project_root = project_root
        self.config = initial_config or {}
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from fymo.yml or config files"""
        config_file = self.project_root / "fymo.yml"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    file_config = yaml.safe_load(f) or {}
                    self.config.update(file_config)
            except (yaml.YAMLError, IOError) as e:
                print(f"Warning: Could not load config from {config_file}: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value"""
        self.config[key] = value
    
    def update(self, config: Dict[str, Any]) -> None:
        """Update configuration with new values"""
        self.config.update(config)
    
    def get_app_name(self) -> str:
        """Get the application name"""
        return self.get('name', 'Fymo App')
    
    def get_routes_config(self) -> Dict[str, Any]:
        """Get the routes configuration"""
        return self.get('routes', {})

    def get_limits_config(self) -> Dict[str, Any]:
        """`limits:` section. Holds rate_limit + max_body_bytes."""
        return self.get('limits', {}) or {}

    def get_security_config(self) -> Dict[str, Any]:
        """`security:` section. Holds headers config."""
        return self.get('security', {}) or {}

    def get_auth_config(self) -> Dict[str, Any]:
        """`auth:` section. Holds enabled flag + user_store import path."""
        return self.get('auth', {}) or {}

    def get_jobs_config(self) -> Dict[str, Any]:
        """`jobs:` section. Holds the JobProvider selection (bare string,
        `type`/`class` dict, or absent — see fymo.jobs.providers.registry)."""
        return self.get('jobs', {}) or {}

    def get_broadcasts_config(self) -> Dict[str, Any]:
        """`broadcasts:` section. Holds the BroadcastProvider selection —
        same shapes as jobs.provider; defaults to postgres when absent."""
        return self.get('broadcasts', {}) or {}

    def get_remote_config(self) -> Dict[str, Any]:
        """`remote:` section. Holds explicit_optin (require @remote to expose
        an app/remote/*.py function; default False for back-compat)."""
        return self.get('remote', {}) or {}

    def get_logging_config(self) -> Dict[str, Any]:
        """`logging:` section. Holds destination/file/level/format — see
        fymo.core.logging.resolve_logging_config for shapes and defaults."""
        return self.get('logging', {}) or {}

    def get_media_config(self) -> List[Dict[str, Any]]:
        """`media:` section. A list of {prefix, dir, extensions} entries
        for declarative byte-range media serving (see fymo.core.media),
        entirely optional. Absent means no media routes are registered, so
        existing apps are unaffected."""
        return self.get('media', []) or []

    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary"""
        return self.config.copy()
