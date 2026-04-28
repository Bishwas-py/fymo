"""`fymo dev` — watch + serve."""
import os
import time
from pathlib import Path
from fymo.utils.colors import Color
from fymo.build.dev_orchestrator import DevOrchestrator


def run_dev(host: str = "127.0.0.1", port: int = 8000):
    project_root = Path.cwd()
    Color.print_info("Starting dev server with watcher")

    orch = DevOrchestrator(project_root=project_root)
    orch.start()

    # Wait for initial build
    manifest_path = project_root / "dist" / "manifest.json"
    deadline = time.time() + 30
    while time.time() < deadline and not manifest_path.exists():
        time.sleep(0.1)
    if not manifest_path.exists():
        Color.print_error("initial build did not complete in 30s")
        orch.stop()
        return

    Color.print_success("Initial build complete")

    os.environ["FYMO_NEW_PIPELINE"] = "1"

    from fymo import create_app
    app = create_app(project_root)
    app.dev_orchestrator = orch

    from wsgiref.simple_server import make_server
    server = make_server(host, port, app)
    Color.print_info(f"Listening on http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if app.sidecar:
            app.sidecar.stop()
        orch.stop()
