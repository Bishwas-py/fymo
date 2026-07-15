"""`fymo jobs-worker` — start the configured JobProvider's worker loop.

Runs as its own long-lived OS process, independent of `fymo serve`/`fymo
dev` — scaled, deployed, and restarted on its own axis (see the
Job Providers design doc, section 3.4). Deliberately does not construct a
full FymoApp: a worker process needs only the configured JobProvider with
its app/jobs/*.py tasks registered, not the sidecar/HTTP-serving machinery.
"""
from pathlib import Path
from typing import Optional

from fymo.core.config import ConfigManager
from fymo.jobs import init_job_provider
from fymo.utils.colors import Color


def run_jobs_worker(project_root: Optional[Path] = None) -> None:
    """Build the project's configured JobProvider and run its worker loop.

    Blocks forever under normal operation (e.g. Procrastinate's default
    `wait=True`). Exits with status 1 and a clear message — instead of a
    raw traceback — if the configured provider has no separate worker
    process (e.g. the default `threaded`) or is misconfigured (e.g.
    `procrastinate` with no `DATABASE_URL`).
    """
    project_root = Path(project_root) if project_root else Path.cwd()

    # Resolved before ConfigManager so both this dev-only .env load and
    # ConfigManager's ${VAR} interpolation of fymo.yml see the same env,
    # matching FymoApp.__init__'s ordering (fymo/core/server.py).
    from fymo.core.config import env_truthy, load_dotenv
    dev = env_truthy("FYMO_DEV")
    if dev:
        load_dotenv(project_root)

    config_manager = ConfigManager(project_root)

    # The worker is its own OS process — FymoApp's logging configuration
    # happened in the web process, not here. Same config source, same
    # dev-detection (FYMO_DEV), so both processes log to the same place in
    # the same format.
    from fymo.core.logging import configure as _configure_logging
    _configure_logging(
        dev=dev,
        config=config_manager.get_logging_config(),
        project_root=project_root,
    )

    provider_config = config_manager.get_jobs_config().get("provider")

    provider = init_job_provider(project_root, provider_config)

    # Jobs publish progress/completion to broadcast channels, and this
    # worker is a separate OS process — it needs its own broadcast init
    # (FymoApp's happened in the web process, not here).
    from fymo.broadcast import init_broadcasts
    init_broadcasts(project_root, config_manager.get_broadcasts_config().get("provider"))

    Color.print_info(f"Starting job worker ({provider.id}) for {project_root}")
    try:
        provider.run_worker()
    except RuntimeError as e:
        Color.print_error(str(e))
        raise SystemExit(1)
    except KeyboardInterrupt:
        Color.print_info("\nShutting down job worker...")
