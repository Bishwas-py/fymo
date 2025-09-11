"""
Configuration management for Fymo applications
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional


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
    
    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary"""
        return self.config.copy()
