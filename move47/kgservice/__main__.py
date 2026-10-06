"""python3 -m kgservice {backend|client|keepalive|status|stop} ..."""
from __future__ import annotations

import sys

USAGE = """usage: python3 -m kgservice COMMAND ...
  backend   --model M --config C        (inside a Slurm GPU job; see scripts/slurm/kg_backend.sbatch)
  client    analysis -config C -model M [-override-config ...]   (what bin/kg-client runs)
  keepalive --model M [--lead 600] [--max-jobs 2] [--once]
  status                                list backends and kgservice jobs
  stop      [--model M]                 scancel kgservice jobs, SIGTERM local backends"""


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "backend":
        from .backend import main as m
        return m(rest)
    if cmd == "client":
        from .client import main as m
        return m(rest)
    if cmd in ("keepalive", "status", "stop"):
        from .keepalive import main as m
        return m(cmd, rest)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
