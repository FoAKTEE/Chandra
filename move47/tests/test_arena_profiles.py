"""Arena script profiles (scripts/arena_env.sh): dry runs of arena_up.sh / arena_down.sh / arena_status.sh.
The default profile (strong net, k1 tiers, port 8765, runs/move47/arena) is unchanged; the ladder profile serves
config/tiers-9x9.json with the b10c128 net on port 8766.  No GPU, nothing started."""
import os
import subprocess
from pathlib import Path

import pytest

from goarena.opponents import load_tiers

ROOT = Path(__file__).resolve().parent.parent
STRONG = "engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz"
SMALL = "engines/models/g170e-b10c128-s1141046784-d204142634.bin.gz"
ADJ = "--adjudicate-winrate 0.01 --adjudicate-lead 20 --adjudicate-moves 4 --adjudicate-after 30"
OVERRIDES = ("ARENA_PROFILE", "ARENA_DIR", "MODEL", "CONFIG", "TIERS", "HOST", "PORT", "REFEREE_VISITS",
             "REVIEW_VISITS", "ADJUDICATE", "RUNS_ROOT")


def _script(name, *args, **env):
    e = {k: v for k, v in os.environ.items() if k not in OVERRIDES}
    e.update(env)
    return subprocess.run(["bash", str(ROOT / "scripts" / name), *args], cwd=ROOT, env=e, capture_output=True,
                          text=True, timeout=60)


def _have(*paths):
    return all((ROOT / p).exists() for p in paths)


needs_files = pytest.mark.skipif(not _have(STRONG, SMALL, "engines/configs/analysis-gpu.cfg"),
                                 reason="engines/ (gitignored) not fetched")


# ------------------------------------------------------------------ arena scripts
@needs_files
def test_arena_up_default_profile_is_unchanged():
    p = _script("arena_up.sh", "--dry-run")
    assert p.returncode == 0, p.stderr
    arena = next(l for l in p.stdout.splitlines() if l.startswith("arena: "))
    keep = next(l for l in p.stdout.splitlines() if l.startswith("keepalive: "))
    assert f"--model {STRONG} --config engines/configs/analysis-gpu.cfg" in keep
    assert "--port 8765 " in arena and "--host 127.0.0.1 " in arena
    assert arena.split("--db ")[1].split()[0].endswith("/runs/move47/arena/arena.db")
    assert f"--katago-model {ROOT}/{STRONG} " in arena and f"--tiers {ROOT}/config/tiers-9x9-kata1.json " in arena
    assert "--move-timeout 3600 --referee-visits 1600 --review-visits 1600 " + ADJ in arena
    assert f"KATAGO_BIN={ROOT}/bin/kg-client" in arena
    assert _script("arena_up.sh", "--profile", "kata1", "--dry-run").stdout == p.stdout
    assert _script("arena_up.sh", "--dry-run", ARENA_PROFILE="kata1").stdout == p.stdout


@needs_files
def test_arena_up_ladder_profile():
    p = _script("arena_up.sh", "--profile", "ladder", "--dry-run")
    assert p.returncode == 0, p.stderr
    arena = next(l for l in p.stdout.splitlines() if l.startswith("arena: "))
    keep = next(l for l in p.stdout.splitlines() if l.startswith("keepalive: "))
    assert f"--model {SMALL} " in keep
    assert "--port 8766 " in arena and arena.split("--db ")[1].split()[0].endswith("/runs/move47/arena-ladder/arena.db")
    assert f"--katago-model {ROOT}/{SMALL} " in arena and f"--tiers {ROOT}/config/tiers-9x9.json " in arena
    assert "/runs/move47/arena-ladder/kg-client.log" in arena
    assert _script("arena_up.sh", "--profile=ladder", "--dry-run").stdout == p.stdout
    # the ladder's rated tiers carry their calibrated Elo
    tiers = load_tiers(ROOT / "config/tiers-9x9.json")
    assert {t: (tiers[t].elo, tiers[t].counts_for_rating) for t in ("lv5", "lv7", "lv8")} == \
        {"lv5": (1259, True), "lv7": (1850, True), "lv8": (2064, True)}


@needs_files
def test_arena_scripts_environment_overrides_win(tmp_path):
    p = _script("arena_up.sh", "--profile", "ladder", "--dry-run", PORT="9001", ARENA_DIR=str(tmp_path / "a"),
                ADJUDICATE="", REVIEW_VISITS="64")
    assert p.returncode == 0, p.stderr
    arena = next(l for l in p.stdout.splitlines() if l.startswith("arena: "))
    assert "--port 9001 " in arena and f"--db {tmp_path}/a/arena.db " in arena and "--review-visits 64" in arena
    assert "adjudicate" not in arena and "adjudication off" in p.stdout
    assert not (tmp_path / "a").exists()                           # a dry run creates nothing


@needs_files
def test_arena_scripts_refuse_bad_input():
    assert _script("arena_up.sh", "--profile", "nope", "--dry-run").returncode == 2
    assert _script("arena_up.sh", "--bogus").returncode == 2
    inside = _script("arena_up.sh", "--dry-run", ARENA_DIR=str(ROOT / "runs-inside"))
    assert inside.returncode == 2 and "outside the Chandra tree" in inside.stderr
    missing = _script("arena_up.sh", "--dry-run", MODEL="engines/models/none.bin.gz")
    assert missing.returncode == 2 and "missing" in missing.stderr


def test_arena_down_and_status_take_the_profile():
    d = _script("arena_down.sh", "--profile", "ladder", "--dry-run")
    assert d.returncode == 0 and "kgb-g170e-b10c128-s1141046784-d204142634" in d.stdout
    assert "/runs/move47/arena-ladder/arena.pid" in d.stdout
    d0 = _script("arena_down.sh", "--dry-run")
    assert d0.returncode == 0 and "kgb-kata1-tf3-b11c768-s11003M-d5973M-7gres" in d0.stdout
    for name in ("arena_up.sh", "arena_down.sh", "arena_status.sh", "arena_env.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)]).returncode == 0
