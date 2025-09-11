"""
Routing system for Fymo
"""

from pathlib import Path
from typing import Dict, Optional, List, Any, Union
import yaml
import re

from fymo.core.exceptions import RouterError, ConfigurationError


class Router:
    """Handle routing for Fymo applications"""
    
    def __init__(self, routes_file: Optional[Path] = None) -> None:
        """
        Initialize router
        
        Args:
            routes_file: Path to routes configuration file
        """
        self.routes: Dict[str, Dict[str, Any]] = {}
        self.resources: List[str] = []
        
        if routes_file and routes_file.exists():
            try:
                self._load_routes_from_file(routes_file)
            except Exception as e:
                raise ConfigurationError(f"Failed to load routes from {routes_file}: {str(e)}")
        elif routes_file:
            raise RouterError(f"Routes file not found: {routes_file}")
        # If no routes file provided, start with empty routes (will be populated dynamically)
    
    def _load_routes_from_file(self, routes_file: Path) -> None:
        """Load routes from a Python or YAML file"""
        if routes_file.suffix == '.py':
            self._load_python_routes(routes_file)
        elif routes_file.suffix in ['.yml', '.yaml']:
            self._load_yaml_routes(routes_file)
    
    def _load_python_routes(self, routes_file: Path):
        """Load routes from a Python file"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("routes", routes_file)
        routes_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(routes_module)
        
        if hasattr(routes_module, 'routes'):
            self.routes = routes_module.routes
        if hasattr(routes_module, 'resources'):
            self.resources = routes_module.resources
            self._expand_resources()
    
    def _load_yaml_routes(self, routes_file: Path):
        """Load routes from a YAML file"""
        try:
            with open(routes_file, 'r') as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in routes file: {str(e)}")
        except IOError as e:
            raise RouterError(f"Could not read routes file: {str(e)}")
        
        # Handle nested routes structure (fymo.yml format)
        routes_config = config.get('routes', config)
        
        if 'root' in routes_config:
            controller, action = routes_config['root'].split('.')
            self.routes['/'] = {
                'controller': controller,
                'action': action,
                'template': f"{controller}/{action}.svelte"
            }
        
        if 'resources' in routes_config:
            self.resources = routes_config['resources']
            self._expand_resources()
        
        # Handle explicit route definitions
        for key, value in routes_config.items():
            if key not in ['root', 'resources'] and isinstance(value, str):
                controller, action = value.split('.')
                self.routes[key] = {
                    'controller': controller,
                    'action': action,
                    'template': f"{controller}/{action}.svelte"
                }
            elif key not in ['root', 'resources'] and isinstance(value, dict):
                self.routes[key] = value
    
    def _expand_resources(self):
        """Expand resource routes (RESTful routing)"""
        for resource in self.resources:
            # Index route
            self.routes[f'/{resource}'] = {
                'controller': resource,
                'action': 'index',
                'template': f'{resource}/index.svelte'
            }
            
            # Show route
            self.routes[f'/{resource}/:id'] = {
                'controller': resource,
                'action': 'show',
                'template': f'{resource}/show.svelte'
            }
            
            # Edit route
            self.routes[f'/{resource}/:id/edit'] = {
                'controller': resource,
                'action': 'edit',
                'template': f'{resource}/edit.svelte'
            }
            
            # New route
            self.routes[f'/{resource}/new'] = {
                'controller': resource,
                'action': 'new',
                'template': f'{resource}/new.svelte'
            }
    
    def match(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Match a path to a route
        
        Args:
            path: The URL path to match
            
        Returns:
            Route information dict or None
        """
        # Normalize path
        if path != '/' and path.endswith('/'):
            path = path[:-1]
        
        # Direct match
        if path in self.routes:
            return self.routes[path]
        
        # Try pattern matching (for :id style params)
        for route_pattern, route_info in self.routes.items():
            if ':' in route_pattern:
                # Convert :param to regex
                pattern = re.escape(route_pattern)
                pattern = re.sub(r'\\:(\w+)', r'(?P<\1>[^/]+)', pattern)
                pattern = f'^{pattern}$'
                
                match = re.match(pattern, path)
                if match:
                    # Add params to route info
                    route_info_copy = route_info.copy()
                    route_info_copy['params'] = match.groupdict()
                    return route_info_copy
        
        # Try to match as a resource route
        parts = path.strip('/').split('/')
        if parts and parts[0] in self.resources:
            resource = parts[0]
            
            # Default to index if no other parts
            if len(parts) == 1:
                return {
                    'controller': resource,
                    'action': 'index',
                    'template': f'{resource}/index.svelte'
                }
        
        # If no explicit routes found, try convention-based routing
        return self._try_convention_based_routing(path)
    
    def add_route(self, path: str, controller: str, action: str, template: Optional[str] = None) -> None:
        """Add a route dynamically"""
        if not template:
            template = f"{controller}/{action}.svelte"
        
        self.routes[path] = {
            'controller': controller,
            'action': action,
            'template': template
        }
    
    def _try_convention_based_routing(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Try to match path using convention-based routing
        
        Convention:
        - / -> home.index
        - /controller -> controller.index  
        - /controller/action -> controller.action
        """
        # Normalize path
        if path == '/':
            return {
                'controller': 'home',
                'action': 'index',
                'template': 'home/index.svelte'
            }
        
        # Remove leading slash and split
        parts = path.strip('/').split('/')
        
        if len(parts) == 1:
            # /controller -> controller.index
            controller = parts[0]
            return {
                'controller': controller,
                'action': 'index',
                'template': f'{controller}/index.svelte'
            }
        elif len(parts) == 2:
            # /controller/action -> controller.action
            controller, action = parts
            return {
                'controller': controller,
                'action': action,
                'template': f'{controller}/{action}.svelte'
            }
        
        return None
