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
        # Per-controller soft-nav flag. True (default) = SPA-style nav; False
        # = full page reload on every link to that resource.
        self._soft_nav: Dict[str, bool] = {}
        # Per-resource require_auth value (True or dotted guard path),
        # attached to every expanded route of the resource.
        self._resource_require_auth: Dict[str, Any] = {}
        # Route name -> path. Names come from the fymo.yml key ('root' for
        # root:, the resource name, or the explicit key sans leading '/').
        # The route named 'signin' is the require_auth redirect target.
        self._route_names: Dict[str, str] = {}
        self._signin_path: Optional[str] = None

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
            for path in self.routes:
                self._route_names.setdefault(path.lstrip('/') or 'root', path)
        if hasattr(routes_module, 'resources'):
            self.resources = routes_module.resources
            self._expand_resources()
        self._finalize_require_auth()
    
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
            root_spec = routes_config['root']
            if isinstance(root_spec, dict):
                # Dict form exists so root can carry route attributes
                # (require_auth); the target moves under `to:`.
                to = root_spec.get('to')
                if not to:
                    raise ConfigurationError(
                        "routes.root dict form requires `to: controller.action`"
                    )
                controller, action = to.split('.')
                info = {
                    'controller': controller,
                    'action': action,
                    'template': f"{controller}/{action}.svelte",
                }
                for attr_key, attr_value in root_spec.items():
                    if attr_key != 'to':
                        info.setdefault(attr_key, attr_value)
            else:
                controller, action = root_spec.split('.')
                info = {
                    'controller': controller,
                    'action': action,
                    'template': f"{controller}/{action}.svelte",
                }
            self.routes['/'] = info
            self._route_names['root'] = '/'

        if 'resources' in routes_config:
            # Resources may be plain strings (`- posts`) or dicts with
            # per-resource config (`- name: admin\n  soft_nav: false`).
            normalized: List[str] = []
            for entry in routes_config['resources']:
                if isinstance(entry, str):
                    normalized.append(entry)
                elif isinstance(entry, dict):
                    name = entry.get('name')
                    if not name:
                        raise ConfigurationError(
                            f"resource entry missing required 'name': {entry}"
                        )
                    normalized.append(name)
                    if 'soft_nav' in entry:
                        self._soft_nav[name] = bool(entry['soft_nav'])
                    if 'require_auth' in entry:
                        self._resource_require_auth[name] = entry['require_auth']
                else:
                    raise ConfigurationError(
                        f"resource entry must be a string or dict, got {type(entry).__name__}"
                    )
            self.resources = normalized
            self._expand_resources()
        
        # Handle explicit route definitions. Keys are stored as paths
        # (leading '/' added when missing) so a declared route actually
        # direct-matches in match() instead of falling through to the
        # convention guess, which would drop its attributes (require_auth).
        for key, value in routes_config.items():
            if key in ['root', 'resources']:
                continue
            name = key.lstrip('/')
            path = key if key.startswith('/') else f'/{key}'
            if isinstance(value, str):
                controller, action = value.split('.')
                info = {
                    'controller': controller,
                    'action': action,
                    'template': f"{controller}/{action}.svelte"
                }
            elif isinstance(value, dict):
                if 'to' in value:
                    controller, action = value['to'].split('.')
                    info = {
                        'controller': controller,
                        'action': action,
                        'template': f"{controller}/{action}.svelte",
                    }
                    for attr_key, attr_value in value.items():
                        if attr_key != 'to':
                            info.setdefault(attr_key, attr_value)
                else:
                    info = value
            else:
                continue
            self.routes[path] = info
            self._route_names[name] = path
        self._finalize_require_auth()

    def _finalize_require_auth(self):
        """Apply the require_auth conventions after all routes are loaded.

        The route named 'signin' is the redirect target and is auto-public:
        require_auth on it is ignored with a warning. Any route carrying
        require_auth with no signin route to redirect to is a hard
        configuration error at boot, not a request-time surprise.
        """
        signin = self._route_names.get('signin')
        self._signin_path = signin
        if signin is not None:
            info = self.routes.get(signin)
            if isinstance(info, dict) and info.get('require_auth'):
                from fymo.utils.colors import Color
                Color.print_warning(
                    "route 'signin' is the require_auth redirect target and is "
                    "always public; ignoring require_auth on it"
                )
                info.pop('require_auth', None)
        protected = [
            path for path, info in self.routes.items()
            if isinstance(info, dict) and info.get('require_auth')
        ]
        if protected and signin is None:
            from fymo.core.page_auth import REQUIRE_AUTH_WITHOUT_SIGNIN_ERROR
            raise ConfigurationError(REQUIRE_AUTH_WITHOUT_SIGNIN_ERROR)

    def signin_path(self) -> Optional[str]:
        """Path of the route named 'signin' (the require_auth redirect
        target), or None when no such route is declared."""
        return self._signin_path

    def _expand_resources(self):
        """Expand resource routes (RESTful routing)"""
        for resource in self.resources:
            require_auth = self._resource_require_auth.get(resource)
            self._route_names[resource] = f'/{resource}'

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

            if require_auth is not None:
                for suffix in ('', '/:id', '/:id/edit', '/new'):
                    self.routes[f'/{resource}{suffix}']['require_auth'] = require_auth
    
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
                # Substitute :param placeholders before escaping so that
                # re.escape() doesn't interfere with them.
                pattern = re.sub(r':(\w+)', r'(?P<\1>[^/]+)', route_pattern)
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

    def soft_nav_enabled(self, controller: str) -> bool:
        """Whether SPA-style soft navigation is enabled for this controller.

        Default: True. Apps opt out via `resources: - {name: x, soft_nav: false}`
        in fymo.yml.
        """
        return self._soft_nav.get(controller, True)

    def disabled_soft_nav_resources(self) -> List[str]:
        """Sorted list of resource names with soft_nav explicitly disabled."""
        return sorted(name for name, enabled in self._soft_nav.items() if not enabled)
    
    def _try_convention_based_routing(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Try to match path using convention-based routing
        
        Convention:
        - / -> home.index
        - /controller -> controller.index
        - /controller/action -> controller.action

        Matches carry `'convention': True` so callers can tell a guessed
        route from a declared one: a convention match with no built assets
        behind it is a routing miss (404), whereas a declared route in the
        same state is a stale build (500).
        """
        # Normalize path
        if path == '/':
            return {
                'controller': 'home',
                'action': 'index',
                'template': 'home/index.svelte',
                'convention': True
            }

        # Remove leading slash and split
        parts = path.strip('/').split('/')

        if len(parts) == 1:
            # /controller -> controller.index
            controller = parts[0]
            return {
                'controller': controller,
                'action': 'index',
                'template': f'{controller}/index.svelte',
                'convention': True
            }
        elif len(parts) == 2:
            # /controller/action -> controller.action
            controller, action = parts
            return {
                'controller': controller,
                'action': action,
                'template': f'{controller}/{action}.svelte',
                'convention': True
            }

        return None
