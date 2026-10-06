"""The task given to every harness.  All harnesses get the same goal text;
only the machinery around the model differs."""
from __future__ import annotations

TASK_TEMPLATE = """\
# Go training run

You will play {games} games of Go (9x9) against computer opponents in an arena.
Your goal: become as strong as you can over the course of these games. Your
rating is computed from your results in your most recent {window} games against
rated opponents, so what matters is how well you play by the end.

## How to play
Use the `goban` command (already on your PATH):

    goban rules                      # read these first
    goban opponents                  # the opponent ladder
    goban status                     # progress, results per opponent, rating
    goban new --opponent NAME        # start a game (colours alternate unless you pass --color)
    goban board                      # current position
    goban play D4                    # play a move; the opponent replies immediately
    goban play pass | goban resign
    goban games | goban show N [--sgf]   # your past games

One game at a time. Each `goban play` returns the opponent's reply and the new board.

## Learning
Nobody will teach you. Working out how to improve is part of the task. You
choose which opponent to play each game. The opponents never learn; you can.
You may keep notes and files in this directory, review your past games, and
write helper code (e.g. to display boards, count liberties, parse records,
keep statistics).

## Hard rules
- Do NOT use, download, install, or write a Go-playing engine, search
  algorithm or neural network to pick your moves (no KataGo, Leela Zero,
  GNU Go, Pachi, MCTS/minimax you write yourself, etc.). Every move must be
  chosen by you. Violating this voids the run.
- No internet lookups for Go material.
- Keep playing until all {games} games are finished (`goban status`). If your
  session ends early you will be restarted in this same directory with your
  files intact; pick up where you left off.
"""

CONTINUE_PROMPT = """\
You are continuing the Go training run described in TASK.md (your session was
restarted; your files are intact). Check `goban status`, finish any game in
progress, and keep going until all games are played."""

FIRST_PROMPT = "Read TASK.md in this directory and carry out the task. Start with `goban rules`."


def render_task(games: int, window: int = 50) -> str:
    return TASK_TEMPLATE.format(games=games, window=window)
