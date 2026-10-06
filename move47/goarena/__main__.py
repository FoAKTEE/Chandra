"""goarena command line:

  python -m goarena serve      run the arena HTTP server
  python -m goarena create-run register a run and print its token
  python -m goarena calibrate  round-robin the opponent tiers and fit their Elo
  python -m goarena review     (re)compute engine reviews of finished games
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import secrets
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _katago_from_args(a):
    if a.no_katago:
        return None
    from .katago import KataGo, KataGoConfig
    return KataGo(KataGoConfig(binary=a.katago_bin, model=a.katago_model, config=a.katago_config))


def _add_engine_args(p):
    p.add_argument("--katago-bin", default=os.environ.get("KATAGO_BIN", str(ROOT / "engines/katago")))
    p.add_argument("--katago-model", default=os.environ.get(
        "KATAGO_MODEL", str(ROOT / "engines/models/g170e-b10c128-s1141046784-d204142634.bin.gz")))
    p.add_argument("--katago-config", default=os.environ.get("KATAGO_CONFIG", str(ROOT / "engines/configs/analysis.cfg")))
    p.add_argument("--no-katago", action="store_true", help="run without KataGo (random/greedy tiers, Tromp-Taylor scoring)")
    p.add_argument("--tiers", default=str(ROOT / "config/tiers-9x9.json"))


def _settings(a):
    from .arena import ArenaSettings
    from .opponents import load_tiers
    adj = {k: getattr(a, k) for k in ("adjudicate_winrate", "adjudicate_lead", "adjudicate_moves",
                                       "adjudicate_after") if getattr(a, k, None) is not None}
    return ArenaSettings(size=a.size, komi=a.komi, max_illegal_per_game=a.max_illegal,
                         move_timeout_s=a.move_timeout, referee_visits=a.referee_visits,
                         review_visits=a.review_visits, rating_window=a.rating_window,
                         allow_color_choice=not a.fixed_colors, tiers=load_tiers(a.tiers), **adj)


def cmd_serve(a):
    from .arena import Arena
    from .server import serve
    from .store import Store
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    admin = a.admin_token or os.environ.get("GOARENA_ADMIN_TOKEN") or "adm_" + secrets.token_urlsafe(18)
    store = Store(a.db)
    kg = _katago_from_args(a)
    arena = Arena(store, _settings(a), kg)
    web = a.web if a.web else (str(ROOT / "web") if (ROOT / "web/index.html").exists() else None)
    httpd = serve(arena, a.host, a.port, admin, a.viewer_token or os.environ.get("GOARENA_VIEWER_TOKEN", ""), web)
    print(f"goarena listening on http://{a.host}:{a.port}  (db={a.db}, katago={'on' if kg else 'off'}, "
          f"tiers={','.join(arena.opponents)})", flush=True)
    st = arena.s
    print("adjudication: " + (f"on (agent winrate < {st.adjudicate_winrate:g} and lead < -{st.adjudicate_lead:g} "
                              f"on {st.adjudicate_moves} consecutive opponent moves after ply {st.adjudicate_after})"
                              if st.adjudication_on else "off"), flush=True)
    if not (a.admin_token or os.environ.get("GOARENA_ADMIN_TOKEN")):
        print(f"admin token: {admin}", flush=True)

    def _stop(*_):
        arena.stop()
        if kg:
            kg.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _stop()


def cmd_create_run(a):
    import urllib.request
    body = {"name": a.name, "model": a.model, "harness": a.harness, "reasoning": a.reasoning,
            "context": a.context, "notes": a.notes, "target_games": a.games,
            "config": json.loads(a.config) if a.config else {}}
    if a.id:
        body["id"] = a.id
    req = urllib.request.Request(a.url.rstrip("/") + "/api/admin/runs", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json",
                                                         "Authorization": f"Bearer {a.admin_token or os.environ.get('GOARENA_ADMIN_TOKEN', '')}"})
    with urllib.request.urlopen(req) as r:
        out = json.loads(r.read())
    print(json.dumps(out["run"], indent=2))


def cmd_calibrate(a):
    """Round-robin between tiers; Bradley-Terry fit anchored at random=0."""
    from .board import BLACK, WHITE, Board
    from .opponents import build_opponent, load_tiers
    from .rating import fit_pool
    from .referee import score_final
    tiers = load_tiers(a.tiers)
    names = [n for n in (a.only.split(",") if a.only else tiers)]
    kg = _katago_from_args(a)
    rng = random.Random(a.seed)
    bots = {n: build_opponent(tiers[n], kg, random.Random(rng.random())) for n in names}
    pairs: list[tuple[str, str, float]] = []
    schedule = []
    for i, x in enumerate(names):
        for j in range(i + 1, min(len(names), i + 1 + a.span)):
            schedule.append((x, names[j]))
    t0 = time.time()
    log_f = open(a.log, "a") if a.log else None
    for x, y in schedule:
        sx = 0.0
        for k in range(a.games):
            black, white = (x, y) if k % 2 == 0 else (y, x)
            b = Board(a.size, a.komi)
            st = {BLACK: {}, WHITE: {}}
            winner = None
            while True:
                who = black if b.to_play == BLACK else white
                dec = bots[who].safe_genmove(b, st[b.to_play])
                if dec.resign:
                    winner = WHITE if b.to_play == BLACK else BLACK
                    break
                b.play(dec.point)
                if b.consecutive_passes() >= 2 or len(b.moves) >= 3 * a.size * a.size:
                    winner = score_final(b, kg, a.referee_visits)["winner"]
                    break
            win_name = black if winner == BLACK else white
            s = 1.0 if win_name == x else 0.0
            sx += s
            pairs.append((x, y, s))
            if log_f:
                log_f.write(json.dumps({"black": black, "white": white, "winner": win_name, "moves": len(b.moves)}) + "\n")
                log_f.flush()
        print(f"{x:>8} vs {y:<8} {sx:.0f}/{a.games}  ({time.time() - t0:.0f}s)", flush=True)
    fit = fit_pool(pairs, anchor=names[0], anchor_elo=0.0)
    print("\nCalibrated ratings (anchor %s = 0):" % names[0])
    for n in names:
        r, se = fit[n]
        print(f"  {n:<8} {r:7.0f} ± {se:.0f}")
    if a.write:
        data = json.loads(Path(a.tiers).read_text())
        for n in names:
            data["tiers"][n]["elo"] = round(fit[n][0])
            data["tiers"][n]["elo_se"] = round(fit[n][1])
        data["_calibration"] = {"date": time.strftime("%Y-%m-%d"), "games_per_pair": a.games, "span": a.span,
                                "size": a.size, "komi": a.komi, "anchor": names[0]}
        Path(a.write).write_text(json.dumps(data, indent=2) + "\n")
        print(f"wrote {a.write}")
    if kg:
        kg.close()


def cmd_review(a):
    from .arena import Arena
    from .store import Store
    store = Store(a.db)
    arena = Arena(store, _settings(a), _katago_from_args(a))
    ids = [g["id"] for g in store.q("SELECT id FROM games WHERE status='finished'" +
                                     ("" if a.all else " AND review IS NULL"))]
    for gid in ids:
        print(gid, arena.review_game(gid), flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="goarena")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--db", default="goarena.db")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--admin-token", default="")
    s.add_argument("--viewer-token", default="")
    s.add_argument("--web", default="")
    _add_engine_args(s)
    for sp in (s,):
        sp.add_argument("--size", type=int, default=9)
        sp.add_argument("--komi", type=float, default=7.5)
        sp.add_argument("--max-illegal", type=int, default=10)
        sp.add_argument("--move-timeout", type=float, default=3600)
        sp.add_argument("--referee-visits", type=int, default=300)
        sp.add_argument("--review-visits", type=int, default=64)
        sp.add_argument("--rating-window", type=int, default=50)
        sp.add_argument("--fixed-colors", action="store_true")
        sp.add_argument("--adjudicate-winrate", type=float, default=0.0,
                        help="adjudicate decided games: agent winrate threshold, e.g. 0.01 (default 0 = off)")
        sp.add_argument("--adjudicate-lead", type=float, default=20.0,
                        help="... and the agent's score lead must be below minus this many points (default 20)")
        sp.add_argument("--adjudicate-moves", type=int, default=4,
                        help="... on this many consecutive opponent moves (default 4)")
        sp.add_argument("--adjudicate-after", type=int, default=30,
                        help="... counting only opponent moves after this ply (default 30)")
    s.set_defaults(fn=cmd_serve)

    c = sub.add_parser("create-run")
    c.add_argument("--url", default=os.environ.get("GOARENA_URL", "http://127.0.0.1:8765"))
    c.add_argument("--admin-token", default="")
    c.add_argument("--name", required=True)
    c.add_argument("--id", default="")
    c.add_argument("--model", default="")
    c.add_argument("--harness", default="")
    c.add_argument("--reasoning", default="")
    c.add_argument("--context", default="")
    c.add_argument("--notes", default="")
    c.add_argument("--games", type=int, default=200)
    c.add_argument("--config", default="", help='JSON, e.g. {"opponents": ["easy","medium"]}')
    c.set_defaults(fn=cmd_create_run)

    k = sub.add_parser("calibrate")
    _add_engine_args(k)
    k.add_argument("--games", type=int, default=20, help="games per pairing")
    k.add_argument("--span", type=int, default=2, help="pair each tier with the next N tiers")
    k.add_argument("--only", default="", help="comma-separated tier subset, weakest first")
    k.add_argument("--size", type=int, default=9)
    k.add_argument("--komi", type=float, default=7.5)
    k.add_argument("--referee-visits", type=int, default=200)
    k.add_argument("--seed", type=int, default=1)
    k.add_argument("--log", default="")
    k.add_argument("--write", default="", help="write calibrated tier file here")
    k.set_defaults(fn=cmd_calibrate)

    r = sub.add_parser("review")
    r.add_argument("--db", default="goarena.db")
    r.add_argument("--all", action="store_true")
    _add_engine_args(r)
    r.add_argument("--size", type=int, default=9)
    r.add_argument("--komi", type=float, default=7.5)
    r.add_argument("--max-illegal", type=int, default=10)
    r.add_argument("--move-timeout", type=float, default=3600)
    r.add_argument("--referee-visits", type=int, default=300)
    r.add_argument("--review-visits", type=int, default=100)
    r.add_argument("--rating-window", type=int, default=50)
    r.add_argument("--fixed-colors", action="store_true")
    r.set_defaults(fn=cmd_review)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
