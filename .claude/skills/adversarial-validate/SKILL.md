---
name: adversarial-validate
description: Submit one candidate to independent refuter and judge sessions, then execute the verdict through gated ledger appends. Load for "validate this candidate", "independent refutation", "admit or reject this result", or a repair following a rejected evidence claim.
---

# adversarial-validate — refute first, judge second, admit only through the gate

## When to use

- One node has a bounded claim, candidate result row, and inspectable evidence files.
- A worker needs independent validation before promoting a result or closing its node.
- A rejection needs a traceable repair obligation and a subsequent validation attempt.

## Steps

1. Read `alignment.md`, `_common/contracts/research_admission_contract.md`, the seven
   validation gates in `pipelines/2-work/spec.md`, and `orchestrator/src/validator.ts`.
   There is no validation CLI subcommand: call `adjudicateCandidate` through the module API.
   The current mission entrypoint does not call it automatically; arrange this step explicitly.
2. Build a `CandidateSubmission` JSON object with `paper`, `node`, integer `wave`, plain
   `claim`, complete `resultRow`, and `evidencePaths` (individual repo-relative files).
   Print the actual result schema before filling it:
   ```bash
   python3 _common/ledgers/result_database.py schema
   ```
   This example includes every REQUIRED result field; substitute real identifiers, paths,
   working context, assumptions, and the task's actual verification command before use:
   ```json
   {"paper":"arxiv-0000.00000","node":"arxiv-0000.00000::boundary","wave":1,
    "claim":"The boundary term vanishes under the stated regularity conditions.",
    "resultRow":{"paper":"arxiv-0000.00000","result_id":"r-boundary","name":"Boundary term",
      "working_context":"Source conventions, boundary regime, and defined symbols.",
      "claim":"The boundary term vanishes under the stated regularity conditions.",
      "evidence_type":"symbolic_derivation",
      "evidence":{"path":"results/<project>/paper_<P>/evidence/boundary.txt"},
      "verifier_result":{"verdict":"pass"},"dependencies":[],
      "assumptions":["the stated regularity conditions"],"status":"checked",
      "provenance":"Task boundary derivation and recorded verifier output.","open_obligations":[],
      "node_ids":["arxiv-0000.00000::boundary"],
      "verification":{"command":"<actual task verification command>","timeout_s":60}},
    "evidencePaths":["results/<project>/paper_<P>/evidence/boundary.txt"]}
   ```
   Include the certificate, verifier source/output, and any definitions or source excerpts
   needed to assess this claim in `evidencePaths`. The executable command later runs in the
   consumer repo, not the pack, so its files must also exist there. A verdict field alone
   does not execute verification. `node_ids` must be a non-empty array containing the
   candidate `node`, and `resultRow.paper` / `resultRow.claim` must equal the candidate's
   `paper` / `claim`: the API freezes and hashes the submission at entry and rejects any
   mismatch (`ValidationBindingError`) before a pack is built or a reviewer runs.
3. Check the pack boundary. `ALWAYS_PACKED` contains exactly `alignment.md`,
   `_common/contracts/research_admission_contract.md`, and `pipelines/2-work/spec.md`.
   The builder adds only the evidence allowlist, generated `CLAIM.md` containing the claim
   and proposed row, and `MANIFEST.json`; hashed entries include `CLAIM.md` but not the
   manifest itself. The fresh directory is under `/tmp/chandra-pack-<suffix>/`.
   The defender transcript, unrelated nodes, and remaining repo files are physically absent
   from that directory. `checkIsolation` rejects unmanifested, changed, or missing files and
   is re-run after construction, after refutation, and after judging: any change aborts the
   adjudication with `pack_tampered` and no verdict. Evidence paths must be relative, contain
   no `..` segment, and resolve (realpath) inside the repository; symlink escapes are rejected.
   Do not overclaim host isolation: the runner sets cwd and permits Read/Grep/Glob/Bash;
   it installs no filesystem sandbox, and the audit checks pack contents only.
   For a requirement that validators cannot access anything else on the host, supply a
   `ValidatorRunner` backed by an enforced filesystem boundary; this SDK runner alone is insufficient.
4. Require refutation before judging. Nonempty findings are mandatory, including specific
   failed refutation attempts when no counterexample is found. Check all seven gates:

   | Gate | Refuter's check |
   |---|---|
   | 1 | Every symbol has a definition in the supplied source/context. |
   | 2 | Claim carries context, evidence type, assumptions, dependencies, provenance. |
   | 3 | Evidence actually supports the required evidence type. |
   | 4 | Units, dimensions, frames, regimes, and domains agree. |
   | 5 | Approximation names parameter, norm, order, regime, remainder obligations. |
   | 6 | Simulation/empirical protocol includes code, checks, uncertainty, artifacts. |
   | 7 | Checked claims have no open/unchecked items or circular evidence dependency. |

   Ledger shape/ref checks cover only part of these gates; undefined symbols and scientific
   compatibility still need substantive review. Never promote simulation or citation to proof.
5. Give the judge a fresh session with the pack and refuter findings, without the defender's
   conversation. Require exactly one JSON object with string reasons:
   `{"verdict":"admit","reasons":"One paragraph explaining why the evidence survives refutation."}`
   or the same shape with `"verdict":"reject"`. Unparseable output, or an admit whose
   `reasons` is missing or blank, becomes a rejection (`judge gave no reasons`);
   empty refuter findings abort before judging or appending.
