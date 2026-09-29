"""Start the packaged API locally and probe both model versions without NOAA."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise ValueError(f"Health probe returned HTTP {response.status}")
        return json.load(response)


def main() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with TemporaryDirectory(prefix="yuki-runtime-smoke-") as current_root:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["RENDER"] = "true"
        env["FORECAST_BUST_CORS_ORIGINS"] = "https://example.test"
        env["FORECAST_BUST_CURRENT_ROOT"] = current_root
        env.pop("FORECAST_BUST_OBJECT_BUCKET", None)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "forecast_bust.api.app:app",
                                    "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags)
        try:
            deadline = monotonic() + 60
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Packaged API process exited before readiness")
                try:
                    v2 = get_json(f"http://127.0.0.1:{port}/api/v2/health")
                    break
                except (URLError, TimeoutError):
                    if monotonic() > deadline:
                        raise RuntimeError("Packaged API did not become ready")
                    sleep(0.5)
            v1 = get_json(f"http://127.0.0.1:{port}/health")
            if not v1["model_ready"] or not v2["model_ready"] or v2["state_count"] != 36:
                raise ValueError("Packaged API model/state readiness failed")
            current = v2["primary_initialization"]
            if v2["run_metadata"][current]["run_kind"] != "current_forecast":
                raise ValueError("Packaged API did not serve the bootstrap current run")
            summary = get_json(f"http://127.0.0.1:{port}/api/v2/forecast/{current}/summary")
            if len(summary["lead_day_summaries"]) != 10:
                raise ValueError("Packaged current run does not cover Day 1–10")
            print(f"PACKAGED_API_READY=true V1_READY=true V2_READY=true CURRENT_RUN={current} STATES=36 DAYS=10")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
