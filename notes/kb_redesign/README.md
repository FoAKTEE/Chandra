# kb_redesign — evidence for `notes/knowledgebase_redesign.md`

- `scale.py` — append / query / transitive-walk / trial-append cost at 100, 500, 2,000 pre-existing rows, plus a 200-row batch.
- `gaps.py` — the four demonstrations: cross-paper readiness, same-id claim replacement, tail truncation vs `verify-chains`, orphan trial anchors.
- `concurrent.py` — four processes appending to one ledger with no lock corrupt the hash chain.
- `prompts/` — the two GPT-6 analysis prompts owed under obligation `kb-gpt6-review`.

All scripts run from the repo root against throwaway repos under `/tmp`; they never touch `results/`.
