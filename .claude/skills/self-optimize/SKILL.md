---
name: self-optimize
description: Run Chandra on Chandra — optimize this methodology repo (infra, ledgers, orchestrator, skills) as a self-hosted mission whose DAG, trials, and promotions live in the repo's own ledgers under the `software` domain, one gated commit per node. Use for any change to the methodology itself, when asked to "improve / optimize / self-improve Chandra", or when a worker's skill or tool change must be recorded as verified progress.
---

# self-optimize — the methodology repo is its own consumer

Same invariant, same machinery: nodes are knowledge rows, work is trials, a node
is solid only when the admission gate has RUN its verification command. The
domain is `software` (`python3 _common/ledgers/error_database.py describe-domain --domain software`).

## When to use

- Any code, contract, or skill change to this repo that should count as verified progress.
- A stalled or ad hoc improvement that needs a DAG, a verifier, and a commit per node.

## Steps

1. **Branch and gate.** Work on a topic branch; `bash _common/hooks/install.sh` so every
   commit passes the commit-msg gate (`commit-gated`).
2. **Decompose into nodes.** Paper id `self`, node ids `self::<slug>`, `domain: software`,
   status `hypothesis`, `predecessors` for real dependencies. Append the DAG with
   `CHANDRA_ROLE=worker python3 _common/knowledge_database.py append-batch --repo-root .`
   from a JSON array of rows shaped like
   `{"paper":"self","node_id":"self::skill-registry","task_id":"S1","domain":"software","status":"hypothesis","summary":"…","predecessors":[]}`.
   The role is required under `.delegation-policy: strict`; it is recorded as `actor_role`.
3. **Work one node.** Tests first (`tests/test_<node>.py`), then code; run `python3 -m pytest -q`
   and, for `orchestrator/`, `cd orchestrator && npm test`. Delegate substantial nodes to a
   worker with `codex-gpt6-max`; you orchestrate, verify, and commit (kernel §6).
4. **Log every trial** (`ledger-error-trial`): `domain: software`, `node_id` set, `stage:
   implementation`; failures carry expected / observed / root_cause / fix_hypothesis and a
   `failure_mode` from the software tag list (`test_failure`, `spec_drift`, `gate_rejection`,
   `timeout_or_oom`, …; first unknown kind → `uncategorized_software` with a candidate tag).
5. **Commit per node** with a `verify:` object quoting the suite output; tests with the code;
   no large data, no rendered HTML, no tool attribution.
6. **Promote through the gate.** Append a `solid` row citing the commit and carrying the
   verifier — the gate runs it and refuses the promotion if it fails:
   `{"paper":"self","node_id":"self::skill-registry","task_id":"S1","domain":"software","status":"solid","summary":"…","predecessors":[],"evidence":"b9e6cc9","verification":{"command":"python3 -m pytest tests/test_skill_registry.py -q","timeout_s":300}}`
   Use `"cwd": "orchestrator"` inside `verification` for `npm test`. A refused promotion is a
   trial: log it with its root cause, fix, retry. The verifier runs without your `CHANDRA_ROLE`.
7. **Read progress off the DAG**, never off prose:
   `python3 _common/visualization/dag_mermaid.py progress --repo-root .`,
   `python3 _common/visualization/dag_mermaid.py render --paper self --repo-root .`,
   `python3 _common/visualization/dashboard.py render --paper self --repo-root . --out /tmp/chandra/dashboard_self.html`,
   `python3 _common/contract.py verify-chains --repo-root .` (a broken chain halts everything).
8. **Commit the ledger rows** as `notes(self): …` (small JSONL + summary.csv only).
9. **Harvest recipes.** A procedure you used twice is a skill (`skill-write`); a helper you wrote
   ad hoc is promoted into `_common/` with tests (`tool-promote`). Three cycles of the same idea
   on one node ⇒ `loop-no-tweak`.

## Verify

```bash
python3 _common/ledgers/knowledge_database.py schema | grep -q software \
  && python3 _common/ledgers/error_database.py describe-domain --domain software | grep -q test_failure \
  && python3 _common/loop/loop_policy.py describe-domain --domain software | grep -q pivot
```
