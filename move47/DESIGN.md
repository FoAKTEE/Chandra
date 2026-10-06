# 设计文档：围棋 long-horizon harness benchmark

## 1. 要测什么

模型训练完以后权重就固定了。我们想知道的是：一个 agent（模型 + harness）能不能在一个持续好几天、跨越数百次交互的任务里，只靠自己写笔记、复盘和管理上下文，把某件事越做越好。

Gostev 的国际象棋实验给出了一个很干净的设定：和 Stockfish 下 200 盘，自己选对手档位，禁止调用引擎。结果 Claude Opus 5.5（跑在 Claude Code 里）从 1500 左右涨到 1760；GPT-6 Astra（跑在 Codex 里）则从 1810 掉到 1400。作者怀疑后者是上下文被越积越多的笔记拖垮了，但没有做对照实验。

这个 benchmark 把那个设定搬到围棋上，并补上三样东西，让它从一次演示变成可以重复的测量：

1. **校准过的对手阶梯**，并且对手强度不依赖硬件。
2. **比胜负更细的指标**：每手目损、分阶段得分率、学习增益。
3. **把 harness 当作自变量**：同一个模型可以换 harness 跑；我们自己写的 Dojo harness 的每个组件都能单独关掉，用来做消融。

## 2. 架构

```
 ┌──────────── agent 沙箱 ────────────┐        ┌──────────────── arena 服务 ────────────────┐
 │ 模型 ⇄ harness（Claude Code /      │  HTTP  │ 规则引擎 ── 对局管理 ── SQLite（runs/games/  │
 │        Codex / Dojo）               │ ─────► │                          moves/illegal/events）│
 │ 工作区：TASK.md、bin/goban、笔记    │ run    │ KataGo（一个进程）：分档对手 / 裁判 / 复盘    │
 └─────────────────────────────────────┘ token  │ 公开只读 API ──► 网站（排行榜、Live、回放）    │
          ▲                                     └────────────────────────────────────────────┘
          │ 反复拉起，直到 N 盘下完                         ▲ admin token
 ┌────────┴──────── runner（每个 run 一个）────────────────┘
```

- agent 只能通过 `goban` 命令或等价的 HTTP API 下棋，凭 run token 鉴权。它拿不到 admin token，也看不到 KataGo。
- 数据库是唯一的状态来源。arena 重启后，会把进行中的对局按已存的着手重放出来，接着下。
- 一个 KataGo 进程同时为所有对手档、裁判和复盘服务。复盘请求用低优先级，不会拖慢正在进行的对局。

## 3. 规则与对局协议

| 项目 | 设定 | 理由 |
|---|---|---|
| 棋盘 | 9×9（`--size` 可改为 13） | 一盘 60–100 手，和国际象棋一盘的长度接近；200 盘的成本可控 |
| 规则 | 中国规则（数子），贴 7.5 目，禁自杀，全局同形禁止（positional superko） | 贴半目就不会有和棋；数子不需要双方协商死活 |
| 终局 | 连续两次 pass 或认输。由裁判用 KataGo ownership 判死子（某块棋的归属值反向超过 0.5 即判为死子），再数子 | 模型不必参与死活确认，也就避免了这一步的争议 |
| 过早 pass | 对手会继续下；没有下完的地方谁都不算 | 不鼓励靠 pass 混过终局 |
| 手数上限 | 3×N²（9 路为 243 手），到上限后按现状数子 | 防止无限循环 |
| 非法手 | 拒绝并计数。单盘超过 10 次判负 | 非法手率本身就是一个指标（象棋版也统计了这一项） |
| 超时 | agent 60 分钟不落子判负 | 防止会话挂住后卡死整个 run |
| 对手认输 | KataGo 档在自己胜率 < 2%、落后 > 15 目时，连续 3 手后认输 | 节省时间；此时局面已经客观输定 |
| 执色 | 默认按盘号黑白交替，agent 也可以自己指定 | 和象棋版一样，选择权交给模型 |
| 并发 | 每个 run 同一时间只能有一盘在下 | |

