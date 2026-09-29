#!/usr/bin/env python3
"""Run the integration suite on a new disposable Compose database.

The project's unique Compose volume is removed when the run ends. It never
touches the default `docker compose up` portal or its data volume.
"""

from __future__ import annotations

import os
import http.client
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def unused_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    project = f"beyondbugtest-{uuid.uuid4().hex[:10]}"
    port = unused_local_port()
    base = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["DOGFOOD_PORT"] = str(port)
    environment["DOGFOOD_TEST_URL"] = base
    environment["DOGFOOD_BOOTSTRAP_EMAIL"] = "integration-admin@beyondbug.local"
    environment["DOGFOOD_BOOTSTRAP_PASSWORD"] = "DisposableTestAdmin2026!"
    command = ["docker", "compose", "-p", project]
    print(f"Fresh test portal: {base} ({project})", flush=True)
    try:
        subprocess.run(command + ["up", "-d", "--build"], cwd=ROOT, env=environment, check=True)
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, http.client.HTTPException):
                time.sleep(1)
        else:
            raise RuntimeError("Fresh portal did not become healthy within 60 seconds")
        subprocess.run(command + ["run", "--rm", "--no-deps", "--volume", f"{ROOT}:/app:ro",
                                  "--env", "DOGFOOD_TEST_URL=http://portal:8080",
                                  "portal", "python", "-m", "unittest", "discover", "-s", "tests", "-v"],
                       cwd=ROOT, env=environment, check=True)
    finally:
        subprocess.run(command + ["down", "--volumes"], cwd=ROOT, env=environment,
                       check=True)


if __name__ == "__main__":
    main()
