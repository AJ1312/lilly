"""Run Lilly: build the runtime, serve the UI on this computer only, and shut down cleanly."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from pathlib import Path

import uvicorn

from lilly.app.paths import LillyPaths
from lilly.app.runtime import Runtime
from lilly.bridges.service import BridgeService
from lilly.domain.errors import ConfigurationError
from lilly.obs.log import setup_logging
from lilly.ui.app import create_app
from lilly.ui.security import Auth

HOST = "127.0.0.1"  # Lilly never listens on another address. Reach it remotely through a Tailscale Serve proxy.
DEFAULT_PORT = 8787
log = logging.getLogger("lilly.daemon")


def pid_file(paths: LillyPaths) -> Path:
    return paths.root / "lilly.pid"


def ensure_port_free(port: int) -> None:
    """Fail early with a clear message. The probe sets SO_REUSEADDR like the real server does, so a port that is
    merely in TIME_WAIT after a previous run (common on macOS) is not mistaken for one in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except OSError as exc:
            raise ConfigurationError(
                f"cannot listen on port {port} ({exc.strerror}). Another program may be using it: find it with "
                f"`lsof -nP -iTCP:{port} -sTCP:LISTEN`, or choose another port with `lilly --port 8790 open`."
            ) from exc


async def serve(paths: LillyPaths, port: int = DEFAULT_PORT) -> None:
    """Run until asked to stop (Ctrl-C, SIGTERM, `lilly stop`)."""
    ensure_port_free(port)
    setup_logging(paths.log)
    auth = Auth(paths.token, paths.secret)
    runtime = await Runtime.create(paths)
    bridge = BridgeService(runtime)
    await bridge.start()
    server = uvicorn.Server(uvicorn.Config(
        create_app(runtime, auth, bridges=bridge), host=HOST, port=port, log_level="warning", access_log=False,
        server_header=False, date_header=False, timeout_graceful_shutdown=3, lifespan="off"))

    async def release_streams() -> None:
        # Live-event connections never end by themselves; close them as soon as shutdown begins.
        while not server.should_exit:
            await asyncio.sleep(0.2)
        runtime.bus.close()

    pid_file(paths).write_text(str(os.getpid()))
    log.info("Lilly %s listening on http://%s:%d", "started", HOST, port)
    releaser = asyncio.create_task(release_streams())
    try:
        await server.serve()
    finally:
        releaser.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await releaser
        await bridge.aclose()
        await runtime.close()
        pid_file(paths).unlink(missing_ok=True)
        log.info("Lilly stopped")
