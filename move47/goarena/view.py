"""Text rendering shared by the server responses, the `goban` CLI and the
native harness, so every harness sees exactly the same observations."""
from __future__ import annotations

from typing import Optional

from .board import BLACK, Board, point_to_coord


def stone(color: str) -> str:
    return "X" if color == "B" else "O"


def color_word(color: str) -> str:
    return "Black" if color == "B" else "White"


def recent_moves(board: Board, n: int = 6) -> str:
    out = []
    start = max(0, len(board.moves) - n)
    for i in range(start, len(board.moves)):
        m = board.moves[i]
        out.append(f"{i + 1}.{'B' if m.color == BLACK else 'W'} {point_to_coord(m.point, board.size)}")
    return "  ".join(out) if out else "(none)"


def board_text(board: Board, game: dict, *, header: Optional[str] = None) -> str:
    me = game["agent_color"]
    to_play = "B" if board.to_play == BLACK else "W"
    lines = []
    lines.append(header or f"Game #{game['game_no']} vs {game['opponent']} | you are {color_word(me)} ({stone(me)}) "
                           f"| komi {game['komi']:g} | Chinese area scoring")
    lines.append(board.render())
    cap_b, cap_w = board.captures[1], board.captures[2]
    lines.append(f"Move {len(board.moves)} played. Captures: X took {cap_b}, O took {cap_w}. "
                 f"Recent: {recent_moves(board)}")
    if game.get("status") == "active":
        turn = "YOUR move" if to_play == me else "opponent to move"
        lines.append(f"{color_word(to_play)} ({stone(to_play)}) to play — {turn}.")
    return "\n".join(lines)


def result_text(game: dict, scoring: Optional[dict]) -> str:
    who = "You WON" if game["winner"] == "agent" else "You LOST"
    s = f"GAME OVER: {game['result']} — {who} ({game['end_reason']})."
    if scoring and game["end_reason"] in ("score", "move_cap"):
        s += (f" Area: Black {scoring['black_area']}, White {scoring['white_area']} + komi {scoring['komi']:g}."
              f" Dead stones removed: {', '.join(scoring.get('dead_coords', [])) or 'none'}.")
    return s
