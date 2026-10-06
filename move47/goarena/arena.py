"""Game manager: the rules of the benchmark live here, independent of HTTP."""
from __future__ import annotations

import json
import logging
import queue
import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .board import BLACK, WHITE, Board, IllegalMove, coord_to_point, point_to_coord
from .katago import KataGo
from .opponents import Opponent, TierSpec, build_opponent
from .rating import journey, phase_table, run_summary
from .referee import result_string, review_moves, score_final, summarize_review
from .sgf import write_sgf
from .store import Store
from .view import board_text, result_text

log = logging.getLogger("goarena")


class ArenaError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class ArenaSettings:
    size: int = 9
    komi: float = 7.5
    max_illegal_per_game: int = 10
    move_timeout_s: float = 3600.0        # agent inactivity -> loss by timeout
    move_cap_factor: float = 3.0          # max plies = factor * size^2
    referee_visits: int = 300
    review_visits: int = 64                # 0 disables post-game engine review
    rating_window: int = 50
    allow_color_choice: bool = True
    tiers: dict[str, TierSpec] = field(default_factory=dict)
    # Adjudication (off while adjudicate_winrate <= 0): the game ends as an agent loss when, on
    # `adjudicate_moves` consecutive opponent moves played after ply `adjudicate_after`, the KataGo
    # opponent's own search gave the agent a winrate below `adjudicate_winrate` AND a score lead
    # below -`adjudicate_lead`.  Only numbers the opponent computed for its genmove are used.
    adjudicate_winrate: float = 0.0
    adjudicate_lead: float = 20.0
    adjudicate_moves: int = 4
    adjudicate_after: int = 30

    @property
    def adjudication_on(self) -> bool:
        return self.adjudicate_winrate > 0 and self.adjudicate_moves > 0

    @property
    def rated_tiers(self) -> set[str]:
        return {n for n, t in self.tiers.items() if t.counts_for_rating}

    @property
    def tier_elo(self) -> dict[str, float]:
        return {n: t.elo for n, t in self.tiers.items()}


