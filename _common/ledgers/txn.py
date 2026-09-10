"""Repository-wide advisory transactions for the four JSONL ledgers.

Write protocol (including batches):
  (a) Run each row's verification.command OUTSIDE the lock: it may take
      minutes, read ledgers, or append its own rows. Retain its outcome.
  (b) Take the repository's exclusive ledger_lock.
  (c) Re-validate the read set against CURRENT files: dependencies,
      predecessors, settling references, evidence hashes, checked/solid
      rules, and delegation policy. Never re-run a pre-lock verification.
  (d) Allocate node_seq and resolve batch deduplication under this lock.
  (e) chain_append writes one complete line with os.write, then fsyncs the
      file and, on creation, its directory. An incomplete tail is truncated
      under the same lock before appending, with a diagnostic on stderr.
  (f) Regenerate summary.csv before releasing the lock.
  (g) Release. A batch holds one critical section; a rejected row stops it
      with its already admitted prefix retained (there is no rollback).

Readers use read_lock for a shared flock. Both layouts ALWAYS lock at
results/ledgers/.lock. Locks nest within the owning thread/process; a shared
lock inside an exclusive one never downgrades it. Read-to-write upgrades are
rejected: release the read lock and re-validate after acquiring the writer
lock. Append APIs with verification commands must be called without an
enclosing lock; they manage the verification/commit boundary themselves.
Threads serialize locally; after fork a child must acquire its own
flock. This is a cooperative, local-filesystem protocol, not a distributed
lock or protection against writers that bypass it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import math
import os
from pathlib import Path
import threading
import time

LOCK_PATH = "results/ledgers/.lock"
TIMEOUT_ENV = "CHANDRA_LOCK_TIMEOUT_S"
DEFAULT_TIMEOUT_S = 120


class LedgerLockTimeout(TimeoutError):
    """The repository ledger lock could not be acquired before its deadline."""


@dataclass
class _LockState:
    mutex: threading.RLock = field(default_factory=threading.RLock)
    fd: int | None = None
    depth: int = 0
    shared: bool = False
    owner: int | None = None


_states: dict[Path, _LockState] = {}
_states_guard = threading.Lock()


def _after_fork() -> None:
    global _states, _states_guard
    for state in _states.values():
        if state.fd is not None:
            # Close the child's copy without LOCK_UN, which would release
            # the parent's flock on the inherited open file description.
            os.close(state.fd)
    _states = {}
    _states_guard = threading.Lock()


os.register_at_fork(after_in_child=_after_fork)


def holds_lock(repo_root: str | Path | None) -> bool:
    """Whether the calling thread already holds this repository's lock."""
    root = (Path(repo_root) if repo_root else Path.cwd()).resolve()
    with _states_guard:
        state = _states.get(root / LOCK_PATH)
        return state is not None and state.depth > 0 and state.owner == threading.get_ident()


@contextmanager
def _lock(repo_root: str | Path | None, *, shared: bool):
    pid = os.getpid()
    root = (Path(repo_root) if repo_root else Path.cwd()).resolve()
    path = root / LOCK_PATH
    timeout = float(os.environ.get(TIMEOUT_ENV, DEFAULT_TIMEOUT_S))
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError(f"{TIMEOUT_ENV} must be a finite, non-negative number")
    deadline = time.monotonic() + timeout
    with _states_guard:
        state = _states.setdefault(path, _LockState())

    def expired():
        return LedgerLockTimeout(
            f"timed out after {timeout:g}s acquiring {'shared' if shared else 'exclusive'} "
            f"ledger lock {path} ({TIMEOUT_ENV})")

    if not state.mutex.acquire(timeout=max(0, deadline - time.monotonic())):
        raise expired()
    try:
        if state.depth:
            if state.shared and not shared:
                raise RuntimeError("cannot upgrade a ledger read lock; release it and re-validate under ledger_lock")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, (os.O_RDONLY if shared else os.O_RDWR) | os.O_CREAT, 0o666)
            state.fd = fd
            try:
                while True:
                    try:
                        fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise expired()
                        time.sleep(min(0.01, remaining))
            except BaseException:
                os.close(fd)
                state.fd = None
                raise
            state.shared = shared
            state.owner = threading.get_ident()
        state.depth += 1
        try:
            yield
        finally:
            # A forked child has already closed the inherited fd and reset
            # its registry. The old descriptor number may now name a new file.
            if os.getpid() == pid:
                state.depth -= 1
                if state.depth == 0:
                    try:
                        fcntl.flock(state.fd, fcntl.LOCK_UN)
                    finally:
                        os.close(state.fd)
                        state.fd = None
                        state.owner = None
    finally:
        if os.getpid() == pid:
            state.mutex.release()


def ledger_lock(repo_root: str | Path | None):
    """Exclusive, re-entrant repository lock; timeout uses CHANDRA_LOCK_TIMEOUT_S."""
    return _lock(repo_root, shared=False)


def read_lock(repo_root: str | Path | None):
    """Shared repository lock; safe to nest inside ledger_lock or read_lock."""
    return _lock(repo_root, shared=True)
