"""`fymo jobs-status`: print what the configured JobProvider knows about
job state, counts by status first, then the most recent jobs.

Read-only, answers "is this job stuck" without hand-querying Postgres
(issue #52). Like `fymo jobs-worker` it deliberately does not construct a
full FymoApp (it only needs the configured JobProvider), and unlike the
worker it also skips broadcasts/storage/logging setup, since it never
executes a job, it only reads the provider's own bookkeeping.

A provider that doesn't track job state (the default `threaded`, or any
custom provider keeping the base's None defaults) exits with status 1 and
a clear message: that absence is a documented provider property, not a
fymo oversight (see docs/conventions.md, "Job status visibility").
"""
from pathlib import Path
from typing import Optional

from fymo.core.config import ConfigManager
from fymo.jobs import init_job_provider
from fymo.utils.colors import Color


def run_jobs_status(
    project_root: Optional[Path] = None, limit: int = 10, dev: bool = False,
) -> None:
    """Build the project's configured JobProvider and print its status
    surface (job_counts()/list_recent_jobs()).

    `dev=True` (the --dev CLI flag) gets the same treatment as
    `fymo jobs-worker --dev`: it sets FYMO_DEV=1 in this process before
    anything reads it, so .env loading works, which matters here because
    DATABASE_URL usually lives in .env during development.
    """
    import os

    project_root = Path(project_root) if project_root else Path.cwd()

    if dev:
        os.environ["FYMO_DEV"] = "1"

    # Same ordering as run_jobs_worker: .env must be loaded (dev-only)
    # before ConfigManager interpolates ${VAR} references in fymo.yml.
    from fymo.core.config import env_truthy, load_dotenv
    if env_truthy("FYMO_DEV"):
        load_dotenv(project_root)

    config_manager = ConfigManager(project_root)
    provider_config = config_manager.get_jobs_config().get("provider")
    provider = init_job_provider(project_root, provider_config)

    # Both status methods are read through getattr for the same reason
    # close() is below: the registry never required BaseJobProvider
    # subclassing, so a duck-typed provider written against the pre-status
    # contract simply lacks them, and that means "tracks nothing", not an
    # AttributeError traceback.
    counts_fn = getattr(provider, "job_counts", None)
    recent_fn = getattr(provider, "list_recent_jobs", None)
    try:
        counts = counts_fn() if counts_fn is not None else None
        recent = recent_fn(limit) if (recent_fn is not None and counts is not None) else None
    except Exception as e:
        # Misconfiguration (missing DATABASE_URL, missing extra) raises
        # RuntimeError, but backend failures surface as other Exception
        # subclasses too: procrastinate wraps every psycopg error, missing
        # tables and unreachable servers included, in its own plain
        # ConnectorException, and a status query against a database the
        # worker has never touched is this command's most likely first
        # run. All of it reports as a clear message, not a raw traceback.
        # The cause chain is included because ConnectorException's own
        # message is just "Database error.", the actionable part (which
        # table is missing, which host was unreachable) lives in the
        # chained psycopg exception underneath.
        parts: list = []
        current: Optional[BaseException] = e
        while current is not None and len(parts) < 4:
            text = str(current).strip()
            if text and text not in parts:
                parts.append(text)
            current = current.__cause__ or current.__context__
        Color.print_error(" | ".join(parts) or type(e).__name__)
        raise SystemExit(1)
    finally:
        # This process is done with the provider either way: release its
        # connection instead of leaving it to interpreter shutdown.
        # Guarded because close() joined the seam after custom providers
        # existed; one written against the older contract may lack it.
        close = getattr(provider, "close", None)
        if close is not None:
            close()

    if counts is None:
        Color.print_error(
            f"the {provider.id!r} job provider does not track job state — "
            "there is nothing to report. Providers backed by a durable "
            "queue (e.g. 'procrastinate') support `fymo jobs-status`; see "
            "docs/conventions.md for the app-level progress convention."
        )
        raise SystemExit(1)

    Color.print_info(f"Job status ({provider.id})")
    status_width = max((len(s) for s in counts), default=0)
    for status, count in counts.items():
        print(f"  {status:<{status_width}}  {count}")

    print()
    Color.print_info(f"Recent jobs (newest first, up to {limit})")
    if recent is None:
        print("  this provider does not list individual jobs")
        return
    if not recent:
        print("  (none)")
        return

    rows = [
        (
            record.id,
            record.task_name,
            record.status,
            record.queued_at.isoformat(sep=" ", timespec="seconds")
            if record.queued_at else "-",
        )
        for record in recent
    ]
    headers = ("ID", "TASK", "STATUS", "QUEUED AT")
    widths = [
        max(len(headers[col]), *(len(row[col]) for row in rows))
        for col in range(len(headers))
    ]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for row in rows:
        print("  " + "  ".join(cell.ljust(w) for cell, w in zip(row, widths)))
