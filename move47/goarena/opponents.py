"""Opponent tiers.

Every tier implements `genmove(board, state) -> MoveDecision`.  `state` is a
per-game dict the arena keeps for the opponent (resign counters etc.).

Tier kinds:
  random  - uniform random legal move that does not fill its own eye
  greedy  - no-engine heuristic (capture > escape atari > avoid self-atari)
  katago  - KataGo with `visits` playouts; temperature > 0 samples from the
            policy (visits == 1) or from the visit distribution (visits > 1);
            temperature 0 plays the policy argmax (visits == 1) or KataGo's
            best move (visits > 1); `random_prob` mixes in uniformly random
            moves; `root_symmetries` > 0 averages the root network evaluation
            over that many board symmetries (8 = all: with visits == 1 the
            policy, hence the move, is a fixed function of the position).

Strength labels/Elo values in the tier file are *calibrated* numbers produced
by `goarena calibrate` (see DESIGN.md); never trust the labels alone.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .board import BLACK, Board, coord_to_point, other
from .katago import KataGo


@dataclass
class MoveDecision:
    point: Optional[int]          # None = pass
    resign: bool = False
    info: dict = field(default_factory=dict)


@dataclass
class TierSpec:
    name: str
    label: str
    kind: str
    elo: float = 0.0
    elo_se: Optional[float] = None       # set by calibration; None = not calibrated
    description: str = ""
    visits: int = 1
    temperature: float = 0.0
    random_prob: float = 0.0
    root_symmetries: int = 0             # 0 = engine default (one random symmetry per evaluation)
    resign_threshold: float = 0.02
    resign_consecutive: int = 3
    resign_min_lead: float = 15.0
    counts_for_rating: bool = True
    visible: bool = True

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "TierSpec":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(name=name, **known)

    def public(self) -> dict:
        return {"name": self.name, "label": self.label,
                "elo": round(self.elo) if self.elo_se is not None else None,
                "elo_se": round(self.elo_se) if self.elo_se is not None else None,
                "description": self.description, "counts_for_rating": self.counts_for_rating}


def load_tiers(path: str | Path) -> dict[str, TierSpec]:
    data = json.loads(Path(path).read_text())
    tiers = data.get("tiers", data)
    return {name: TierSpec.from_dict(name, d) for name, d in tiers.items()}


# ---------------------------------------------------------------------------

def _candidate_moves(board: Board, color: int) -> list[int]:
    return [p for p in board.legal_moves(color) if not board.is_eye_like(p, color)]


class Opponent:
    def __init__(self, spec: TierSpec, rng: Optional[random.Random] = None):
        self.spec = spec
        self.rng = rng or random.Random()

    def genmove(self, board: Board, state: dict) -> MoveDecision:  # pragma: no cover - abstract
        raise NotImplementedError

    def safe_genmove(self, board: Board, state: dict) -> MoveDecision:
        """genmove, guaranteed legal under the arena's rules.  KataGo's own ko
        handling can differ from positional superko in rare cycles; then we
        fall back to a random legal move."""
        dec = self.genmove(board, state)
        if dec.resign or dec.point is None or board.is_legal(dec.point, board.to_play):
            return dec
        cands = _candidate_moves(board, board.to_play)
        dec.info = dict(dec.info, fallback=True)
        return MoveDecision(self.rng.choice(cands) if cands else None, info=dec.info)


class RandomOpponent(Opponent):
    def genmove(self, board: Board, state: dict) -> MoveDecision:
        cands = _candidate_moves(board, board.to_play)
        if not cands:
            return MoveDecision(None)
        return MoveDecision(self.rng.choice(cands))


class GreedyOpponent(Opponent):
    """Simple tactical heuristic, no search engine.  Useful as a sanity
    baseline and as the fallback ladder when KataGo is unavailable."""

    def genmove(self, board: Board, state: dict) -> MoveDecision:
        color = board.to_play
        cands = _candidate_moves(board, color)
        if not cands:
            return MoveDecision(None)
        if board.last_move and board.last_move.point is None:
            # opponent passed: pass too unless we can capture something
            pass_ok = True
        else:
            pass_ok = False
        best, best_score = None, -1e9
        for p in cands:
            score = self.rng.random()
            b = board.copy()
            mv = b.play(p, color)
            score += 10 * len(mv.captured)
            _, libs = b.group(p)
            if len(libs) == 1:
                score -= 8  # self-atari
            elif len(libs) >= 3:
                score += 1
            # does it put an opponent group in atari?
            for n in b.neighbors[p]:
                if b.cells[n] == other(color):
                    _, olibs = b.group(n)
                    if len(olibs) == 1:
                        score += 3
            # does it rescue one of our groups that was in atari?
            for n in board.neighbors[p]:
                if board.cells[n] == color:
                    _, olibs = board.group(n)
                    if len(olibs) == 1 and len(libs) > 1:
                        score += 6
            # mild preference for 3rd/4th line early on
            y, x = divmod(p, board.size)
            edge = min(x, y, board.size - 1 - x, board.size - 1 - y)
            if len(board.moves) < board.size * 2:
                score += {0: -2, 1: -0.5, 2: 1, 3: 0.8}.get(edge, 0.3)
            if score > best_score:
                best, best_score = p, score
        if pass_ok and best_score < 5:
            return MoveDecision(None)
        return MoveDecision(best)


class KataGoOpponent(Opponent):
    def __init__(self, spec: TierSpec, katago: KataGo, rng: Optional[random.Random] = None):
        super().__init__(spec, rng)
        self.kg = katago

    def genmove(self, board: Board, state: dict) -> MoveDecision:
        spec, color = self.spec, board.to_play
        sign = 1 if color == BLACK else -1
        visits = max(1, spec.visits)
        kw = {"override_settings": {"rootNumSymmetriesToSample": int(spec.root_symmetries)}} \
            if spec.root_symmetries > 0 else {}
        res = self.kg.analyze(board, visits, policy=(visits == 1 or spec.temperature > 0), **kw)
        root = res.get("rootInfo", {})
        winrate = root.get("winrate", 0.5)
        lead = root.get("scoreLead", 0.0)
        my_wr = winrate if color == BLACK else 1 - winrate
        my_lead = sign * lead
        info = {"winrate": round(my_wr, 4), "score_lead": round(my_lead, 2), "visits": root.get("visits")}

        # resignation
        if spec.resign_threshold > 0 and len(board.moves) >= board.size * board.size // 3:
            if my_wr < spec.resign_threshold and my_lead < -spec.resign_min_lead:
                state["low"] = state.get("low", 0) + 1
            else:
                state["low"] = 0
            if state["low"] >= spec.resign_consecutive:
                return MoveDecision(None, resign=True, info=info)

        # endgame: if the agent passed and the engine thinks pass is best, pass
        agent_passed = bool(board.last_move and board.last_move.point is None)
        infos = res.get("moveInfos", [])
        if agent_passed:
            top = infos[0]["move"].lower() if infos else "pass"
            if visits < 16:
                chk = self.kg.analyze(board, 32)
                ci = chk.get("moveInfos", [])
                top = ci[0]["move"].lower() if ci else "pass"
            if top == "pass":
                return MoveDecision(None, info=info)

        if spec.random_prob > 0 and self.rng.random() < spec.random_prob:
            cands = _candidate_moves(board, color)
            if cands:
                info["random"] = True
                return MoveDecision(self.rng.choice(cands), info=info)

        if visits == 1 or (spec.temperature > 0 and "policy" in res and visits <= 4):
            return MoveDecision(self._sample_policy(board, res["policy"], spec.temperature), info=info)

        if not infos:
            return MoveDecision(None, info=info)
        if spec.temperature > 0:
            weights = [mi["visits"] ** (1.0 / spec.temperature) for mi in infos]
            pick = self.rng.choices(infos, weights=weights)[0]
        else:
            pick = infos[0]
        mv = pick["move"]
        return MoveDecision(None if mv.lower() == "pass" else coord_to_point(mv, board.size), info=info)

    def _sample_policy(self, board: Board, policy: list[float], temperature: float) -> Optional[int]:
        n = board.size * board.size
        color = board.to_play
        items: list[tuple[Optional[int], float]] = []
        for p in range(n):
            pr = policy[p]
            if pr <= 0 or board.cells[p] != 0:
                continue
            if board.is_eye_like(p, color) or not board.is_legal(p, color):
                continue
            items.append((p, pr))
        if policy[n] > 0:
            items.append((None, policy[n]))
        if not items:
            return None
        if temperature <= 0.05:
            return max(items, key=lambda t: t[1])[0]
        logw = [math.log(pr) / temperature for _, pr in items]
        m = max(logw)
        weights = [math.exp(l - m) for l in logw]
        return self.rng.choices([p for p, _ in items], weights=weights)[0]


def build_opponent(spec: TierSpec, katago: Optional[KataGo], rng: Optional[random.Random] = None) -> Opponent:
    if spec.kind == "random":
        return RandomOpponent(spec, rng)
    if spec.kind == "greedy":
        return GreedyOpponent(spec, rng)
    if spec.kind == "katago":
        if katago is None:
            raise RuntimeError(f"tier {spec.name} needs KataGo but no engine is configured")
        return KataGoOpponent(spec, katago, rng)
    raise ValueError(f"unknown opponent kind {spec.kind}")
