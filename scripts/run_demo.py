#!/usr/bin/env python3
"""One-shot demo stack: FastAPI backend (SQLite) + LoRa gateway simulator + Next.js dashboard.

Everything runs with dummy data in one command:

    python scripts/run_demo.py            # seed + start all three services
    python scripts/run_demo.py --fresh    # wipe .demo state first
    python scripts/run_demo.py --skip-frontend
    python scripts/run_demo.py --no-open
    python scripts/run_demo.py --stop     # stop a running instance

State (DB, gateway buffer, logs) lives in `.demo/` at the repo root so a demo
run never touches developer databases. Ctrl+C stops all three services.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
GATEWAY_DIR = ROOT / "gateway"
FRONTEND_DIR = ROOT / "frontend"
RUN_DIR = ROOT / ".demo"
LOG_DIR = RUN_DIR / "logs"
PID_FILE = RUN_DIR / "pids.json"

BACKEND_PORT = 8000
FRONTEND_PORT = 3000

ADMIN_USER = "admin@ess.local"
ADMIN_PASS = "change-me-strong-password"
GATEWAY_KEY = "change-me-gateway-key"
IS_WIN = os.name == "nt"

CHILDREN: dict[str, subprocess.Popen] = {}

# Windows consoles default to cp1252 and choke on unicode arrows
for _s in (sys.stdout, sys.stderr):
    if _s and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _venv_python(base: Path) -> Path:
    return base / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")


def _run_step(cmd: list[str], cwd: Path, env: dict[str, str], label: str) -> None:
    print(f"→ {label} …")
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(f"✗ {label} failed (exit {proc.returncode})")
        for stream in (proc.stderr, proc.stdout):
            if stream and stream.strip():
                print("  " + stream.strip().replace("\n", "\n  ")[-2500:])
        sys.exit(proc.returncode)
    if proc.stdout.strip():
        print("  " + "\n  ".join(proc.stdout.strip().splitlines())[:1500])


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _kill_tree(pid: int) -> None:
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def _stop_routine() -> None:
    if not PID_FILE.exists():
        print("No running demo found (no PID file).")
        return
    for label, pid in json.loads(PID_FILE.read_text(encoding="utf-8")).items():
        print(f"Stopping {label} (pid {pid}) …")
        _kill_tree(pid)
    PID_FILE.unlink(missing_ok=True)
    print("Stopped.")


def _spawn(cmd: list[str], cwd: Path, env: dict[str, str], label: str, log_name: str) -> subprocess.Popen:
    log = open(LOG_DIR / log_name, "wb")
    print(f"→ starting {label} (log: .demo/logs/{log_name})")
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    CHILDREN[label] = proc
    return proc


def _tail(proc_name: str) -> None:
    log = LOG_DIR / f"{proc_name}.log"
    if log.exists():
        with open(log, encoding="utf-8", errors="replace") as f:
            data = f.read()
        print(f"--- last lines of {proc_name}.log ---")
        print("\n".join(data.splitlines()[-20:]))


def _wait_ur(url: str, timeout: float, min_len: int = 0) -> None:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                body = r.read()
                if r.status == 200 and len(body) >= min_len:
                    return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(1.0)
    raise RuntimeError(f"{url} not ready after {timeout:.0f}s ({last_err})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full ESS demo stack with dummy data")
    parser.add_argument("--stop", action="store_true", help="stop a previously started instance")
    parser.add_argument("--fresh", action="store_true", help="wipe .demo state (db/logs/buffer) first")
    parser.add_argument("--skip-frontend", action="store_true", help="run backend + gateway only")
    parser.add_argument("--no-open", action="store_true", help="don't open the browser automatically")
    args = parser.parse_args()

    if args.stop:
        _stop_routine()
        return 0

    py = _venv_python(BACKEND_DIR)
    if not py.exists():
        print(f"✗ backend venv missing at {py}\n  create it: python -m venv backend/.venv && backend\\.venv\\Scripts\\pip install -r backend/requirements.txt")
        return 2
    for label, port in (("backend API", BACKEND_PORT), ("gateway health", 8080)):
        if not _port_free(port):
            print(f"✗ port {port} in use ({label}) — stop that service or run: python scripts/run_demo.py --stop")
            return 2
    if not args.skip_frontend:
        if not _port_free(FRONTEND_PORT):
            print(f"✗ port {FRONTEND_PORT} in use — stop the other dev server first")
            return 2
        if not (FRONTEND_DIR / "node_modules").exists():
            print("✗ frontend deps missing — run `npm install` in frontend/")
            return 2

    if args.fresh:
        shutil.rmtree(RUN_DIR, ignore_errors=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        print("Another demo instance may be running — run `python scripts/run_demo.py --stop` first.")
        return 2

    env = {k: v for k, v in os.environ.items() if not k.startswith("NEXT_PUBLIC_")}
    env.update(
        ENV="development",
        PYTHONUTF8="1",
        SECRET_JWT_KEY="demo-secret-key-not-for-production-0123456789",
        ADMIN_USERNAME=ADMIN_USER,
        ADMIN_PASSWORD=ADMIN_PASS,
        DATABASE_URL=f"sqlite+aiosqlite:///{(RUN_DIR / 'demo.db').as_posix()}",
        CORS_ORIGINS=json.dumps([
            f"http://localhost:{FRONTEND_PORT}",
            f"http://127.0.0.1:{FRONTEND_PORT}",
        ]),
    )

    # 1) schema + seed + dummy history (stdout shown inline)
    _run_step([str(py), "-m", "alembic", "upgrade", "head"], BACKEND_DIR, env, "migrations")
    _run_step([str(py), "-m", "app.db.seed"], BACKEND_DIR, env, "seed")
    _run_step([str(py), str(ROOT / "scripts" / "seed_history.py")], BACKEND_DIR, env, "dummy history seed")

    # 2) backend
    _spawn([str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
           BACKEND_DIR, env, "backend", "backend.log")
    try:
        _wait_ur(f"http://127.0.0.1:{BACKEND_PORT}/api/v1/health", timeout=60)
        print(f"✔ backend healthy → http://localhost:{BACKEND_PORT}")

        # 3) gateway simulator
        health_port = 8080
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        health_port = probe.getsockname()[1]
        probe.close()
        node_keys = ",".join(f"{d}:{secrets.token_hex(32)}" for d in ("101", "102", "103"))
        gw_env = {
            **env,
            "BACKEND_URL": f"http://127.0.0.1:{BACKEND_PORT}",
            "GATEWAY_API_KEY": GATEWAY_KEY,
            "GATEWAY_ID": "gw-1",
            "NODE_KEYS": node_keys,
            "SIMULATE_DEVICE_IDS": "101,102,103",
            "SIMULATE_INTERVAL_SECONDS": "3",
            "SIMULATE_WATER_RATE": "0.15",
            "SIMULATE_FAULT_RATE": "0.05",
            "BUFFER_DB_PATH": str(RUN_DIR / "gateway-buffer.sqlite3"),
            "HEALTH_PORT": str(health_port),
        }
        _spawn([str(py), "-m", "gateway_pkg.main", "--simulate", "--log-level", "INFO"],
               GATEWAY_DIR, gw_env, "gateway", "gateway.log")

        # 4) frontal (Next.js dev server)
        frontend: subprocess.Popen | None = None
        if not args.skip_frontend:
            npm = shutil.which("npm.cmd" if IS_WIN else "npm") or "npm"
            fe_env = {
                **env,
                "NEXT_PUBLIC_API_BASE_URL": f"http://localhost:{BACKEND_PORT}/api/v1",
                "NEXT_PUBLIC_WS_BASE_URL": f"ws://localhost:{BACKEND_PORT}/api/v1",
                "NEXT_PUBLIC_DEMO_MODE": "false",
            }
            frontend = _spawn([npm, "run", "dev"], FRONTEND_DIR, fe_env, "frontend", "frontend.log")
            try:
                _wait_ur(f"http://127.0.0.1:{FRONTEND_PORT}/", timeout=120, min_len=200)
                print(f"✔ dashboard ready → http://localhost:{FRONTEND_PORT}")
            except RuntimeError as exc:
                print(f"! frontend web not ready yet ({exc})")

        if frontend or args.skip_frontend:
            _write_pids()

        if not args.no_open and not args.skip_frontend:
            webbrowser.open(f"http://localhost:{FRONTEND_PORT}/")

        print(
            "\nESS demo stack is running\n"
            "───────────────────────────────\n"
            f"  Dashboard : http://localhost:{FRONTEND_PORT}          (login: {ADMIN_USER} / {ADMIN_PASS})\n"
            f"  API       : http://localhost:{BACKEND_PORT}/api/v1        (docs in dev mode)\n"
            f"  Health    : http://localhost:{BACKEND_PORT}/api/v1/health\n"
            "  Data      : simulated live telemetry arrives a few seconds after login.\n"
            f"  Logs      : .demo/logs/*.log    DB: .demo/demo.db\n"
            "\n  Press Ctrl+C to stop everything."
        )

        while True:
            time.sleep(1.0)
            for label, proc in CHILDREN.items():
                code = proc.poll()
                if code is not None:
                    print(f"\n! {label} exited unexpectedly (code {code}); stopping remaining services")
                    _tail(label)
                    return 1
    except KeyboardInterrupt:
        print("\nStopping demo stack …")
        return 0
    except Exception:
        print("✗ demo failed — stopping children")
        _tail("backend")
        _tail("gateway")
        raise
    finally:
        for label, proc in CHILDREN.items():
            if proc.poll() is None:
                _kill_tree(proc.pid)
        PID_FILE.unlink(missing_ok=True)


def _write_pids() -> None:
    PID_FILE.write_text(
        json.dumps({label: proc.pid for label, proc in CHILDREN.items() if proc.pid is not None}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