## 4. 对手阶梯与校准

**为什么不直接用"段位"做标签。** Stockfish 的 skill level 和 UCI_Elo 都有已知的刻度压缩问题，所以象棋版在文章里也特意说明"1760 不等于人类 1760"。围棋这边，KataGo 的 human-SL 模型（可以模仿各个段位的人类）本来是最理想的阶梯。但它需要从 katagotraining.org 下载，而我们当前的构建环境访问不了这个站点。所以先用一个能复现、并且自己标定过的阶梯：

- `random`、`greedy`：不用引擎的基线。
- `lv1`–`lv6`：KataGo 策略网络（g170e-b10c128），按 ε 的概率改下随机手（ε = 0.7 → 0.04）。这和 Stockfish skill level 故意弱化的思路一致，但档位之间的过渡平滑得多。
- `lv7`：策略网络原样输出。`lv8`：32 visits 的搜索。`max`：600 visits，不计入评分。

`lv1`–`lv7` 每手只做一次网络推理，**棋力和硬件、时间都无关**。只有 `lv8` 和 `max` 依赖 visits，而 visits 同样不随硬件变化。所以同一份配置在不同机器上测出来的强度是一样的。

**校准方法**：`python -m goarena calibrate` 让每一档和相邻的两档各下 12 盘（黑白各半），用 Bradley–Terry 拟合（坐标上升法，每个选手加一个弱先验），以 random = 0 为锚点，结果写入 tier 文件。

**实测结果**（2026-10-05，204 盘）：random 0、lv1 409、lv2 592、greedy 668、lv3 865、lv4 1173、lv5 1259、lv6 1506、lv7 1850、lv8 2064（标准误 ±64 到 ±107）。相邻两档相差 76 到 409 分，强的一方的期望得分大约在 61% 到 91% 之间。所以无论 agent 落在哪个区间，附近都有能分出胜负的对手。一个意外发现是：不用引擎的 greedy 比 lv1、lv2 还强，说明掺入大量随机手的 KataGo 弱得很快。

**以后的升级**：换成 human-SL 网络（`b18c384nbt-humanv0`）的 `humanSLProfile`（例如 `rank_20k` … `rank_1d`），这样阶梯就能直接对应人类段位。代码只需要在 `opponents.py` 里加一种 kind。

## 5. 指标

| 指标 | 怎么算 | 说明 |
|---|---|---|
| **Elo** | 对最近 50 盘对**计分档**的结果做 MAP 拟合（对手 Elo 固定为校准值），并报告 ± 标准误 | 和象棋版"最近 50 盘、不含 Max 档"同口径，但多了不确定度 |
| **学习增益 Gain** | 当前 Elo 减去第一个完整窗口（前 50 盘）的 Elo | 直接回答"有没有越下越强"，是首要的 harness 指标 |
| Elo 曲线 | 每盘之后的滚动 Elo | 网站上可以看 |
| 分阶段得分率 | 把 run 平均切成 4 段，统计每段对每一档的得分率 | 文章里用来说明 Opus 进步、Astra 退步的就是这张表 |
| **每手目损** | 赛后用 KataGo（默认 64 visits）复盘：走这步之前和之后，局面估值从行棋方视角看下降了多少目 | 比胜负稳定得多。还按布局 / 中盘 / 官子拆开统计（9 路按手数划分：前 20% / 20–60% / 其余） |
| 恶手数 | 单手损失 ≥ 5 目的次数 | |
| 引擎吻合率 | agent 的着手和 KataGo 首选相同的比例 | 作弊监测：吻合率远高于同等水平应有的值时，标记出来复查 |
| 非法手 | 被拒绝的着手次数，按原因分类（占位、自杀、劫、坐标错误） | 衡量状态跟踪能力 |
| 用时、token | 每盘的墙钟时间、每手思考时间；Dojo 额外记录每次调用的 token | 衡量成本 |

## 6. 实验协议

