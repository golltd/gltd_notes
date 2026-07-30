"""Manage the local GLTD Notes web UI process from the desktop GUI."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

INSTALL_ROOT = Path("/var/PROGRAMAS/gltd_notes")
PID_FILE = Path.home() / ".local" / "share" / "gltd_notes" / "web.pid"
LOG_FILE = Path.home() / ".local" / "share" / "gltd_notes" / "web.log"


def _web_bind(config) -> tuple[str, int]:
    web = (config.data.get("web") or {}) if hasattr(config, "data") else {}
    host = web.get("host") or "127.0.0.1"
    if host in ("0.0.0.0", "::", "") and not web.get("allow_remote"):
        host = "127.0.0.1"
    port = int(web.get("port") or 8766)
    return host, port


def web_url(config) -> str:
    host, port = _web_bind(config)
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{host}:{port}/"


def is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        h = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        with socket.create_connection((h, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_pid() -> Optional[int]:
    try:
        if not PID_FILE.exists():
            return None
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status(config) -> Dict[str, Any]:
    host, port = _web_bind(config)
    url = web_url(config)
    pid = read_pid()
    alive = bool(pid and _pid_alive(pid))
    listening = is_port_open(host if host not in ("0.0.0.0", "::") else "127.0.0.1", port)
    if not alive and listening:
        # process running but not our pid file
        state = "running"
    elif alive and listening:
        state = "running"
    elif alive and not listening:
        state = "starting"
    else:
        state = "stopped"
        pid = None
    return {
        "state": state,
        "running": state == "running",
        "pid": pid,
        "host": host,
        "port": port,
        "url": url,
        "log": str(LOG_FILE),
    }


def start(config) -> Dict[str, Any]:
    st = status(config)
    if st["running"]:
        return st
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(INSTALL_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [
        "python3",
        "-m",
        "gltd_notes",
        "web",
        "--no-browser",
        "--host",
        st["host"] if st["host"] not in ("0.0.0.0", "::") else "127.0.0.1",
        "--port",
        str(st["port"]),
    ]
    logf = open(LOG_FILE, "a", encoding="utf-8")
    logf.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    logf.flush()
    proc = subprocess.Popen(
        cmd,
        cwd=str(INSTALL_ROOT),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid) + "\n")
    # wait briefly for port
    for _ in range(30):
        if is_port_open("127.0.0.1", st["port"]):
            break
        time.sleep(0.1)
    return status(config)


def stop(config) -> Dict[str, Any]:
    pid = read_pid()
    host, port = _web_bind(config)
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    # also free port if something else holds it (best-effort pkill our module)
    if is_port_open("127.0.0.1", port):
        try:
            subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass
    time.sleep(0.2)
    return status(config)


def restart(config) -> Dict[str, Any]:
    stop(config)
    time.sleep(0.3)
    return start(config)
