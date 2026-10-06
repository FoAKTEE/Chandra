# Task for a coding agent: improve the code heuristics from search data

You are improving `gotree/user_heuristics.py` (copy it from `gotree/user_heuristics_template.py` if it does not
exist). These heuristics are the system's fast "intuition": they order candidate moves when the LLM runs out of
ideas and they are the starting point of every search. The ground truth is the search DAG of earlier runs
(`runs/<run>/dag.db`): positions that were searched many times and the move the search preferred.

Loop (Heuristic Learning — iterate on code, not weights):
1. `python -m gotree heurtest --run runs/<run>` and note `top5` and `value_corr`.
2. Look at positions where the heuristic disagrees with the search (write a small script that lists them with
   `gotree.perception.position_card`). Find a pattern that explains several of them.
3. Change `score_moves` / `value` to capture that pattern. Keep the code small and readable.
4. Re-run heurtest. Keep the change only if `top5` or `value_corr` improves on positions you did NOT look at
   (split the nodes, e.g. by key hash, into a train half and a test half).
5. Turn each position you fixed into a regression test in `tests/test_user_heuristics.py`.
6. Append one line per iteration to `runs/<run>/hl-trials.jsonl`: what you changed, the numbers before/after.

Rules: no pretrained Go engines or neural networks, no downloaded game records, no KataGo output.
Rules-level code (liberties, ladders, eyes), pattern tables and hand-written evaluators are fine.