1. **相同的任务文本**：所有 harness 拿到的都是同一份 `TASK.md`（`harness/task.py`）。Claude Code 和 Codex 读到的是工作区里的这个文件（另有 `CLAUDE.md` / `AGENTS.md` 指向它）；Dojo 把同样的规则和目标写进自己的 system prompt。
2. **相同的监督方式**：runner 对所有 harness 一视同仁。会话结束但 run 还没完成，就用固定的 continue 提示重新拉起；连续 3 个会话没有任何进展就停下。`--resume-mode resume` 可以让 Claude Code / Codex 在重新拉起时接回上一个会话（会把上下文管理的压力留给 harness 自己），默认 `fresh` 则是新开会话、只靠文件延续。这两种方式本身也是可以比较的条件。
3. **重复**：每个配置至少跑 3 个 run。200 盘的 Elo 标准误在 ±60 左右，只跑一次，只能分辨出很大的差距。
4. **对照组**：Dojo 的 `--memory none`（每盘都从零开始）是"无学习"基线。某个配置的 Gain 和它的差，才是真正的学习效应。
5. **预算**：`--max-hours`、`--session-timeout`、每个 run 的盘数都可以设置，所有条件要保持一致。

## 7. Harness 层

### 7.1 Claude Code / Codex 适配器

- Claude Code：`claude -p <prompt> --output-format stream-json --verbose --dangerously-skip-permissions --model … --effort …`
- Codex：`codex exec --json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C <ws> -m … -c model_reasoning_effort=…`
- 其他 CLI agent（Gemini CLI、OpenHands、自研 agent 等）用通用适配器 `--harness cmd --cmd "<模板>"` 接入，模板里可以用 `{prompt}` `{model}` `{reasoning}` `{workspace}` `{session_id}`。
- 会话 id 从输出流里解析出来，供 `--resume-mode resume` 使用。命令行参数的具体写法请以你们所用的 CLI 版本为准（集中写在 `harness/runner.py` 的适配器类里）。
- 正式跑时，用 `--wrap "docker run --rm -i -v {workspace}:/work -w /work --network arena-only … image"` 把 agent 关进只能访问 arena 和模型 API 的容器。

### 7.2 Dojo：为长程学习设计的 harness

Dojo 的出发点是象棋版里 Astra 的退化假说：上下文随着笔记一起增长，最后把模型拖垮。所以 Dojo 用结构来约束上下文。

| 机制 | 做法 | 针对的问题 |
|---|---|---|
| **按盘开新上下文** | 每盘棋都从全新的上下文开始，只注入有大小上限的长期记忆 | 上下文长度不随已下盘数增长（测试里检查了单次调用不超过 2 万字符） |
| **盘内滑动窗口** | 只保留最近 6 轮原文；更早的棋盘输出替换成"已省略"，完整着手序列和 agent 自己写的 `plan` 每轮都会重新注入 | 单盘之内的长程问题：避免几十份过期棋盘混在上下文里 |
| **结构化长期记忆** | `playbook`（有字数上限，只能通过 add / update / delete 编辑，超出时淘汰最久没更新的条目）、`plan`（训练计划）、`opponents`（对手笔记）、`journal`（每盘一行）、`reviews/`（完整复盘，只能检索，不会整体注入） | 笔记无限膨胀、新旧结论混在一起 |
| **赛后复盘** | 在单独的上下文里完成，没有引擎评估。agent 可以用 `board_at(n)` 查看任意一手的局面，然后提交复盘、日志、playbook 修改和对手笔记 | 把一盘棋变成可复用的教训 |
| **定期整理（教练环节）** | 每 10 盘根据各段战绩、日志和最近的复盘重写 playbook 和训练计划 | 去重、淘汰无效原则、调整选对手的课程 |
| **崩溃恢复** | 状态全部在文件和 arena 里；重启后会补做漏掉的复盘，接着下进行中的那盘 | 一个 run 要跑好几天 |
| **可观测性** | `usage.jsonl`（每次调用的 token、延迟、上下文大小）、`transcripts/`、`memory_ops.jsonl`（每次记忆修改） | 方便事后归因 |