6. Run one submission manually after building the existing orchestrator per
   `.claude/skills/mission-run/SKILL.md`. From the consumer root, set `SUBMISSION` to the
   reviewed JSON file outside the repo. This command uses real sessions and gated appends:
   ```bash
   export PYTHONDONTWRITEBYTECODE=1
   CHANDRA_ROLE=validator node --input-type=module - "$PWD" "$SUBMISSION" <<'JS'
   import fs from 'node:fs';
   import path from 'node:path';
   import { pathToFileURL } from 'node:url';
   const [root, input] = process.argv.slice(2);
   const load = file => import(pathToFileURL(path.join(root, 'orchestrator/dist/src', file)).href);
   const { adjudicateCandidate, buildValidatorRunner } = await load('validator.js');
   const { Ledgers } = await load('ledger.js');
   const { Journal } = await load('journal.js');
   const { runtimeDir } = await load('runtime.js');
   const { loadMissionSpec } = await load('missionspec.js');
   const candidate = JSON.parse(fs.readFileSync(input, 'utf8'));
   if (candidate.paper !== candidate.resultRow.paper || candidate.claim !== candidate.resultRow.claim)
     throw new Error('candidate paper/claim must agree with resultRow');
   const base = fs.realpathSync(root) + path.sep;
   for (const rel of candidate.evidencePaths) {
     if (path.isAbsolute(rel) || rel.split(/[\\/]/).includes('..')) throw new Error('unsafe evidence path');
     const file = fs.realpathSync(path.join(root, rel));
     if (!file.startsWith(base) || !fs.statSync(file).isFile()) throw new Error('evidence must be a repo file');
   }
   const spec = loadMissionSpec(root);
   const outcome = await adjudicateCandidate(candidate, {
     repoRoot: root, ledgers: new Ledgers(root, 'validator'),
     journal: new Journal(path.join(runtimeDir(root, `paper_${candidate.paper}`), 'journal.jsonl')),
     runner: buildValidatorRunner(spec),
   });
   console.log(JSON.stringify(outcome));
   process.exitCode = outcome.outcome === 'admitted' ? 0 : 1;
   JS
   ```
   For cross-model refutation, set consumer `mission.json` `models.refuter` to an available
   model different from `models.worker`; set `models.judge` as desired. The current factory
   selects each role independently, including `codex:<model>`; omitting the API's `runner`
   also loads these defaults. This still does not wire validation into the mission `run` loop.
   The optional `codex` settings are explained in `.claude/skills/mission-run/SKILL.md`;
   validator CLI sessions default to read-only, but a sandbox override changes that boundary.
7. Interpret the actual append outcome. `admitted` means the result append passed;
   `gate_rejected` means an admit verdict failed executable admission and no result landed.
   `rejected` appends a blocking open obligation with all five schema-required fields:
   ```json
   {"paper":"arxiv-0000.00000","entry_id":"repair-arxiv-0000_00000::boundary-w1",
    "kind":"obligation","status":"open","statement":"validation rejected: gate 4 violated",
    "node_ids":["arxiv-0000.00000::boundary"],"blocking":true}
   ```
   The actual id is `repair-<sanitized-node>-w<N>`: characters outside letters, digits,
   underscore, colon, and hyphen become underscores. Rejection does not demote knowledge rows;
   a still-unsolid node with solid predecessors remains on the frontier with the repair.
   Current readiness does not filter open obligations. Never close the node before repair.
8. After admission, have the delegated worker settle claim/obligation rows and promote
   the node only after all closure gates pass, using `.claude/skills/work-packet/SKILL.md`.
   The validator API itself only appends the result or repair obligation; it does not refresh
   claim views or promote nodes. On exceptions or gate rejection, record the actual failed
   gate, observed error, root cause evidence, and fix hypothesis as an error trial. The pack
   is removed in the normal adjudication cleanup, but the full review — candidate and its
   hash, pack manifest, complete refuter findings, raw judge output, verdict, the appended row
   or repair obligation, timestamps — is retained at
   `$CHANDRA_RUNTIME/paper_<P>/validation/<node>-w<N>.json` (`reviewPath()` in
   `orchestrator/src/validator.ts`); the journal's `validation_verdict` carries
   `candidateHash` and `reviewPath`. Keep durable evidence in consumer outputs.

## Verify

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, re, subprocess
from pathlib import Path
from _common.ledgers import claims_database as c, result_database as r
for db in ['result', 'claims']:
    script = f'_common/ledgers/{db}_database.py'
    for args in [[], ['schema'], ['append']]:
        subprocess.run(['python3', script, *args, '--help'], capture_output=True, check=True, timeout=5)
    assert 'REQUIRED fields:' in subprocess.check_output(['python3', script, 'schema'], text=True)
body = (Path(os.environ['CLAUDE_SKILL_DIR']) / 'SKILL.md').read_text()
fence = chr(96) * 3
candidate, repair = [json.loads(x) for x in re.findall(fence + r'json\n(.*?)\n[ \t]*' + fence, body, re.S)]
assert {'paper', 'node', 'wave', 'claim', 'resultRow', 'evidencePaths'} == candidate.keys()
r.validate(candidate['resultRow']); c.validate(repair)
src = Path('orchestrator/src/validator.ts').read_text()
packed = src.split('const ALWAYS_PACKED = [', 1)[1].split('];', 1)[0]
assert re.findall(r'"([^"]+)"', packed) == ['alignment.md', '_common/contracts/research_admission_contract.md', 'pipelines/2-work/spec.md']
for p in re.findall(r'"([^"]+)"', packed):
    assert Path(p).is_file(), p
assert src.index('await runner.refute(') < src.index('await runner.judge(') < src.index('await ledgers.appendResult(')
assert 'if (!refutation.findings.trim())' in src and 'gate_rejected' in src
assert 'adjudicateCandidate' not in Path('orchestrator/src/main.ts').read_text()
PY
```
