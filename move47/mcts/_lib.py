"""Build and load the C core (move47/mcts/csrc/*.c) with ctypes.

The shared library is compiled on first import into ``move47/mcts/.build/`` (gitignored), named by
a hash of the sources, the compiler flags and the compiler version, so an edited source or a
different compiler triggers a rebuild and a stale library is never loaded.  Concurrent first
imports (pytest workers, search threads in several processes) serialise on a file lock.

    python3 -m mcts build            # the same build, explicitly (prints the library path)

Environment: MCTS_CC (compiler, default gcc), MCTS_BUILD_DIR (output directory).

Two handles to the same library: ``lib`` (ctypes.CDLL, releases the GIL during the call; used for
the long calls: tree search, playouts) and ``plib`` (ctypes.PyDLL, keeps the GIL; used for the
many tiny board calls where releasing and re-taking the GIL would cost more than the call).
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "csrc"
BUILD = Path(os.environ.get("MCTS_BUILD_DIR", HERE / ".build"))
CC = os.environ.get("MCTS_CC", "gcc")
CFLAGS = ["-O3", "-march=x86-64-v2", "-std=gnu11", "-Wall", "-Wextra", "-fPIC", "-shared", "-pthread"]
LIBS = ["-lm"]


class BuildError(RuntimeError):
    pass


def _sources() -> list[Path]:
    return sorted(SRC.glob("*.c")) + sorted(SRC.glob("*.h"))


def _cc_version() -> str:
    try:
        return subprocess.run([CC, "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError) as e:
        raise BuildError(f"the C compiler '{CC}' is not usable ({e}); install gcc or set MCTS_CC") from e


def build_id() -> str:
    h = hashlib.sha256()
    for p in _sources():
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    h.update(" ".join(CFLAGS + LIBS).encode())
    h.update(_cc_version().encode())
    return h.hexdigest()[:16]


def build(force: bool = False, verbose: bool = False) -> Path:
    """Compile the library if it is missing (or force); return its path."""
    bid = build_id()
    out = BUILD / f"libmcts-{bid}.so"
    if out.exists() and not force:
        return out
    BUILD.mkdir(parents=True, exist_ok=True)
    with open(BUILD / ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if out.exists() and not force:
            return out
        tmp = BUILD / f".libmcts-{bid}.{os.getpid()}.so"
        cmd = [CC, *CFLAGS, "-o", str(tmp), *[str(p) for p in sorted(SRC.glob("*.c"))], *LIBS]
        if verbose:
            print(" ".join(cmd), file=sys.stderr)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise BuildError(f"building the MCTS core failed:\n$ {' '.join(cmd)}\n{r.stderr}")
        os.replace(tmp, out)
        for old in BUILD.glob("libmcts-*.so"):     # stale builds (a mapped .so survives unlinking)
            if old != out:
                old.unlink(missing_ok=True)
    return out


_P = ctypes.c_void_p
_I = ctypes.c_int
_I64 = ctypes.c_int64
_U64 = ctypes.c_uint64
_F = ctypes.c_float
_D = ctypes.c_double

_SIGS = {
    # name: (restype, argtypes)
    "mc_init": (None, []),
    "mc_board_sizeof": (_I, []),
    "mc_n_patterns": (_I, []),
    "mc_n_features": (_I, []),
    "mc_pattern_code_at": (_I, [_I]),
    "mc_pattern_index_of": (_I, [_I]),
    "mcb_clear": (None, [_P, _I, _F]),
    "mcb_load": (_I, [_P, _I, _F, _P, _I, _I, _I, _I, _I]),
    "mcb_cells": (None, [_P, _P]),
    "mcb_info": (None, [_P, _P]),
    "mcb_komi": (_F, [_P]),
    "mcb_key": (_U64, [_P]),
    "mcb_hash": (_U64, [_P]),
    "mcb_play": (_I, [_P, _I]),
    "mcb_legal": (_I, [_P, _I]),
    "mcb_legal_moves": (_I, [_P, _P]),
    "mcb_score": (_F, [_P]),
    "mcb_is_eye": (_I, [_P, _I, _I]),
    "mcb_features": (_I, [_P, _I, _I, _P]),
    "mcb_logits": (_I, [_P, _P, _I, _P, _P]),
    "mcb_playout": (_I, [_P, _P, _U64, _I, _P]),
    "mcb_playouts": (_I64, [_P, _P, _U64, _I, _P]),
    "mc_policy_new": (_P, []),
    "mc_policy_free": (None, [_P]),
    "mc_policy_set": (None, [_P, _P, _I, _D, _D, _I, _I]),
    "mc_now_ns": (_I64, []),
    "mc_tree_new": (_P, [_I]),
    "mc_tree_free": (None, [_P]),
    "mc_tree_attach": (None, [_P, _P, _I64, _I64]),
    "mc_tree_rebuild_tt": (_I, [_P]),
    "mc_tree_set_root": (None, [_P, ctypes.c_int32, _P]),
    "mc_tree_set_history": (_I, [_P, _P, _I]),
    "mc_tree_set_policy": (None, [_P, _P, _I, _D, _D, _I, _I]),
    "mc_tree_set_limits": (None, [_P, _I64, _I64]),
    "mc_tree_set_stop": (None, [_P, _I]),
    "mc_tree_run": (_I, [_P, _P]),
    "mc_thread_new": (_P, [_U64]),
    "mc_thread_free": (None, [_P]),
    "mc_tree_find": (ctypes.c_int32, [_P, _U64]),
    "mc_tree_node_for": (ctypes.c_int32, [_P, _P]),
    "mc_tree_expand": (_I, [_P, ctypes.c_int32, _P, _P]),
    "mc_tree_merge_priors": (_I, [_P, ctypes.c_int32, _P, _P, _I, _D]),
    "mc_tree_backup_ext": (_I, [_P, _P, _I, _D, _I]),
    "mc_tree_pop_event": (_I, [_P, _P, _P, _P, _P]),
    "mc_tree_clear_events": (_I, [_P]),
    "mc_tree_mark": (_I64, [_P, ctypes.c_int32, _P]),
    "mc_tree_reach": (_I64, [_P, ctypes.c_int32, _P, _I64]),
    "mc_tree_adjust_ext": (_I, [_P, _P, _I, _D, _D]),
    "mc_tree_rearm": (_I, [_P, ctypes.c_int32]),
    "mc_tree_set_root_cls": (_I, [_P, _P, _P, _I]),
    "mc_ev_path_max": (_I, []),
    # rules (mcts-llm-hl)
    "mc_rules_new": (_P, []),
    "mc_rules_free": (None, [_P]),
    "mc_rules_load": (_I, [_P, _P, _I, _P]),
    "mc_rule_ints": (_I, []),
    "mc_max_rules": (_I, []),
    "mcb_rule_hits": (_I, [_P, _P, _P, _I, _P, _P, _I]),
    "mcb_logits_r": (_I, [_P, _P, _I, _P, _P, _P]),
    "mc_tree_set_rules": (_I, [_P, _P, _I, _P]),
}


def _bind(dll):
    for name, (res, args) in _SIGS.items():
        f = getattr(dll, name)
        f.restype = res
        f.argtypes = args
    return dll


def load():
    path = build()
    lib = _bind(ctypes.CDLL(str(path)))
    plib = _bind(ctypes.PyDLL(str(path)))
    plib.mc_init()
    return path, lib, plib


LIB_PATH, lib, plib = load()
BOARD_BYTES = plib.mc_board_sizeof()
N_PATTERNS = plib.mc_n_patterns()
N_FEATURES = plib.mc_n_features()
EV_PATH_MAX = plib.mc_ev_path_max()
RULE_INTS = plib.mc_rule_ints()
MAX_RULES = plib.mc_max_rules()
