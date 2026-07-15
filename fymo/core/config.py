"""
Configuration management for Fymo applications
"""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

from fymo.core.exceptions import ConfigurationError


def env_truthy(name: str) -> bool:
    """Shared FYMO_DEV-style env flag check ("1"/"true"/"yes"/"on")."""
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def load_dotenv(project_root: Path) -> None:
    """Load KEY=value pairs from a .env file at the project root into
    os.environ, without overwriting a variable that's already set there.

    Callers gate this on dev mode and call it before constructing a
    ConfigManager, so ${VAR} interpolation in fymo.yml can see .env values
    alongside real env vars, while a real env var set outside .env always
    wins (so a one-off override doesn't require editing the file) and
    production never reads .env at all, even if one exists on disk.

    Hand-rolled rather than a python-dotenv dependency: the subset of the
    format actually needed (KEY=value, # comments, blank lines, optional
    matching quotes) is small and stable, matching the lazy-optional-dep
    philosophy already used for pyjwt in auth/providers/clerk.py rather
    than adding a hard dependency for a few lines of parsing.
    """
    dotenv_path = project_root / ".env"
    if not dotenv_path.is_file():
        return
    for raw_line in dotenv_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def parse_bool(value: Any, *, field: str) -> bool:
    """Strictly coerce a fymo.yml config value to bool.

    A value that flowed through ${VAR} interpolation is always a plain YAML
    string (see _yaml_quote below), so a bare bool(value) downstream would
    truthy-coerce any non-empty string, including the string "false",
    to True. A real bool passes through unchanged (a literal true/false
    YAML scalar untouched by interpolation, or a Python default like
    `not dev`). A string is accepted only as "true"/"false", case- and
    whitespace-insensitive. Anything else raises ConfigurationError naming
    `field` and the value, instead of silently guessing. Deliberately
    narrower than env_truthy above, which is fine defaulting an optional
    dev flag to False on an unrecognized token but wrong here, where a
    typo (e.g. "enabeld") should raise, not silently resolve to False.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise ConfigurationError(f"{field} must be true or false, got {value!r}")


# ${VAR} (required) or ${VAR:-default} (falls back when unset). Resolved on
# the raw YAML text before yaml.safe_load parses it: the simplest correct
# approach, and it applies uniformly to the whole file (any section, any
# nesting depth) instead of needing a walk over the parsed structure.
_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _yaml_quote(value: str) -> str:
    """Render `value` as a YAML double-quoted scalar.

    Splicing a resolved env value back into the raw config text as a plain
    substring would let a value that itself looks like YAML (a newline
    followed by "admin: true", a colon, a leading "- ") restructure the
    parsed config instead of staying a string. Emitting it as an explicit
    quoted scalar closes that off: whatever the value contains, it can only
    ever parse back out as that same string.
    """
    return yaml.dump(value, default_style='"', default_flow_style=True).strip()


def _find_matching_brace(text: str, open_index: int) -> int:
    """`text[open_index]` is the '{' that opened a '${' placeholder. Returns
    the index of the '}' that closes it, counting every '{'/'}' in between
    (not just '${' ones) so a nested ${OTHER} reference and a literal brace
    in a default (e.g. a JSON-shaped fallback) are both handled by the same
    depth count, instead of the first '}' anywhere winning.
    """
    depth = 1
    i = open_index + 1
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ConfigurationError(
        "fymo.yml has an unterminated \"${\" placeholder starting at "
        f"position {open_index - 1}; every \"${{\" needs a matching \"}}\""
    )


def _resolve_placeholder_value(inner: str) -> str:
    """Resolve the contents between one placeholder's outer ${ and }
    (e.g. "FOO", "FOO:-bar", or "FOO:-${BAR}") to its plain, unquoted
    value. A default is only evaluated, including any ${OTHER} nested in
    it, when the outer var is actually unset."""
    name, sep, default = inner.partition(":-")
    if not _VAR_NAME_RE.match(name):
        raise ConfigurationError(
            f'fymo.yml has a malformed placeholder: "${{{inner}}}" is not '
            'a valid ${VAR} or ${VAR:-default}'
        )
    if name in os.environ:
        return os.environ[name]
    if sep:
        return _scan_placeholders(default, quote=False)
    raise ConfigurationError(
        f"fymo.yml references undefined environment variable: {name}"
    )


def _scan_placeholders(text: str, quote: bool) -> str:
    """Walk `text` left to right, replacing every ${...} with its resolved
    value. `quote` controls whether each resolved value is spliced back in
    as a YAML-quoted scalar (splicing into the actual config text) or as a
    plain string (resolving a default's own value before its outer
    placeholder gets quoted once, so nesting can't double-quote)."""
    out = []
    pos = 0
    while True:
        start = text.find("${", pos)
        if start == -1:
            out.append(text[pos:])
            break
        out.append(text[pos:start])
        close = _find_matching_brace(text, start + 1)
        inner = text[start + 2:close]
        value = _resolve_placeholder_value(inner)
        out.append(_yaml_quote(value) if quote else value)
        pos = close + 1
    return "".join(out)


def _interpolate_env_vars(text: str) -> str:
    """Substitute ${VAR}/${VAR:-default} placeholders in raw fymo.yml text
    with real env values, each spliced back in as an explicit YAML-quoted
    scalar (see _yaml_quote) so a value can never be interpreted as new
    YAML structure, only ever as the literal string it is.

    A bare ${VAR} with nothing set raises loudly and names the var, since a
    deployment-specific value silently resolving to the literal string
    "${VAR}" would be a much worse failure mode than refusing to boot.
    """
    return _scan_placeholders(text, quote=True)


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
                    raw_text = f.read()
                interpolated_text = _interpolate_env_vars(raw_text)
                file_config = yaml.safe_load(interpolated_text) or {}
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
        """`remote:` section. Holds remote.mode (strict or implicit-legacy),
        controlling whether an app/remote/*.py function needs @remote to be
        browser-callable; default is implicit for back-compat. The deprecated
        explicit_optin/allow_implicit booleans still resolve through
        fymo.remote.mode.resolve_remote_mode."""
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

    def get_storage_config(self) -> Optional[Dict[str, Any]]:
        """`storage:` section. Selects the StorageProvider (bare string,
        `provider`/`class` dict, or absent, see fymo.storage.registry).
        Returns None, not {}, when absent: callers need to tell "no storage
        configured" apart from "configured but empty", since storage has no
        silent default the way auth/jobs/broadcasts do."""
        return self.get('storage', None)

    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary"""
        return self.config.copy()
