"""ledger_common — shared helpers for the append-only per-paper ledgers.

Single source for the IO + render scaffolding that `error_database.py`,
`knowledge_database.py`, and `loop_policy.py` previously
each carried their own copy of: UTC timestamping, git stamping, JSONL reads,
CSV `summary.csv` regeneration, the latest-non-amended-per-node collapse,
HTML cell escaping, and the shared ledger HTML CSS/JS assets.

This module has no CLI and owns no schema — each ledger module remains the
canonical spec for its own row shape. The siblings import this by bare name
(they run as scripts with this directory on `sys.path`, or are imported by
bare module name in-process); they bootstrap that path themselves.
"""
from __future__ import annotations

import csv
import hashlib
import html as _html
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from _common.ledgers.txn import ledger_lock, read_lock
else:
    from .txn import ledger_lock, read_lock


# --- timestamp + git ---------------------------------------------------------

def utc_now_iso(timespec: str = "seconds") -> str:
    """ISO-8601 UTC now. `timespec='microseconds'` keeps closely-spaced appends
    orderable (knowledge ledger); 'seconds' is the default (error ledger)."""
    return datetime.now(timezone.utc).isoformat(timespec=timespec)


def git_commit_short(repo_root: str | Path | None = None) -> str:
    cmd = ["git"]
    if repo_root is not None:
        cmd += ["-C", str(repo_root)]
    cmd += ["rev-parse", "--short", "HEAD"]
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unavailable"


# --- JSONL ledger IO ---------------------------------------------------------
#
# Canonical on-disk home: results/ledgers/<db>/paper_<paper>/ — ONE research-
# output tree instead of four top-level `<db>-database/` directories. Legacy
# layouts keep working: if `<db>-database/paper_<paper>/` already exists and
# the canonical dir does not, reads AND appends stay there (no split-brain);
# migrate with `git mv <db>-database/paper_* results/ledgers/<db>/`.

def db_dir(repo_root: str | Path | None, db: str, paper: str) -> Path:
    """The ledger directory for (db, paper): canonical results/ledgers/ home,
    or the legacy `<db>-database/` home when only that exists."""
    root = Path(repo_root) if repo_root else Path.cwd()
    canonical = root / "results" / "ledgers" / db / f"paper_{paper}"
    legacy = root / f"{db}-database" / f"paper_{paper}"
    if legacy.exists() and not canonical.exists():
        return legacy
    return canonical


def iter_paper_dirs(repo_root: str | Path | None, db: str):
    """Yield (paper_id, dir) across BOTH layouts, canonical first, no dupes."""
    root = Path(repo_root) if repo_root else Path.cwd()
    with read_lock(root):
        seen: set[str] = set()
        for base in (root / "results" / "ledgers" / db, root / f"{db}-database"):
            if not base.is_dir():
                continue
            for d in sorted(base.glob("paper_*")):
                paper = d.name[len("paper_"):]
                if d.is_dir() and paper not in seen:
                    seen.add(paper)
                    yield paper, d


def _repo_root(directory: Path) -> Path:
    """Recover the lock root from a canonical or legacy paper directory."""
    directory = directory.resolve()
    if directory.parent.parent.name == "ledgers" and directory.parent.parent.parent.name == "results":
        return directory.parents[3]
    if directory.parent.name.endswith("-database"):
        return directory.parents[1]
    # Standalone callers may use a directory outside either ledger layout.
    return directory


INCOMPLETE_TAIL = "incomplete tail (crash mid-write)"


