# Infra tests

Smoke + rejection checks for the `_common/` infrastructure and the stage CLIs.
This suite exists so the methodology repo self-hosts on its own admission rule
(`alignment.md` §0, "the verifier admits"): the code that enforces closed-loop
verification is itself verified by committed, runnable evidence rather than an
unbacked "Verified" claim in a commit message.

## Run

    python3 -m pytest           # from repo root (pytest.ini sets testpaths=tests)

(Use whichever of `python` / `python3` resolves to Python 3 in your environment.)

No third-party deps beyond `pytest`. Every test that writes a ledger does so
under a `tmp_path`; the real `*-database/` ledgers are never touched.

## Coverage map

| File | What it pins |
|---|---|
| `test_imports_cli.py` | every grouped module + flat compat shim imports; shims re-export the SAME `main`; all CLIs answer `--help`; ledger `schema` prints |
| `test_admission.py` | the executable admission gate: verification commands RUN at append (pass admits + records outcome, fail rejects), checked/solid need verifiable evidence, dependency existence, bypass flags visible on the row |
| `test_result_ledger.py` | stage-4 admission: round-trip, latest-per-result collapse, query filters, 7 validator rejections, generated `render-md`/`render-state` views |
| `test_error_ledger.py` | trial log: pass/fail round-trip, §0 required-on-fail diagnosis, domain-legal `failure_mode` |
| `test_knowledge_ledger.py` | converged-node log: promotion (latest wins), predecessor walk, §0 `solid`-needs-evidence |
| `test_claims_ledger.py` | claim/obligation/assumption ledger: kind-conditional schema, settling refs checked to exist (result_ref / discharged_by / reduction_obligation), generated views |
| `test_loop_gate.py` | progress circuit breaker: full decision ladder + priority, streak arithmetic, `main()` exit codes, `progress_signal` over real ledgers |
| `test_dag_mermaid.py` | DAG-as-Mermaid renderer: merge, duplicates, node-view, per-node progress off the giant DAG |
| `test_dashboard.py` | HTML mission dashboard: render paths, chain badges + KPI arithmetic, SVG DAG topology, cycle reporting, ledger-text escaping, self-containment, CLI |
| `test_commit_msg_gate.py` | commit-msg hook: title grammar admit + reject cases, body/claim-tag warnings |

`factories.py` holds the minimal schema-valid rows; mutating one field is how the
rejection cases are built.

The v2 orchestrator has its own behavioral suite (including the end-to-end
toy-mission fixture): `cd orchestrator && npm test`.