class Arena:
    def __init__(self, store: Store, settings: ArenaSettings, katago: Optional[KataGo] = None,
                 seed: Optional[int] = None):
        self.store, self.s, self.kg = store, settings, katago
        self.rng = random.Random(seed)
        self.boards: dict[int, Board] = {}
        self.opp_state: dict[int, dict] = {}
        self._run_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        self.opponents: dict[str, Opponent] = {}
        for name, spec in settings.tiers.items():
            try:
                self.opponents[name] = build_opponent(spec, katago, random.Random(self.rng.random()))
            except RuntimeError as e:
                log.warning("tier %s disabled: %s", name, e)
        self._review_q: "queue.Queue[int]" = queue.Queue()
        self._stop = threading.Event()
        self._restore()
        threading.Thread(target=self._review_worker, daemon=True, name="reviewer").start()
        threading.Thread(target=self._reaper, daemon=True, name="reaper").start()

    # ------------------------------------------------------------------ util
    def _lock(self, run_id: str) -> threading.Lock:
        with self._locks_lock:
            return self._run_locks.setdefault(run_id, threading.Lock())

    def _restore(self) -> None:
        now = time.time()
        for g in self.store.all_active_games():
            try:
                b = Board(g["size"], g["komi"])
                for m in self.store.game_moves(g["id"]):
                    b.play(coord_to_point(m["coord"], g["size"]), BLACK if m["color"] == "B" else WHITE)
            except (ValueError, IllegalMove) as e:
                log.error("cannot restore game %s (%s); marking it abandoned", g["id"], e)
                self.store.x("UPDATE games SET status='finished', end_reason='abandoned', ended_at=? WHERE id=?",
                             (now, g["id"]))
                continue
            self.boards[g["id"]] = b
            self.opp_state[g["id"]] = {}
            # downtime must not count against the agent's move clock
            self.store.x("UPDATE games SET last_activity=? WHERE id=?", (now, g["id"]))
        # games finished without review (e.g. server restarted) -> requeue
        if self.kg and self.s.review_visits > 0:
            for g in self.store.q("SELECT id FROM games WHERE status='finished' AND review IS NULL "
                                  "AND moves_count > 0"):
                self._review_q.put(g["id"])

    def available_tiers(self, run: dict) -> list[str]:
        allowed = run["config"].get("opponents")
        names = [n for n, t in self.s.tiers.items() if t.visible and n in self.opponents]
        return [n for n in names if not allowed or n in allowed]

    def board_of(self, game: dict) -> Board:
        b = self.boards.get(game["id"])
        if b is None:  # finished games: rebuild from moves
            b = Board(game["size"], game["komi"])
            for m in self.store.game_moves(game["id"]):
                b.play(coord_to_point(m["coord"], game["size"]), BLACK if m["color"] == "B" else WHITE)
        return b

    # ------------------------------------------------------------ run admin
    def create_run(self, name: str, *, model: str = "", harness: str = "", reasoning: str = "",
                   context: str = "", notes: str = "", target_games: int = 200,
                   config: Optional[dict] = None, run_id: Optional[str] = None) -> dict:
        size = (config or {}).get("size")
        if size is not None and not (isinstance(size, int) and 5 <= size <= 19):
            raise ArenaError("bad_config", "config.size must be an integer between 5 and 19")
        run_id = run_id or "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:40] + \
            "-" + secrets.token_hex(2)
        token = "gat_" + secrets.token_urlsafe(24)
        run = self.store.create_run(run_id, name, token, model=model, harness=harness, reasoning=reasoning,
                                    context=context, notes=notes, target_games=target_games, config=config)
        self.store.event(run_id, "run_created", {"name": name, "model": model, "harness": harness})
        return run

    def set_run_status(self, run_id: str, status: str) -> None:
        with self._lock(run_id):
            self.store.set_run_status(run_id, status)
            if status == "active":  # time spent paused must not count against the agent
                self.store.x("UPDATE games SET last_activity=? WHERE run_id=? AND status='active'",
                             (time.time(), run_id))
            self.store.event(run_id, "run_status", {"status": status})

    # ------------------------------------------------------------ gameplay
    def _check_run_active(self, run: dict) -> None:
        if run["status"] == "paused":
            raise ArenaError("run_paused", "This run is paused by the operator. Try again later.", 409)
        if run["status"] in ("complete", "abandoned"):
            raise ArenaError("run_finished", f"This run is {run['status']}; no more games can be played.", 409)

    def new_game(self, run: dict, opponent: str, color: Optional[str] = None) -> dict:
        with self._lock(run["id"]):
            run = self.store.get_run(run["id"]) or run
            self._check_run_active(run)
            self._maybe_timeout(run)
            if self.store.active_game(run["id"]):
                raise ArenaError("game_in_progress",
                                 "You already have a game in progress. Finish it (play/pass/resign) first.", 409)
            done = len(self.store.finished_games(run["id"]))
            if done >= run["target_games"]:
                raise ArenaError("run_finished", f"All {run['target_games']} games have been played.", 409)
            tiers = self.available_tiers(run)
            if opponent not in tiers:
                raise ArenaError("unknown_opponent", f"Unknown opponent '{opponent}'. Choose one of: {', '.join(tiers)}")
            game_no = self.store.next_game_no(run["id"])
            if color and color.lower() not in ("random", "") and not self.s.allow_color_choice:
                raise ArenaError("color_fixed", "Colour choice is disabled for this run; colours alternate.")
            c = (color or "").lower()
            if c in ("b", "black"):
                agent_color = "B"
            elif c in ("w", "white"):
                agent_color = "W"
            elif c == "random":
                agent_color = self.rng.choice("BW")
            else:
                agent_color = "B" if game_no % 2 == 1 else "W"
            cfg = run["config"]
            size, komi = int(cfg.get("size", self.s.size)), float(cfg.get("komi", self.s.komi))
            if not 5 <= size <= 19:
                raise ArenaError("bad_config", f"board size {size} is not supported (5-19)", 500)
            now = time.time()
            spec = self.s.tiers[opponent]
            gid = self.store.x(
                "INSERT INTO games (run_id, game_no, opponent, opponent_elo, agent_color, size, komi, started_at,"
                " last_activity) VALUES (?,?,?,?,?,?,?,?,?)",
                (run["id"], game_no, opponent, spec.elo, agent_color, size, komi, now, now))
            board = Board(size, komi)
            self.boards[gid] = board
            self.opp_state[gid] = {}
            self.store.event(run["id"], "game_start", {"game_id": gid, "game_no": game_no, "opponent": opponent,
                                                        "agent_color": agent_color})
            game = self.store.game(gid)
            opp_move = None
            if agent_color == "W":
                opp_move, _ = self._opponent_turn(run, game, board)
                game = self.store.game(gid)
            return self._game_response(game, board, extra={"opponent_move": opp_move,
                                                             "message": f"New game #{game_no} started."})

    def play(self, run: dict, move: str) -> dict:
        with self._lock(run["id"]):
            run = self.store.get_run(run["id"]) or run
            if run["status"] == "paused":
                raise ArenaError("run_paused", "This run is paused by the operator. Try again later.", 409)
            if self._maybe_timeout(run):
                raise ArenaError("timeout", "Your game was forfeited because you did not move in time.", 409)
            game = self.store.active_game(run["id"])
            if not game:
                raise ArenaError("no_active_game", "No game in progress. Start one with `goban new`.", 409)
            board = self.boards[game["id"]]
            me = BLACK if game["agent_color"] == "B" else WHITE
            if board.to_play != me:
                # the opponent's reply was interrupted (engine error / restart): generate it now and show
                # the agent the new position instead of applying its move to a board it has not seen
                opp_move, finished = self._opponent_turn(run, game, board)
                if finished is not None:
                    return finished
                resp = self._game_response(self.store.game(game["id"]), board, extra={"opponent_move": opp_move})
                resp.update(ok=False, error={"code": "resync", "message": "the opponent's reply was delayed"})
                resp["text"] = ("NOTE: the opponent's previous reply had been delayed by a server problem. "
                                "Your move was NOT played (and not counted as illegal). Here is the current "
                                "position — choose your move again.\n" + resp["text"])
                return resp
            mv = move.strip()
            if mv.lower() == "resign":
                return self._finish(run, game, board, winner_is_agent=False, reason="resign")
            now = time.time()
            try:
                point = coord_to_point(mv, board.size)
                result = board.play(point, me)
            except IllegalMove as e:
                cnt = game["illegal_count"] + 1
                self.store.x("UPDATE games SET illegal_count=? WHERE id=?", (cnt, game["id"]))
                self.store.x("INSERT INTO illegal (game_id, ply, coord, code, message, ts) VALUES (?,?,?,?,?,?)",
                             (game["id"], len(board.moves) + 1, mv[:16], e.code, e.message, now))
                self.store.event(run["id"], "illegal", {"game_id": game["id"], "move": mv[:16], "code": e.code})
                game = self.store.game(game["id"])
                if cnt > self.s.max_illegal_per_game:
                    return self._finish(run, game, board, winner_is_agent=False, reason="illegal_limit")
                resp = self._game_response(game, board)
                resp.update(ok=False, error={"code": e.code, "message": e.message},
                            illegal_attempts=cnt, illegal_limit=self.s.max_illegal_per_game)
                resp["text"] = (f"ILLEGAL MOVE ({e.code}): {e.message}. Nothing was played; it is still your move. "
                                f"Illegal attempts this game: {cnt}/{self.s.max_illegal_per_game}.\n" + resp["text"])
                return resp
            think_ms = int((now - game["last_activity"]) * 1000)
            self._record_move(run, game, board, result, "agent", think_ms)
            if self._game_should_end(board):
                return self._finish(run, self.store.game(game["id"]), board, reason="score")
            opp_move, finished = self._opponent_turn(run, self.store.game(game["id"]), board)
            game = self.store.game(game["id"])
            if finished is not None:
                return finished
            return self._game_response(game, board, extra={"your_move": point_to_coord(point, board.size),
                                                            "captured": len(result.captured),
                                                            "opponent_move": opp_move})

    def _game_should_end(self, board: Board) -> bool:
        if board.consecutive_passes() >= 2:
            return True
        return len(board.moves) >= int(self.s.move_cap_factor * board.size * board.size)

    def _record_move(self, run: dict, game: dict, board: Board, mv, actor: str, think_ms: Optional[int],
                     info: Optional[dict] = None) -> None:
        ply = len(board.moves)
        coord = point_to_coord(mv.point, board.size)
        color = "B" if mv.color == BLACK else "W"
        now = time.time()
        self.store.x("INSERT INTO moves (game_id, ply, color, coord, actor, ts, think_ms, captured, info)"
                     " VALUES (?,?,?,?,?,?,?,?,?)",
                     (game["id"], ply, color, coord, actor, now, think_ms, len(mv.captured),
                      json.dumps(info) if info else None))
        self.store.x("UPDATE games SET moves_count=?, last_activity=? WHERE id=?", (ply, now, game["id"]))
        self.store.event(run["id"], "move", {"game_id": game["id"], "ply": ply, "color": color, "coord": coord,
                                             "actor": actor, "captured": len(mv.captured)})

    def _opponent_turn(self, run: dict, game: dict, board: Board) -> tuple[str, Optional[dict]]:
        opp = self.opponents[game["opponent"]]
        dec = opp.safe_genmove(board, self.opp_state.setdefault(game["id"], {}))
        if dec.resign:
            self.store.event(run["id"], "opponent_resign", {"game_id": game["id"]})
            return "resign", self._finish(run, game, board, winner_is_agent=True, reason="resign",
                                          extra={"opponent_move": "resign"})
        mv = board.play(dec.point)
        self._record_move(run, game, board, mv, "opponent", None, dec.info)
        coord = point_to_coord(dec.point, board.size)
        if self._game_should_end(board):
            return coord, self._finish(run, self.store.game(game["id"]), board, reason="score",
                                       extra={"opponent_move": coord})
        if self._decided(game["id"]):
            return coord, self._finish(run, self.store.game(game["id"]), board, winner_is_agent=False,
                                       reason="adjudicated", extra={"opponent_move": coord})
        return coord, None

    def _decided(self, game_id: int) -> bool:
        """Adjudication rule (see ArenaSettings).  Stateless: it reads the evaluations the opponent
        stored with its last moves (move info, from the opponent's point of view), so a restart
        neither loses nor double-counts the streak.  Nothing here is shown to the agent."""
        s = self.s
        if not s.adjudication_on:
            return False
        rows = self.store.q("SELECT ply, info FROM moves WHERE game_id=? AND actor='opponent' "
                            "ORDER BY ply DESC LIMIT ?", (game_id, int(s.adjudicate_moves)))
        if len(rows) < s.adjudicate_moves:
            return False
        evals = []
        for r in rows:
            if r["ply"] <= s.adjudicate_after:
                return False
            try:
                info = json.loads(r["info"]) if r["info"] else {}
                agent_wr, agent_lead = 1.0 - float(info["winrate"]), -float(info["score_lead"])
            except (ValueError, TypeError, KeyError):
                return False      # a move without an engine evaluation breaks the streak
            if not (agent_wr < s.adjudicate_winrate and agent_lead < -s.adjudicate_lead):
                return False
            evals.append((r["ply"], round(agent_wr, 4), agent_lead))
        log.info("game %s adjudicated: agent (ply, winrate, lead) on the last %d opponent moves: %s",
                 game_id, len(evals), evals)
        return True

    def _finish(self, run: dict, game: dict, board: Board, *, winner_is_agent: Optional[bool] = None,
                reason: str = "score", extra: Optional[dict] = None) -> dict:
        me = BLACK if game["agent_color"] == "B" else WHITE
        scoring = None
        margin = None
        if reason == "score":
            if len(board.moves) >= int(self.s.move_cap_factor * board.size * board.size) and \
                    board.consecutive_passes() < 2:
                reason = "move_cap"
            scoring = score_final(board, self.kg, self.s.referee_visits)
            scoring["dead_coords"] = [point_to_coord(p, board.size) for p in scoring["dead"]]
            scoring.pop("territory", None)
            margin = scoring["margin"]
            winner_color = scoring["winner"]
            if winner_color == 0:  # jigo (only possible with integer komi)
                winner_is_agent = None
            else:
                winner_is_agent = winner_color == me
        if winner_is_agent is None and reason not in ("score", "move_cap"):
            winner_is_agent = False
        if winner_is_agent is None:
            agent_score, winner, res = 0.5, "draw", "0"
        else:
            agent_score = 1.0 if winner_is_agent else 0.0
            winner = "agent" if winner_is_agent else "opponent"
            win_color = me if winner_is_agent else (WHITE if me == BLACK else BLACK)
            res = result_string(win_color, margin, "score" if reason in ("score", "move_cap") else reason)
        run_row = self.store.get_run(run["id"]) or run
        sgf = write_sgf(board.size, board.komi, [(m.color, m.point) for m in board.moves],
                        black=self._player_name(run_row, game, "B"), white=self._player_name(run_row, game, "W"),
                        result=res, date=time.strftime("%Y-%m-%d", time.gmtime(game["started_at"])),
                        event=f"goarena run {run['id']} game {game['game_no']}",
                        comment=f"end_reason={reason}")
        now = time.time()
        self.store.x("UPDATE games SET status='finished', result=?, winner=?, end_reason=?, margin=?, agent_score=?,"
                     " ended_at=?, last_activity=?, sgf=?, scoring=?, moves_count=? WHERE id=?",
                     (res, winner, reason, margin, agent_score, now, now, sgf,
                      json.dumps(scoring) if scoring else None, len(board.moves), game["id"]))
        self.boards.pop(game["id"], None)
        self.opp_state.pop(game["id"], None)
        game = self.store.game(game["id"])
        self.store.event(run["id"], "game_end", {"game_id": game["id"], "game_no": game["game_no"], "result": res,
                                                 "winner": winner, "reason": reason, "opponent": game["opponent"]})
        done = len(self.store.finished_games(run["id"]))
        if done >= run_row["target_games"] and run_row["status"] == "active":
            self.store.set_run_status(run["id"], "complete")
            self.store.event(run["id"], "run_complete", {"games": done})
        if self.kg and self.s.review_visits > 0 and len(board.moves) > 0:
            self._review_q.put(game["id"])
        resp = self._game_response(game, board, extra=extra)
        resp["game_over"] = True
        resp["result"] = {"result": res, "winner": winner, "end_reason": reason, "margin": margin,
                          "scoring": scoring, "games_completed": done, "target_games": run_row["target_games"]}
        resp["text"] += "\n" + result_text(game, scoring) + \
            f"\nGames completed: {done}/{run_row['target_games']}."
        return resp

    def _player_name(self, run: dict, game: dict, color: str) -> str:
        if game["agent_color"] == color:
            return f"{run['name']}"
        spec = self.s.tiers.get(game["opponent"])
        return f"{spec.label if spec else game['opponent']} [{game['opponent']}]"

    def _game_response(self, game: dict, board: Board, extra: Optional[dict] = None) -> dict:
        resp = {
            "ok": True,
            "game": {k: game[k] for k in ("id", "game_no", "opponent", "agent_color", "size", "komi", "status",
                                          "moves_count", "illegal_count")},
            "to_play": "B" if board.to_play == BLACK else "W",
            "board_rows": board.to_rows(),
            "moves": [point_to_coord(m.point, board.size) for m in board.moves],
            "game_over": game["status"] == "finished",
        }
        if extra:
            resp.update({k: v for k, v in extra.items() if v is not None})
        head = []
        if resp.get("message"):
            head.append(resp["message"])
        if resp.get("your_move"):
            head.append(f"You played {resp['your_move']}" +
                        (f" capturing {resp['captured']}." if resp.get("captured") else "."))
        if resp.get("opponent_move"):
            head.append(f"Opponent ({game['opponent']}) played {resp['opponent_move']}.")
        resp["text"] = ("\n".join(head) + "\n" if head else "") + board_text(board, game)
        return resp

    # --------------------------------------------------------- read models
    def board_view(self, run: dict) -> dict:
        with self._lock(run["id"]):
            game = self.store.active_game(run["id"])
            if not game:
                raise ArenaError("no_active_game", "No game in progress. Start one with `goban new`.", 409)
            board = self.boards[game["id"]]
            if board.to_play != (BLACK if game["agent_color"] == "B" else WHITE):
                _, finished = self._opponent_turn(run, game, board)
                if finished is not None:
                    return finished
                game = self.store.game(game["id"])
            return self._game_response(game, board)

    def status(self, run: dict) -> dict:
        run = self.store.get_run(run["id"]) or run
        summ = self.run_summary(run)
        game = self.store.active_game(run["id"])
        tiers = self.available_tiers(run)
        lines = [f"Run: {run['name']}  status={run['status']}",
                 f"Games: {summ['games_played']}/{run['target_games']} finished | "
                 f"W {summ['wins']} · L {summ['losses']}"
                 + (f" | rating {summ['elo']:.0f} ± {summ['elo_se']:.0f} (last {self.s.rating_window} rated games)"
                    if summ['elo'] is not None else " | rating: needs 5 rated games")]
        lines.append("Per opponent:")
        for t in tiers:
            st = summ["per_tier"].get(t)
            spec = self.s.tiers[t]
            elo_txt = f"~{spec.elo:.0f} Elo" if spec.elo_se is not None else "uncalibrated"
            lines.append(f"  {t:<8} ({elo_txt}{'' if spec.counts_for_rating else ', unrated'}): " +
                         (f"{st['wins']}/{st['games']} won ({st['score'] * 100:.0f}%)" if st else "not played"))
        if game:
            lines.append(f"Game in progress: #{game['game_no']} vs {game['opponent']} as "
                         f"{'Black' if game['agent_color'] == 'B' else 'White'}, {game['moves_count']} moves played.")
        else:
            lines.append("No game in progress.")
        return {"ok": True, "summary": summ, "active_game": game and {k: game[k] for k in (
            "id", "game_no", "opponent", "agent_color", "moves_count")}, "text": "\n".join(lines)}

    def opponents_view(self, run: dict) -> dict:
        tiers = [self.s.tiers[n].public() for n in self.available_tiers(run)]
        text = "Opponents (choose with `goban new --opponent NAME`):\n" + "\n".join(
            f"  {t['name']:<8} {('~%5d Elo' % t['elo']) if t['elo'] is not None else 'uncalibrated'}  {t['description']}"
            + ("" if t["counts_for_rating"] else " [unrated]")
            for t in tiers)
        return {"ok": True, "opponents": tiers, "text": text}

    def games_view(self, run: dict, limit: int = 50) -> dict:
        games = self.store.finished_games(run["id"])[-limit:]
        rows = [{k: g[k] for k in ("id", "game_no", "opponent", "agent_color", "result", "winner", "end_reason",
                                   "moves_count", "illegal_count")} for g in games]
        text = "game  opponent  you  result     outcome  reason        moves illegal\n" + "\n".join(
            f"#{r['game_no']:<4} {r['opponent']:<9} {r['agent_color']:<4} {r['result'] or '':<10} "
            f"{'WIN' if r['winner'] == 'agent' else 'loss':<8} {r['end_reason'] or '':<13} {r['moves_count']:<5} "
            f"{r['illegal_count']}" for r in rows) if rows else "No finished games yet."
        return {"ok": True, "games": rows, "text": text}

    def game_view(self, run: Optional[dict], game_no: Optional[int] = None, game_id: Optional[int] = None,
                  include_review: bool = False) -> dict:
        if game_id is not None:
            game = self.store.game(game_id)
        else:
            game = self.store.q1("SELECT * FROM games WHERE run_id=? AND game_no=?", (run["id"], game_no))
        if not game or (run is not None and game["run_id"] != run["id"]):
            raise ArenaError("not_found", "No such game.", 404)
        moves = self.store.game_moves(game["id"])
        board = self.board_of(game)
        sgf = game["sgf"] or write_sgf(board.size, board.komi, [(m.color, m.point) for m in board.moves])
        out = {"ok": True, "game": {k: v for k, v in game.items() if k not in ("sgf", "review", "scoring",
                                                                          "review_summary")},
               "moves": [{k: m[k] for k in ("ply", "color", "coord", "actor", "think_ms", "captured")} for m in moves],
               "sgf": sgf, "scoring": json.loads(game["scoring"]) if game["scoring"] else None,
               "illegal": self.store.game_illegal(game["id"]),
               "text": board_text(board, game, header=f"Game #{game['game_no']} vs {game['opponent']} — "
                                                     f"{game['result'] or 'in progress'}") +
               "\nMoves: " + " ".join(f"{m['ply']}.{m['color']}{m['coord']}" for m in moves)}
        if include_review:
            out["review"] = json.loads(game["review"]) if game["review"] else None
            out["review_summary"] = json.loads(game["review_summary"]) if game["review_summary"] else None
        return out

    def run_summary(self, run: dict) -> dict:
        games = self.store.q("SELECT * FROM games WHERE run_id=? ORDER BY game_no", (run["id"],))
        ill = self.store.q1("SELECT COUNT(*) AS n FROM illegal i JOIN games g ON g.id=i.game_id WHERE g.run_id=?",
                            (run["id"],))
        return run_summary(run, games, self.s.tier_elo, self.s.rated_tiers, list(self.s.tiers),
                           self.s.rating_window, ill["n"] if ill else 0)

    def run_detail(self, run: dict) -> dict:
        finished = self.store.finished_games(run["id"])
        return {"summary": self.run_summary(run),
                "journey": journey(finished, self.s.tier_elo, self.s.rated_tiers, self.s.rating_window),
                "phases": phase_table(finished, list(self.s.tiers)),
                "games": [{k: g[k] for k in ("id", "game_no", "opponent", "agent_color", "result", "winner",
                                             "end_reason", "moves_count", "illegal_count", "started_at", "ended_at")}
                          | {"review_summary": json.loads(g["review_summary"]) if g["review_summary"] else None}
                          for g in finished]}

    # ---------------------------------------------------- background jobs
    def _maybe_timeout(self, run: dict) -> bool:
        game = self.store.active_game(run["id"])
        if not game:
            return False
        board = self.boards.get(game["id"])
        if board is None:
            return False
        if board.to_play != (BLACK if game["agent_color"] == "B" else WHITE):
            return False  # waiting on our own opponent (e.g. engine trouble) is never the agent's fault
        if time.time() - game["last_activity"] > self.s.move_timeout_s:
            self._finish(run, game, board, winner_is_agent=False, reason="timeout")
            return True
        return False

    def _reaper(self) -> None:
        while not self._stop.wait(30):
            try:
                for g in self.store.all_active_games():
                    run = self.store.get_run(g["run_id"])
                    if run and run["status"] == "active":
                        with self._lock(run["id"]):
                            self._maybe_timeout(run)
            except Exception:  # pragma: no cover
                log.exception("reaper failed")

    def _review_worker(self) -> None:
        while not self._stop.is_set():
            try:
                gid = self._review_q.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.review_game(gid)
            except Exception:
                log.exception("review of game %s failed", gid)
            finally:
                self._review_q.task_done()

    def review_game(self, gid: int) -> Optional[dict]:
        if not self.kg:
            return None
        g = self.store.game(gid)
        if not g or g["status"] != "finished":
            return None
        moves = [(BLACK if m["color"] == "B" else WHITE, coord_to_point(m["coord"], g["size"]))
                 for m in self.store.game_moves(gid)]
        if not moves:
            return None
        rows = review_moves(moves, g["size"], g["komi"], self.kg, self.s.review_visits)
        summ = summarize_review(rows, g["agent_color"], g["size"])
        self.store.x("UPDATE games SET review=?, review_summary=? WHERE id=?",
                     (json.dumps(rows), json.dumps(summ), gid))
        self.store.event(g["run_id"], "review_done", {"game_id": gid, "summary": summ})
        return summ

    def wait_reviews(self, timeout: float = 600) -> None:
        t0 = time.time()
        while self._review_q.unfinished_tasks > 0 and time.time() - t0 < timeout:
            time.sleep(0.2)

    def stop(self) -> None:
        self._stop.set()
