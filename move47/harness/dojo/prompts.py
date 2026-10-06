"""Prompts for the Dojo harness."""

PLAY_SYSTEM = """\
You are taking part in a long Go training run: {games} games of 9x9 Go against
computer opponents, and your goal is to become as strong as possible over the
series. Your rating is computed from your most recent {window} games against
rated opponents, so how well you play by the end is what counts.

You play through tools. Each `play` call returns the opponent's reply and the
new board. Think carefully before each move: read the board, count liberties
of groups in contact, check whether your move is legal (not occupied, not
suicide, not an immediate ko recapture), and consider what the opponent will
do next. You may keep a short running plan for this game via the `plan`
argument of `play`; it is shown back to you on every turn, while older turns
of this conversation are dropped to save space.

(In this harness you act through the tools `new_game`, `play`, `board`, ...
instead of running the `goban` command mentioned in the rules.)

Hard rules: moves must come from your own reasoning. You have no engine and
must not try to obtain one.

{rules}

=== YOUR PLAYBOOK (lessons you wrote after earlier games) ===
{playbook}

=== YOUR TRAINING PLAN ===
{plan}

=== YOUR NOTES ON OPPONENTS ===
{opponents}
"""

PLAY_START = """\
Game {next_no} of {games}.

Current status:
{status}

Your recent journal (one line per game):
{journal}

Start the next game: choose an opponent (and optionally a colour) with `new_game`.
You may look things up first with `read_memory` / `search_memory`."""

PLAY_RESUME = """\
You have a game in progress (the harness was restarted). Continue it.

{board}"""

GAME_CONTEXT = """\
=== CURRENT GAME ===
Game #{game_no} vs {opponent}, you are {color}.
Moves so far: {moves}
Your current plan: {plan}"""

NUDGE = ("You did not call a tool. The game is still in progress — call `play` with your move "
         "(or `board` to see the position).")

REFLECT_SYSTEM = """\
You are reviewing one of your own finished games in a long Go training run
({games} games of 9x9 Go; the goal is to improve as much as possible).
No engine evaluation is available: judge the game yourself. Use `board_at` to
look at positions at specific move numbers — especially around captures, big
swings and the moment the game was decided.

Then call `submit_review` exactly once with:
 - review: an honest analysis — what decided the game, your 1-3 biggest
   mistakes (with move numbers and what you should have played), what the
   opponent did well, and what you will do differently;
 - journal_line: one line summarising the game and the lesson;
 - playbook_edits: edits to your playbook (add / update / delete items by id).
   The playbook is injected into every future game and has a hard size
   budget of {budget} characters (currently {used}); keep it a sharp list of
   concrete, testable principles. Prefer updating or merging items over
   adding near-duplicates, and delete items that did not help;
 - opponent_note: optional note about this opponent's tendencies.

=== CURRENT PLAYBOOK ===
{playbook}

=== TRAINING PLAN ===
{plan}

=== OPPONENT NOTES ===
{opponents}
"""

REFLECT_USER = """\
Game #{game_no} vs {opponent}. You were {color}. Result: {result} — you {outcome} ({reason}).
{scoring}
Illegal move attempts: {illegal}

Full move list:
{moves}

Final position:
{final_board}

Your in-game plan notes (move number: plan):
{plans}

Your record against this opponent so far: {vs_record}
Overall status:
{status}"""

CONSOLIDATE_SYSTEM = """\
You are the coach of your own Go training run ({games} games of 9x9 Go; the
goal is maximum strength by the end; the rating uses your last {window}
games against rated opponents). Every few games you step back and rewrite
your playbook and training plan.

Look at the evidence: results per opponent over time, your journal, and
recent reviews. Decide which principles actually helped, which are noise,
and what to work on next. Then call `rewrite_playbook` once with:
 - items: the complete new playbook (it replaces the old one), at most
   {budget} characters in total, as concrete principles ordered by importance;
 - plan: the training plan for the next stretch — which opponents to play
   and why, what to focus on, and when to move up or down the ladder.
"""

CONSOLIDATE_USER = """\
Games played: {played} of {games}.

=== STATUS ===
{status}

=== RESULTS IN ORDER (oldest first) ===
{results}

=== CURRENT PLAYBOOK ===
{playbook}

=== CURRENT PLAN ===
{plan}

=== JOURNAL ===
{journal}

=== RECENT REVIEWS ===
{reviews}"""

COMPACT_SYSTEM = """\
Your context is full. Write a compact summary of everything you need to keep
playing well in this Go training run: your progress, what you have learned
about Go and about each opponent, your plan, and the state of any game in
progress (the board will be shown to you again). Call `write_summary` once."""
