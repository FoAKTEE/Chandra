---
name: work-packet
description: Work a leased stage-2 packet continuously, retain a trial WAL through compaction, and flush outcomes through the four ledger batch CLIs. Load for "work this packet", "resume after compaction", "flush the packet", or a scheduler-assigned node chain or repair.
---

# work-packet — keep reasoning continuous and make the ledger diff the deliverable

## When to use

- A scheduler leases an ordered packet of ready nodes or a repair packet.
- A running worker resumes after compaction or reaches its flush boundary.
- Candidate evidence, failure, escalation, or a budget stop must become durable rows.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`,
   `pipelines/2-work/spec.md`, and each packet node's filled task and declared inputs.
   Follow `.claude/skills/task-template/SKILL.md` if the task is incomplete. Read the
   packet list and supplied steering; use `CHANDRA_ROLE=worker` only as a delegated worker.
   Set `P`, `TASK`, and `PACKET_ID` from the lease; use the first node as the packet anchor.
2. Preserve the continuous-work contract from `orchestrator/src/agents.ts` below.
   Only the interpolated paper id is represented by `<P>`:
   ```text
   CONTINUOUS WORK CONTRACT (do not fragment):
   1. Work the packet nodes IN ORDER, in this one session, without stopping
      between nodes for bookkeeping. Keep a scratch log (WAL) at
      $CHANDRA_RUNTIME/paper_<P>/packets/<first-node>/packet_log.jsonl —
      append one line per trial as you go (cheap, ungated, NOT the ledger).
   2. If your context auto-compacts, RE-READ your packet_log.jsonl and this
      packet list, then CONTINUE from the last unfinished node. Compaction is
      not an interruption.
   3. FLUSH at the packet boundary (or when a node's evidence is admitted):
      land outcomes via the gated ledger CLIs — prefer the batch forms
      (result_database / error_database / knowledge_database / claims_database
      append-batch) so summaries regenerate once. The appends ARE the
      deliverable; your final text is ignored — only the ledger diff counts.
   4. Every trial (pass or fail) becomes an error-ledger row at flush.
   5. Interrupt the packet ONLY for: structural failure needing escalation
      (same-mode loop per crash-triage), or an impossible node — flush what
      is done first. Do not touch nodes outside the packet.
   ```
3. Ensure `CHANDRA_RUNTIME` is set to the mission's actual runtime root. The default in
   `orchestrator/src/runtime.ts` is `/tmp/chandra/<repo>-<sha8-of-absolute-path>/`;
   the runner does not export that computed default for you. Set it explicitly or use
   the inherited override, so the journal and WAL share a root. Then initialize scratch:
   ```bash
   : "${CHANDRA_RUNTIME:?set the mission runtime root outside the repo}"
   export CHANDRA_ROLE=worker
   PACKET_DIR="$CHANDRA_RUNTIME/paper_$P/packets/$PACKET_ID"
   mkdir -p "$PACKET_DIR"
   ```
   Keep the WAL at `$CHANDRA_RUNTIME/paper_<P>/packets/<id>/packet_log.jsonl`.
   Append JSONL, never rewrite it. Each trial records node, input claim, preconditions,
   candidate step, generated obligations, evidence or failure, verifier result, and the
   complete proposed error row. Record append receipts/checkpoints separately in the WAL.
4. Work nodes in lease order without unrelated node edits. Run the task's verifier and
   reduction-to-baseline check; record actual metrics and output paths. Keep research code,
   plots, and evidence in the task's output tree; scratch remains outside the repo.
   After compaction, reread WAL, lease, task criterion, and append receipts; compare with
   current ledgers, then continue the last unfinished node. Never equate compaction to failure.
5. Prepare boundary batches as JSON arrays, not JSONL. Print the current required fields:
   ```bash
   for db in error result knowledge claims; do
     python3 "_common/ledgers/${db}_database.py" schema
   done
   python3 _common/ledgers/error_database.py list-tags --domain symbolic
   ```
   This illustrative flush envelope contains complete minimal rows for all four ledgers;
   replace sample measurements and identifiers with actual observations before appending:
   ```json
   {"error":[{"paper":"arxiv-0000.00000","task_id":"boundary","iteration":1,
     "node_id":"arxiv-0000.00000::boundary","stage":"implementation","domain":"symbolic",
     "change_type":"structural","change_summary":"Evaluate a candidate boundary identity.",
     "metric":{"name":"residual","value":0,"threshold":0,"pass":true},
     "pass_fail":"pass","wall_clock_seconds":1,"expected":"zero residual",
     "observed":"zero residual in the trial","root_cause":"No failure observed.",
     "fix_hypothesis":"No fix proposed; independent validation remains."}],
    "result":[{"paper":"arxiv-0000.00000","result_id":"r-boundary-candidate","name":"Boundary candidate",
     "working_context":"Imported source conventions and regularity assumptions.",
     "claim":"The boundary identity remains to be independently verified.",
     "evidence_type":"unchecked_external_step","evidence":"Candidate trial only; no certificate yet.",
     "verifier_result":{"verdict":"partial"},"dependencies":[],"assumptions":["source regularity"],
     "status":"unchecked","provenance":"stage-2 candidate trial","open_obligations":["o-boundary"],
     "node_ids":["arxiv-0000.00000::boundary"]}],
    "knowledge":[{"paper":"arxiv-0000.00000","node_id":"arxiv-0000.00000::boundary",
     "task_id":"boundary","domain":"symbolic","status":"preliminary",
     "summary":"Candidate trial complete; validation remains.","predecessors":[]}],
    "claims":[{"paper":"arxiv-0000.00000","entry_id":"c-boundary","kind":"claim",
     "statement":"Verify the boundary identity.","status":"in_progress",
     "needed_evidence_type":"symbolic_derivation","node_ids":["arxiv-0000.00000::boundary"]}]}
   ```
   For `fail`, `crash`, or `partial` error rows, include `failure_mode`, `expected`,
   `observed`, `root_cause`, and `fix_hypothesis`; choose the actual domain's listed tag.
   Preserve expected/observed/root-cause/fix fields on successful trials too, per the kernel.
6. Validate candidates with `.claude/skills/adversarial-validate/SKILL.md` before accepting
   scientific claims. The mission loop does not automatically invoke that API. A checked
   result needs evidence, a passing verifier, compatible scope, and no open obligations.
   Include `verification: {command, timeout_s?, cwd?}` for executable checks; a command in
   `verifier_result` alone is descriptive. Do not re-append a result already landed by validation.
7. Write one array per ledger to `$PACKET_DIR/<ledger>.json` and flush in reference order:
   ```bash
   python3 _common/ledgers/error_database.py append-batch --repo-root . --rows-file "$PACKET_DIR/error.json"
   python3 _common/ledgers/result_database.py append-batch --repo-root . --rows-file "$PACKET_DIR/result.json"
   python3 _common/ledgers/claims_database.py append-batch --repo-root . --rows-file "$PACKET_DIR/claims.json"
   python3 _common/ledgers/knowledge_database.py append-batch --repo-root . --rows-file "$PACKET_DIR/knowledge.json"
   ```
   Register any missing prerequisite nodes before results that name them. Settle claims
   with existing `result_ref` and obligations with existing `discharged_by`; promote nodes
   to solid only after closure gates pass and predecessors are solid, in topological order.
   Batches can partially land: reconcile receipts/history before retrying; result and error
   batches do not deduplicate. Claims/knowledge dedup ignores metadata-only changes; use
   their `--force` only for an intentional such amendment. Those two implementations still
   regenerate summaries per row; only result/error batches regenerate once, despite the prompt.
8. Flush completed work before structural escalation, an impossible node, a circuit breaker,
   or budget exhaustion. Completion also ends a packet. After trial rows have landed, run:
   ```bash
   python3 _common/loop/loop_policy.py crash-triage --paper "$P" --task "$TASK" --repo-root .
   ```
   It reads ledger trials, not the scratch WAL. Use `.claude/skills/acquire-source/SKILL.md`
   for missing source support; ambiguity returns to decomposition. Hand notes, DAG views,
   rendered result/claim views, and digests to the observer after the flush.
9. Check the per-node diff interpretation in `orchestrator/src/scheduler.ts`, in precedence
   order: runner crash → `failed`; transition to solid → `admitted`; other status change
   or increased latest-result count → `promoted`; increased open-obligation count →
   `rejected`; otherwise → `no_progress`. Results attach via `node_ids`, errors via `node_id`.
   A result revision at the same id does not increase that count. Error rows and final prose
   alone do not count as progress; the final text is ignored for outcome measurement.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import importlib, json, os, re, subprocess
from pathlib import Path
body = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
fence = chr(96) * 3
rows = json.loads(re.search(fence + r'json\n(.*?)\n[ \t]*' + fence, body, re.S)[1])
for db, batch in rows.items():
    script = f'_common/ledgers/{db}_database.py'
    for args in [[], ['schema'], ['append-batch']]:
        subprocess.run(['python3', script, *args, '--help'], capture_output=True, check=True, timeout=5)
    schema = subprocess.check_output(['python3', script, 'schema'], text=True)
    assert 'REQUIRED fields:' in schema
    mod = importlib.import_module(f'_common.ledgers.{db}_database')
    for row in batch:
        assert mod.REQUIRED_FIELDS <= row.keys()
        mod.validate(row)
for script, sub in [('_common/ledgers/error_database.py', 'list-tags'), ('_common/loop/loop_policy.py', 'crash-triage')]:
    for args in [[], [sub]]:
        subprocess.run(['python3', script, *args, '--help'], capture_output=True, check=True, timeout=5)
agents = Path('orchestrator/src/agents.ts').read_text()
assert 'CONTINUOUS WORK CONTRACT' in agents and 'CHANDRA_ROLE: "worker"' in agents
scheduler = Path('orchestrator/src/scheduler.ts').read_text()
assert all(f'"{x}"' in scheduler for x in ['admitted', 'promoted', 'rejected', 'failed', 'no_progress'])
assert Path('orchestrator/src/runtime.ts').is_file()
PY
```
