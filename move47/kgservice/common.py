"""Shared helpers: paths, rendezvous files, liveness, logging."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
PROTO = 1
DEFAULT_MODEL = "engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz"
DEFAULT_CONFIG = "engines/configs/analysis-gpu.cfg"
SBATCH_SCRIPT = ROOT / "scripts/slurm/kg_backend.sbatch"
JOB_PREFIX = "kgb-"


def run_dir() -> Path:
    """Rendezvous directory (override with KGSERVICE_RUN_DIR, e.g. in tests)."""
    d = os.environ.get("KGSERVICE_RUN_DIR")
    return Path(d) if d else ROOT / "engines/run/backends"


def ensure_private_dir(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def model_key(model: str) -> str:
    """Backends and clients match on the model file's basename."""
    return os.path.basename(str(model).rstrip("/"))


def job_name(model: str) -> str:
    stem = model_key(model)
    for ext in (".bin.gz", ".txt.gz", ".gz", ".bin"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    return JOB_PREFIX + stem


def write_json_private(path: Path, obj: dict) -> None:
    """Atomically write a mode-600 JSON file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_backends(d: Optional[Path] = None) -> list[dict]:
    """All readable rendezvous files; each dict gets `_path` and `_mtime`."""
    d = d or run_dir()
    out = []
    try:
        paths = sorted(d.glob("*.json"))
    except OSError:
        return out
    for p in paths:
        try:
            info = json.loads(p.read_text())
            st = p.stat()
        except (OSError, ValueError):
            continue
        if isinstance(info, dict) and isinstance(info.get("id"), str):
            info["_path"], info["_mtime"] = str(p), st.st_mtime
            out.append(info)
    return out


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def backend_alive(info: dict) -> bool:
    """Best-effort liveness: the pid check only means something on the backend's own host."""
    if info.get("hostname") != socket.gethostname():
        return True
    return pid_alive(info.get("pid"))


def parse_slurm_time(s: str) -> Optional[float]:
    s = (s or "").strip()
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def fmt_left(deadline, now: Optional[float] = None) -> str:
    if not deadline:
        return "inf"
    return f"{deadline - (now or time.time()):.0f}s"


class Log:
    """Timestamped lines on stderr (and appended to $KGSERVICE_LOG when set)."""

    def __init__(self, role: str):
        self.role = role
        self.path = os.environ.get("KGSERVICE_LOG")

    def __call__(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} kgservice-{self.role}[{os.getpid()}]: {msg}"
        try:
            print(line, file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass
        if self.path:
            try:
                with open(self.path, "a") as f:
                    f.write(line + "\n")
            except OSError:
                pass
