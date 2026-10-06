# Provenance — go-bench v0.02 working copy

- source: `/data/haiyangw/claude/Move47/ref-code/v0.02/go-bench/` in the Move47 workspace,
  handed over by the user; no upstream URL, repository or commit is known.
- mirror: `ref-code/go-bench-v0.02/` at the Chandra root (gitignored, verbatim, never edited;
  it has its own `PROVENANCE.md` and also keeps the source's top-level `PROMPT.md` and `TREE.md`).
- imported: 2026-10-05, node `move47::import` (task M1).
- scope: all 69 files of `go-bench/` (interpreter caches `__pycache__/` skipped). The source's
  top-level `PROMPT.md` and `TREE.md` are byte-identical to `go-bench/docs/PROMPT.md` and
  `go-bench/TREE.md` (`diff` empty, same sha256), so here they are `docs/PROMPT.md` and `TREE.md`.
- after this import, changes to these files are ordinary commits; the manifest below records
  the state as imported.

## Deviations from the source (complete list)

Every imported file is byte-identical to the source at the same relative path, except:

1. **Executable bits.** The handed-over copy had lost them (every source file is mode 0664).
   Restored `+x` where code or docs run the file as a program:

   | file | how it is run |
   |---|---|
   | `bin/goban` | docs: `bin/goban rules` etc. (`docs/GO-BENCH.md:85`) |
   | `tests/fake_cli_agent.py` | `tests/test_harness.py:71` passes it as `--claude-bin`; `harness/runner.py:54` executes it |
   | `tests/fake_tree_agent.py` | `tests/test_gotree.py:154` passes it as `binary=`; `gotree/workers.py:279` executes it |
   | `scripts/build_katago.sh` | docs: `scripts/build_katago.sh` (`docs/GO-BENCH.md:49`) |
   | `scripts/audit_run.py` | shebang CLI; docs call `python scripts/audit_run.py`, so `+x` is not required; set to match the shebang and `scripts/engine_check.py` (100755) |

   Left 0644 after checking: `goarena/goban.py` (module behind `bin/goban`; `harness/runner.py:134-136`
   copies it into the agent workspace and sets 0755 there itself) and `scripts/slurm/{arena,play,probe}.sbatch`
   (read by `sbatch`, like the mission's own `.sbatch` files).
   Without the two test fakes' bits the suite gives 47 passed, 2 failed
   (`test_cli_worker_protocol`, `test_runner_relaunches_fake_cli`: PermissionError); with them, 49 passed.
2. **README rename.** go-bench `README.md` is `docs/GO-BENCH.md` (content unchanged); `README.md`
   here stays the mission README.
3. **`.gitignore` merge.** go-bench's entries were merged into the existing mission `.gitignore`;
   the only one missing was `*.log`, appended with one comment line. No existing line changed.
4. **`pytest.ini` added** (`testpaths = tests`, `pythonpath = .`): `cd move47 && python3 -m pytest`
   uses `move47/` as rootdir and import root, independent of the Chandra root `pytest.ini`.
5. **README pointer line.** One line added to the mission `README.md`, pointing to
   `docs/GO-BENCH.md`, `TREE.md`, `DESIGN.md` and this file.
6. **This file** (`PROVENANCE.md`) added.

Mapping: `<source>/X` → `move47/X` for every path, except `README.md` → `docs/GO-BENCH.md` and
`.gitignore` (merged, see 3).

## Manifest

`sha256sum` of every imported source file, paths relative to the source `go-bench/` directory,
sorted (`LC_ALL=C`). Checks, run from `move47/`:

```bash
sed -n '/^```sha256$/,/^```$/{//!p}' PROVENANCE.md > /tmp/go-bench-v0.02.sha256
(cd ../ref-code/go-bench-v0.02/go-bench && sha256sum -c --quiet /tmp/go-bench-v0.02.sha256)   # mirror
grep -vE '  (README\.md|\.gitignore)$' /tmp/go-bench-v0.02.sha256 | sha256sum -c --quiet       # working copy, as imported
sed -n 's/  README\.md$/  docs\/GO-BENCH.md/p' /tmp/go-bench-v0.02.sha256 | sha256sum -c --quiet
```

```sha256
74252049600010ee4134a31496224507e3dc4f1ebd7ec1430fb94f54afebb81b  .gitignore
5e2d7523863d655ddb0524916bb15ed07b663b14162bdfd7dd57cfc9e4875a12  DESIGN.md
5975f8d916d15ade3b3e7f9c3987581f664d72328bf1173ab2ded6a519bec708  README.md
6e21d163a7e22d248e37542fbde4ef3c22574b2c9a771712f8768c412b54f53b  TREE.md
2c56d4a1c3c5a147631de834ddfce2e65363f803b2cd18dde95883a3e923e46a  bin/goban
014f862e075d088b6dc23349bc41532555d14865431a25ccdd054141c0d776e0  config/calibration-games-9x9.jsonl
478f5979b76e628cbfdde1bcd99ea793b282f59fa325870d378cc974275109df  config/tiers-19x19.json
4d5aafe9ec1069570d72b297a5aac004f7f267a969ad079e825232f1efb3887e  config/tiers-9x9.json
1fceb859fa84a1cd0c57fd1393fb06b15448d575c08e648518fd9cdaa79aaa1d  data/alphago-leesedol-2016-g2.sgf
7e093fd35d08ae7e02b24dba226f058fb2b1efd685bebae1fa0c4cef18cb7ed7  data/alphago-leesedol-2016-g4.sgf
8d19964f621164944cd44c02b6dab546840ed4da937045e456156162632c4b4f  docs/PROMPT.md
77cccee8f07598775c337cbf6dafe7ec72c7c9041221265d6714b071aa3c7847  docs/prompts/hl-heuristics.md
252a02359d885818da47a839245228205c2380f86a7188ce05a507ab53d584fc  docs/screenshots/game.png
c7cd9207bce172e12136f9ecf1bdf588f069e8becc4c0ed2e4181416356f8a66  docs/screenshots/run.png
2c97543d82b66993f706ad1affa066edda1168c8d5614fa8690486831dddabbe  engines/configs/analysis.cfg
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  goarena/__init__.py
3086ee1a113d6176b25c3902c4448c95a634a0d033e5a06245ce836b4c2f8714  goarena/__main__.py
6ebfaca810f600bf1656438a2b6571e62108952d267c6b8734c8ce2c741d55f4  goarena/arena.py
d6af37cee4f8b76556b6fff6d6b7efd80868a7febd55ee48793abb4d0bb2f571  goarena/board.py
3261489bafd147a1bb71f66b0b001612ec01bee50128a01bd82f45b3ebd0f5ae  goarena/goban.py
1027e5a569a37e60972e1915770bc520770657a2fdad1824020fcecd014193cb  goarena/katago.py
5889d3aa51b8812d5fab3ad5747c1ad1d41a1f91902e47263f9cbbbba045609c  goarena/opponents.py
a07c6e30017449a1e8331e4adb38f8dab557689d54ce452fa6e7b8786813c3a3  goarena/rating.py
bc7de5f07aee8d14b6f2face371e984d845698bb9845bfbc51a247aefbddefef  goarena/referee.py
afe0884cae1ca23fcc9990430dd667dc086b7e7baec47d3d575a59aaf6001536  goarena/server.py
59fca0f1b84e290d8331190d543a501c3fd5c06b66de33efada6f0389e8c6f0b  goarena/sgf.py
736121b8e5ab553a9fd57c2cfb3885b91380a116d2bd027da36a3c87dfc58211  goarena/store.py
0740dc040f8c6e8150cb73ec3fc97ded50876b9f0106ae4f21f10ed2faf73d39  goarena/view.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  gotree/__init__.py
2a72ddeb8dece9485a62ab0e5cdd0368d408f5b617d1a8abf854e6c9025e4ba0  gotree/__main__.py
e32bcb3c4a24bbde2d0d2c31db0c5cc8408fcaf97475b21a44ce523df2464014  gotree/dag.py
9b2696a3939c783beb61484e2031562ed657f4bd06fd1c708b36baae5e111c7b  gotree/gtree.py
50f209814eb45d25f58653300ca4f567f64ebc80b321de9ab0bd03201ecba443  gotree/heuristics.py
a70fe1f8d3df5d41a750926701fd014a5177dd2e3e7ea63fa24f3ffe827b76fe  gotree/hl.py
b176bf8f268d7d1befe8e243c01c959a51e98e80e06e754500142d5253558fe2  gotree/jobs.py
9f2492eab2fba2ea4a22800547d60d73aad3f65920e982dfe0ae5129165aa5e3  gotree/judge.py
def5451435e3ae59a43ad50b4631d92c7d0a43c4d542a8b55a3ee31192c3d28d  gotree/memory.py
7f2987f0cdd8cc222e80c17dc838d63104aa13369ab29a76ecdcb92e2a6fcb89  gotree/perception.py
819ea0845f4035e74736a663cf921388d2e60b88fbda52489950ca5505cc96b4  gotree/play.py
dfe923bc3ca0f4b4c57eb351f4021be9ef0b178357e1e2f8de4665239e5d11d0  gotree/position.py
8b6774a111829e5ca7882a3c74e263bff405fcfa6df0e1dc2fa482de022858c7  gotree/probe.py
4a2079e675e975b46fad32610ced0fdac0213b75fbc05ce36f5dca7afce5c7d6  gotree/search.py
68aba712db5344a110a051c36136bafe192cdbc537eb2342315f518f279f5a25  gotree/user_heuristics_template.py
6bba94cec3bf414afa5be26cb0d184c0b9671db4607ab618cd7df3b1bd1f9b1e  gotree/workers.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  harness/__init__.py
5df27f9269eec59142008f261f26ad24760dd2fa914e9c859ec015ec64b17ba9  harness/arena_client.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  harness/dojo/__init__.py
84d050f42553ed1c826cacea8a0fe2179bff1e9371de446b3ad38d90a28c1659  harness/dojo/__main__.py
c8cac45964da3480c9c4d912b884c88465b365bcc2d9916b964656adb5546eff  harness/dojo/agent.py
6fa45ef82f618000ec2f20f746856f33c413ed850081c40a1c2887b4aae826f6  harness/dojo/llm.py
9bb5b7ceca789c0ea87365ebe0af3a6c6fe00947cc6e1c9185f0985a9f3cec94  harness/dojo/memory.py
11079c69d3e6c20820447a51236bf9d56fc75ed4e455eadc2f8f2cfc2ac1a55e  harness/dojo/prompts.py
2f27ba880d114f63b7be8215bd08515999a7312ad3d2044ae486a8ad4530349f  harness/runner.py
08b6f7bcd22836e4d4c89054171d556a61393cd94b1f5d556f41966245629dd3  harness/task.py
e5d9943702bb51c0b13a5891bf396d41a5b0d269f583ad57534e5021a32af50d  requirements-dev.txt
af1d882a2cc1717c9da20d96d963d2bf7f83b28f2a191612a17599e0e44ff3a5  requirements.txt
e032d112bc7ad4851ff0c92c67d6d934840e79eb78154a20a9f583dc4c1f9d5e  scripts/audit_run.py
aac839f24c7343411a9c50f6d9d8f7db2c6ffe020487accac09cc54d79720411  scripts/build_katago.sh
df32992fd55b0d54c175482aa364a7ce57076aa932d7d111879b36ef166759db  scripts/slurm/arena.sbatch
a2590da9bee2cdcd618393527aa4d5988863cef2568474b33d2be2cc798be022  scripts/slurm/play.sbatch
fd56882bac04d5b06cfc18ce6a8ec8b57414ff8561c0220885010999581cfbe6  scripts/slurm/probe.sbatch
a5e6a1f7ef60aab0708e8e78376b6193f8605715f14f34a298b49043d8ff29ab  tests/fake_cli_agent.py
8a3fa17b6e6b8f71dbf55f890ea56a9aa96073f01e59b42cc80c4df681a9eb0b  tests/fake_tree_agent.py
863616c6222d2519d4faa05b360b189a3051f21282fd364aeb8bae0a000a4099  tests/test_arena.py
bd7e54ffcad3a2c39f0df652bf105b75fcf89b4c4522680448528c9f255936bc  tests/test_board.py
595cbe200637b734521f81f9d99a30d7ee6eef8206c02e5233eabaf00ed6b394  tests/test_gotree.py
026e62278ce749b0a35d9619102a8f337564a72a490943dbd2eaae79846407a2  tests/test_harness.py
6a666593d76c09913ceb1120265916ee43f7efec5853cbab8e8a51431e3689a9  tests/test_regressions.py
e009fc7145f85a9b55c7fe3eee849f604d4e6fb4be11846c7559182aa23a00cb  web/index.html
```