def _complete_lines(path: Path, encoding: str | None = None) -> tuple[list[bytes], int | None]:
    """Read under the caller's lock; return complete lines and a torn-tail offset.

    Only the final physical line can be recovered. Malformed interior lines
    remain in the returned prefix so readers fail and verification diagnoses
    them. Bytes keep a torn UTF-8 character from hiding the valid prefix.
    """
    if not path.exists():
        return [], None
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    tail = None
    if lines:
        last = lines[-1]
        incomplete = not last.endswith(b"\n")
        if not incomplete and last.strip():
            try:
                json.loads(last.decode(encoding or "utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                incomplete = True
        if incomplete:
            tail = len(data) - len(last)
            lines.pop()
    return [line for line in lines if line.strip()], tail


def _read_rows(path: Path, encoding: str | None = None) -> list[dict[str, Any]]:
    lines, tail = _complete_lines(path, encoding)
    if tail is not None:
        print(f"warning: {INCOMPLETE_TAIL}: ignoring final line in {path}", file=sys.stderr)
    return [json.loads(line.decode(encoding or "utf-8")) for line in lines]


def read_jsonl(repo_root: str | Path | None, db: str, paper: str,
               filename: str, *, encoding: str | None = None) -> list[dict[str, Any]]:
    """Read complete rows under a shared lock; warn and ignore an incomplete tail."""
    with read_lock(repo_root):
        return _read_rows(db_dir(repo_root, db, paper) / filename, encoding)


def flatten_record(d: dict, prefix: str = "") -> dict:
    """Flatten nested dicts to dotted keys; JSON-encode list/tuple values.
    Projects a ledger row into a flat `summary.csv` row."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten_record(v, prefix=f"{key}."))
        elif isinstance(v, (list, tuple)):
            out[key] = json.dumps(v, ensure_ascii=False)
        else:
            out[key] = v
    return out


def regenerate_summary(db_dir: Path, filename: str, order: list[str]) -> None:
    """Rebuild `summary.csv` next to `<db_dir>/<filename>` (a JSONL ledger).
    `order` lists the preferred leading columns; any extra flattened keys are
    appended in sorted order. The derived revision column marks superseded
    rows without changing their hashed payloads. No-op for an empty ledger."""
    with ledger_lock(_repo_root(db_dir)):
        history = _read_rows(db_dir / filename)
        revisions = revision_labels(history)
        rows = [flatten_record({**row, "revision": revisions[row.get("row_hash", "")]})
                for row in history]
        if not rows:
            return
        seen = set().union(*[r.keys() for r in rows])
        cols = [c for c in order if c in seen] + sorted(seen - set(order))
        with (db_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow(r)


# --- tamper-evident hash chain -------------------------------------------------
# Every appended row carries row_hash = sha256(prev_row_hash + canonical(row)).
# "Never delete a row" stops being an honor rule: editing, dropping, or
# reordering any hashed row breaks every hash after it. Legacy rows without
# row_hash are tolerated only as a prefix (pre-chain history).

def _canonical_row_bytes(row: dict[str, Any]) -> bytes:
    return json.dumps({k: v for k, v in row.items() if k != "row_hash"},
                      sort_keys=True, ensure_ascii=False).encode("utf-8")


def chain_append(db_dir: Path, filename: str, row: dict[str, Any]) -> dict[str, Any]:
    """Append and fsync one whole row; recover only an incomplete final line."""
    root = _repo_root(db_dir)
    with ledger_lock(root):
        db_dir.mkdir(parents=True, exist_ok=True)
        jsonl = db_dir / filename
        created = not jsonl.exists()
        lines, tail = _complete_lines(jsonl)
        rows = [json.loads(line) for line in lines]
        prev = (rows[-1].get("row_hash", "") or "") if rows else ""
        row["row_hash"] = hashlib.sha256(prev.encode() + _canonical_row_bytes(row)).hexdigest()
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        if created and db_dir.resolve() != root:
            # mkdir(parents=True) may have created the whole ledger layout.
            # Persist its directory entries too, so fsync of a new paper's
            # leaf directory does not leave its ancestors crash-volatile.
            for parent in db_dir.resolve().parents:
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                if parent == root:
                    break
        fd = os.open(jsonl, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
        try:
            if tail is not None:
                os.ftruncate(fd, tail)
                print(f"warning: {INCOMPLETE_TAIL}: truncating {jsonl} at byte {tail}", file=sys.stderr)
            written = os.write(fd, data)
            if written != len(data):
                raise OSError(f"short ledger write to {jsonl}: {written}/{len(data)} bytes; incomplete tail")
            os.fsync(fd)
        finally:
            os.close(fd)
        if created:
            directory_fd = os.open(db_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return row


def verify_chain(db_dir: Path, filename: str) -> dict[str, Any]:
    """Walk the file's hash chain. Returns {ok, rows, hashed, break_at}."""
    with read_lock(_repo_root(db_dir)):
        return _verify_chain(db_dir / filename)


def _verify_chain(jsonl: Path) -> dict[str, Any]:
    prev = ""
    hashed = 0
    seen_hashed = False
    lines, tail = _complete_lines(jsonl)
    total = len(lines) + (tail is not None)
    for i, line in enumerate(lines):
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"ok": False, "rows": total, "hashed": hashed, "break_at": i,
                    "reason": "unparseable line"}
        rh = row.get("row_hash")
        if rh is None:
            if seen_hashed:
                return {"ok": False, "rows": total, "hashed": hashed, "break_at": i,
                        "reason": "unhashed row after hashed history"}
            continue                      # legacy pre-chain prefix
        expect = hashlib.sha256(prev.encode() + _canonical_row_bytes(row)).hexdigest()
        if rh != expect:
            return {"ok": False, "rows": total, "hashed": hashed, "break_at": i,
                    "reason": "hash mismatch (edited, dropped, or reordered row)"}
        prev = rh
        hashed += 1
        seen_hashed = True
    if tail is not None:
        return {"ok": False, "rows": total, "hashed": hashed, "break_at": len(lines),
                "reason": INCOMPLETE_TAIL}
    return {"ok": True, "rows": total, "hashed": hashed, "break_at": None}


LEDGER_FILENAMES = {"error": "trials.jsonl", "result": "results.jsonl",
                    "knowledge": "nodes.jsonl", "claim": "entries.jsonl"}


def verify_all_chains(repo_root: str | Path | None) -> dict[str, Any]:
    """Verify every ledger of every paper in both layouts."""
    breaks = []
    with read_lock(repo_root):
        for db, filename in LEDGER_FILENAMES.items():
            for paper, d in iter_paper_dirs(repo_root, db):
                v = verify_chain(d, filename)
                if not v["ok"]:
                    breaks.append({"db": db, "paper": paper, **v})
    return {"ok": not breaks, "breaks": breaks}


def latest_per_node(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest active row per node_id, in append order (last wins).

    Legacy amended pointers are ignored. Retirement hides the entire node,
    including its older active rows; a subsequent active append can revive it.
    """
    by_node: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("status") == "amended":
            continue
        nid = r.get("node_id")
        if nid is not None:
            by_node[nid] = r
    return [r for r in by_node.values() if r.get("status") != "retired"]


_OBSERVED_FIELDS = frozenset({
    "timestamp", "git_commit", "row_hash", "actor_role", "node_seq",
    "evidence_sha256", "verification_run", "admission_flags",
})


def request_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Submitted payload for replay comparison, excluding admission observations.

    Status, semantic fields, routing metadata, verifier commands, and supersedes
    all participate. A fresh verification run must not manufacture a new request.
    """
    payload = {k: v for k, v in row.items() if k not in _OBSERVED_FIELDS}
    if isinstance(payload.get("verifier_result"), dict):
        payload["verifier_result"] = {k: v for k, v in payload["verifier_result"].items()
                                      if k != "execution"}
    return payload


def json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/number equality conflation."""
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def revision_labels(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Derived view labels; never mutate or persist annotations on hashed rows."""
    successors: dict[str, list[str]] = {}
    for row in rows:
        if row.get("supersedes"):
            successors.setdefault(row["supersedes"], []).append(row.get("row_hash", ""))
    labels = {}
    for row in rows:
        row_hash = row.get("row_hash", "")
        parts = [f"row {row_hash}"] if row_hash else []
        if row.get("supersedes"):
            parts.append(f"supersedes {row['supersedes']}")
        if row_hash in successors:
            parts.append("superseded by " + ", ".join(successors[row_hash]))
        labels[row_hash] = "; ".join(parts)
    return labels


def max_iteration(rows: list[dict[str, Any]]) -> int | None:
    """Highest integer `iteration` across rows, or None if absent."""
    iters = [r.get("iteration") for r in rows if isinstance(r.get("iteration"), int)]
    return max(iters) if iters else None


# --- HTML render assets (shared by the two ledger table views) ---------------

_CSS_TOP = """
:root{color-scheme:light;
  --plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);
  --accent:#2a78d6;--adv:#a45d00;--hover:rgba(11,11,11,.04)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
  --accent:#3987e5;--adv:#fab219;--hover:rgba(255,255,255,.05)}}
:root[data-theme=dark]{color-scheme:dark;
  --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
  --accent:#3987e5;--adv:#fab219;--hover:rgba(255,255,255,.05)}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1500px;
  margin:0 auto;padding:20px 24px 48px;background:var(--plane);color:var(--ink);font-size:14px}
h1{font-size:19px;margin:0 0 .2em}
.subtitle{color:var(--ink2);margin-top:0;font-size:12.5px}
.summary{background:var(--surface);border:1px solid var(--border);padding:.6em 1em;
  border-radius:9px;margin:1em 0;font-size:13px}
.summary span{margin-right:1.5em;white-space:nowrap}
.summary strong{color:var(--ink2);font-weight:600}
.controls{margin:1em 0}
input.search{width:30em;max-width:100%;padding:.45em .7em;font-size:13px;font-family:inherit;
  border:1px solid var(--border);border-radius:7px;background:var(--surface);color:var(--ink)}
input.search:focus{outline:2px solid var(--accent);outline-offset:-1px}
table{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--surface)}
th,td{text-align:left;padding:.5em .7em;border-bottom:1px solid var(--grid);vertical-align:top}
th{background:var(--surface);cursor:pointer;user-select:none;position:sticky;top:0;
  border-bottom:1px solid var(--baseline);font-size:11.5px;color:var(--ink2)}
th:hover{color:var(--ink)}
th[data-sort=asc]::after{content:" \\25B2";font-size:9px;color:var(--muted)}
th[data-sort=desc]::after{content:" \\25BC";font-size:9px;color:var(--muted)}
tbody tr:hover{filter:brightness(.985)}
"""

# The per-module `tr.<status>` tints are light-mode pastels; in dark mode they
# are neutralized (higher specificity than the module's `tr.<status>` rules)
# and the status column's text carries the state on its own.
_CSS_BOTTOM = """.cell-wrap{max-width:24em;overflow-wrap:break-word}
.cell-mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px}
.tag{display:inline-block;padding:.05em .5em;border-radius:99px;background:var(--hover);
  border:1px solid var(--border);font-size:11px;margin-right:.2em}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.muted{color:var(--muted)}
@media (prefers-color-scheme:dark){
  :root:not([data-theme=light]) tbody tr{background:transparent;color:inherit}
  :root:not([data-theme=light]) tbody tr:hover{filter:none;background:var(--hover)}}
:root[data-theme=dark] tbody tr{background:transparent;color:inherit}
:root[data-theme=dark] tbody tr:hover{filter:none;background:var(--hover)}
"""

LEDGER_JS = """
(function(){
var s=document.getElementById('search'),t=document.getElementById('rows'),tb=t.tBodies[0];
s.addEventListener('input',function(){var q=s.value.toLowerCase();
  Array.from(tb.rows).forEach(function(r){r.style.display=r.textContent.toLowerCase().includes(q)?'':'none';});
});
Array.from(t.tHead.rows[0].cells).forEach(function(th,i){th.addEventListener('click',function(){
  var asc=th.dataset.sort!=='asc';
  Array.from(tb.rows).sort(function(a,b){
    var av=a.cells[i].textContent.trim(),bv=b.cells[i].textContent.trim();
    var an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv):bv.localeCompare(av);
  }).forEach(function(r){tb.appendChild(r);});
  Array.from(t.tHead.rows[0].cells).forEach(function(x){x.removeAttribute('data-sort');});
  th.dataset.sort=asc?'asc':'desc';
});});
})();
"""


def ledger_css(status_rules: str, *, advance: bool = False) -> str:
    """Assemble the ledger CSS: shared skeleton + the caller's per-row
    `tr.<status>` tint block, plus the knowledge ledger's `.advance` rule."""
    css = _CSS_TOP + status_rules + _CSS_BOTTOM
    if advance:
        css += ".advance{color:var(--adv)}\n"
    return css


def esc_cell(v: Any, *, bool_lower: bool = False) -> str:
    """HTML-escape a table cell value; None -> muted dash, list/tuple ->
    comma-joined, dict -> JSON. `bool_lower=True` renders bools as
    'true'/'false' (knowledge ledger); the default renders via str()."""
    if v is None:
        return '<span class="muted">—</span>'
    if isinstance(v, (list, tuple)):
        return ", ".join(_html.escape(str(x)) for x in v)
    if isinstance(v, dict):
        return _html.escape(json.dumps(v, ensure_ascii=False))
    if bool_lower and isinstance(v, bool):
        return "true" if v else "false"
    return _html.escape(str(v))