**消融开关**（每个都对应一个可以检验的假设）：

| 开关 | 检验的问题 |
|---|---|
| `--memory none / journal / full` | 长期记忆到底贡献了多少 |
| `--no-reflect` | 独立的复盘环节有没有用 |
| `--consolidate-every 0` | 定期重写记忆能不能防止退化 |
| `--context single --compact-chars N` | 一条对话贯穿所有盘、满了再压缩（也就是通用 harness 的做法）。用来直接检验 Astra 的上下文假说 |
| `--window N`、`--full-boards N` | 盘内需要保留多少历史 |
| `--playbook-chars N` | 记忆预算的大小 |
| `--python-tool` | 给模型一个受限的代码执行工具（30 秒、无网络），和 Claude Code / Codex 能写脚本的条件对齐 |

Dojo 支持 Anthropic Messages API（adaptive thinking + effort，会完整回传 thinking block）、OpenAI Chat Completions（兼容任意 OpenAI 格式的端点），以及离线的 mock。

## 8. 防作弊

- **规则**：禁止使用、下载或编写任何围棋引擎、搜索算法或神经网络来选点，违反则整个 run 作废（写在 TASK.md 里）。允许写辅助脚本，例如显示棋盘、数气、解析棋谱、做统计。
- **隔离**：agent 的工作区里只有任务文件、`goban` 和它自己的文件。正式跑时用 `--wrap` 放进容器，网络只放行 arena 和模型 API。
- **不泄露引擎反馈**：agent 知道 arena 的地址，理论上能访问公开 API。所以对还在进行中的 run，公开接口一律隐去 KataGo 复盘（每手最佳点、目损、吻合率），只有带 admin token 或 `--viewer-token` 口令的请求才能看到；run 结束后自动公开。设置了 `--viewer-token` 之后，整个公开 API（包括别的 run 的棋谱）都需要口令，正式跑时建议开启。
- **审计**：runner 保存了每个会话的完整输出，可以检索 `katago`、`gnugo`、`leela`、`pip install`、`mcts` 等关键词。引擎吻合率异常时，人工复查。
- **重复对局**：对手档本身带随机性（采样加随机手），背下某盘的赢棋照搬是行不通的。这正是"时间循环"那道题里的解法。

## 9. API 一览

| 范围 | 方法与路径 | 说明 |
|---|---|---|
| 公开 | `GET /healthz` | 健康检查 |
| agent | `GET /api/agent/rules`、`/opponents`、`/status`、`/board`、`/games`、`/games/{n}[?format=sgf]` | 读取规则、对手、进度、棋局 |
| agent | `POST /api/agent/new {opponent, color?}`、`/play {move}`、`/resign` | 下棋 |
| 公开 | `GET /api/leaderboard`、`/api/runs/{id}`、`/api/games/{id}[?format=sgf]`、`/api/live`、`/api/events?after=`、`/api/tiers` | 网站用的只读接口 |
| admin | `POST /api/admin/runs`、`GET /api/admin/runs`、`POST /api/admin/runs/{id}/status`、`POST /api/admin/games/{id}/review` | 建 run、暂停 / 恢复、重做复盘 |

所有 agent 接口都会返回一个 `text` 字段（渲染好的棋盘和提示），`goban` 直接打印它。这样不同 harness 看到的观测完全一致。

## 10. 已知限制与下一步

- 现在用的是仓库自带的小网络（b10c128）和 CPU 推理。在 2 核机器上，`max` 档每手要几秒。正式跑建议用 GPU 和更强的网络。网络变了，`lv` 档就要重新校准。
- 分档 Elo 是相对 random 的内部刻度，不对应人类段位。接入 human-SL 网络之后，可以给出"等效段位"。
- 9 路的布局空间比较小，有可能被背谱。可以加一个 13 路赛道（只需要改 `--size` 和 tier 文件）。
- 复盘只在 9 路上用 64 visits；19 路需要更多 visits 和 GPU。
- Codex 的 resume 参数写法依赖 CLI 版本，默认的 `fresh` 模式不依赖它。
