# go-bench：用围棋衡量 long-horizon harness

这是 Peter Gostev 国际象棋实验（[AI Learning to Play Chess](https://ailearningchess.ai-learning-chess.workers.dev/)）的围棋版。每个"模型 + harness"组合拿到同一个目标：和分档的电脑对手连续下 N 盘（默认 200 盘）9 路棋，不更新权重，只靠自己记笔记、复盘来变强。要衡量的是：这套 harness 能不能在几天的长程任务里持续积累经验，而不是越下越乱。

整套系统包括：

| 组件 | 位置 | 作用 |
|---|---|---|
| 规则引擎 | `goarena/board.py`、`goarena/sgf.py` | 提子、禁自杀、全局同形、中国规则数子、坐标、SGF 读写 |
| Arena 服务 | `goarena/arena.py`、`goarena/server.py` | 对局管理、非法手和超时判负、SQLite 存储、HTTP API |
| KataGo | `goarena/katago.py`、`goarena/opponents.py`、`goarena/referee.py` | 分档对手、终局判死子、赛后逐手目损复盘 |
| 评分 | `goarena/rating.py` | 滚动 Elo（MAP，带 ±）、Elo 曲线、学习增益、分阶段得分率 |
| Agent 命令行 | `goarena/goban.py`（`bin/goban`） | agent 唯一的下棋接口，只依赖 Python 标准库 |
| Harness 层 | `harness/` | 统一任务（`TASK.md`）、战役 runner、Claude Code / Codex / 通用 CLI 适配器、自研的 **Dojo** harness |
| 网站 | `web/index.html` | 排行榜、Elo 曲线、Live 棋盘、对局回放（含每手目损图、SGF 下载） |

设计思路和取舍见 [DESIGN.md](DESIGN.md)。

## 第二部分：gotree（LLM 树搜索 + 分层记忆，目标是复现 AlphaGo 第 37 手）

| 组件 | 位置 | 作用 |
|---|---|---|
| 冻结局面 | `gotree/position.py` | 局面 = 棋子 + 轮到谁 + 劫点，不含手顺；8 重对称规范化，换位局面自动合并 |
| 感知层 | `gotree/perception.py` | Position Card：四边坐标棋盘、棋块表、征子、Benson 活棋判定、势力草图、局部窗口 |
| 局面 DAG | `gotree/dag.py` | 跨步、跨盘复用的显式搜索状态（SQLite） |
| 搜索 | `gotree/search.py` | PUCT、渐进加宽、根节点强制广度（非常规候选、九区侦察）、LLM 自博弈 rollout、反驳、决策 |
| 任务与 worker | `gotree/jobs.py`、`gotree/workers.py`、`gotree/gtree.py` | 每个任务一个新会话：Claude Code / Codex / API / mock；worker 用 `gtree` 读棋、提交答案 |
| 记忆 | `gotree/memory.py`、`gotree/hl.py` | 棋形教训库、概念 DAG、代码化启发式（Heuristic Learning） |
| 探针和裁判 | `gotree/probe.py`、`gotree/judge.py` | 第 37 手的发现曲线；KataGo 只做离线裁判，结果写在 run 目录之外 |

```bash
python -m gotree prior  --worker claude:opus:high --samples 10           # 先测：P10 会不会被提出来
python -m gotree probe  --worker claude:opus:high --budget 500 --workers 16 --judge
python -m gotree judge-values --run runs/<run>                            # LLM 估值与 KataGo 的一致程度
python -m gotree play   --worker codex:gpt-6.1-sol:high --opponent lv5 --games 2   # 在 arena 里下棋
python -m gotree lessons --run runs/<run>                                 # 以树的形式查看记忆
```

设计说明（每个问题的多种方案和默认选择）见 [TREE.md](TREE.md)；整理后的任务说明见 [docs/PROMPT.md](docs/PROMPT.md)；超算作业模板在 `scripts/slurm/`。

## 快速开始

依赖：Python 3.10+、`requests`；编译 KataGo 需要 g++、cmake、zlib。

```bash
pip install -r requirements.txt

# 1. KataGo：从源码编译 CPU 版，并装上仓库自带的两个小网络（b10c128、b6c96）
scripts/build_katago.sh          # 产物在 engines/；有 GPU 的机器请换 CUDA 后端和更强的网络
#   或者直接在仓库根目录解压 go-bench-engines-linux-x64.tar.gz（预编译，x86-64 + AVX2）

# 2. 启动 arena（网站也由它提供，打开 http://127.0.0.1:8765）
export GOARENA_ADMIN_TOKEN=change-me
python -m goarena serve --port 8765 --tiers config/tiers-9x9.json
#   常用参数：--review-visits 64（赛后复盘强度，0 关闭）、--move-timeout 3600、
#             --max-illegal 10、--viewer-token X（给网站和公开 API 加口令，正式跑时建议开启；
#             之后用 http://127.0.0.1:8765/?key=X 打开网站）
#   进行中的 run 的引擎复盘对公开接口隐藏（防止 agent 通过 API 拿到引擎反馈），带口令可见，run 结束后公开。

# 3. 跑一个 run（runner 会建 run、准备工作区、反复拉起 agent 直到 200 盘下完）
python -m harness.runner --harness claude-code --model claude-opus-5-5 --reasoning high \
    --name "Opus 5.5 / Claude Code" --games 200
python -m harness.runner --harness codex --model gpt-6.1-sol --reasoning high \
    --name "GPT-6.1 Sol / Codex" --games 200
python -m harness.runner --harness dojo --provider anthropic --model claude-opus-5-5 --reasoning high \
    --name "Opus 5.5 / Dojo" --games 200
python -m harness.runner --harness dojo --provider openai --model gpt-6.1-sol --reasoning high \
    --name "GPT-6.1 Sol / Dojo" --games 200

# 其他 CLI agent：通用适配器，用模板描述命令行
python -m harness.runner --harness cmd --cmd "gemini -p {prompt} -m {model} --yolo" --model MODEL_NAME \
    --name "Gemini / Gemini CLI" --games 200

# 不用 API key 也能试跑整条链路：mock 模型（会走完复盘、整理等所有环节，但棋力没有意义）
python -m harness.runner --harness dojo --provider mock --model mock --name "Mock / Dojo" --games 10
```

每个 run 的文件在 `runs/<run id>/` 下：`workspace/` 是 agent 能看到的全部内容（`TASK.md`、`bin/goban`、它自己的笔记），`logs/` 是 runner 记录的每个会话的完整输出。

### 手动下一盘（也就是 agent 看到的界面）

```bash
python -m goarena create-run --name "me" --games 5        # 打印 run 的 token
export GOARENA_URL=http://127.0.0.1:8765 GOARENA_TOKEN=gat_...
bin/goban rules
bin/goban opponents
bin/goban new --opponent lv3
bin/goban play E5
bin/goban status
bin/goban show 1 --sgf
```

## 对手阶梯（9 路，贴 7.5，中国规则）

| 对手 | 下法 | 校准 Elo |
|---|---|---|
| random | 随机合法手（不填自己的眼） | 0（锚点） |
| lv1 | KataGo 策略网络，70% 随机手 | 409 ± 72 |
| lv2 | KataGo 策略网络，50% 随机手 | 592 ± 64 |
| greedy | 一步战术：能吃就吃、逃叫吃、不自紧气；无搜索 | 668 ± 78 |
| lv3 | KataGo 策略网络，35% 随机手 | 865 ± 77 |
| lv4 | KataGo 策略网络，20% 随机手 | 1173 ± 70 |
| lv5 | KataGo 策略网络，10% 随机手 | 1259 ± 70 |
| lv6 | KataGo 策略网络，4% 随机手 | 1506 ± 77 |
| lv7 | KataGo 策略网络原样输出，无搜索 | 1850 ± 89 |
| lv8 | KataGo 32 visits | 2064 ± 107 |
| max | KataGo 600 visits（不计入 Elo，和象棋版的 Max 档一样） | 未校准 |

各档 Elo 用 `python -m goarena calibrate` 跑循环赛（每档和相邻两档各下 12 盘，共 204 盘，原始对局记录在 `config/calibration-games-9x9.jsonl`），再做 Bradley–Terry 拟合得到，以 random = 0 为锚点，已写入 `config/tiers-9x9.json`。这个刻度是内部刻度，不对应人类段位，也不对应国际象棋的 Elo。lv1–lv7 每手只评估 1 次网络、不做搜索，所以棋力和硬件无关，可以跨机器复现。

## 网站

arena 自带一个单页网站：排行榜（Elo ± 标准误、学习增益、对各档得分的色块、非法手、每手目损）、各 run 的 Elo 曲线、Live 棋盘、对局回放（逐手浏览、每手目损柱状图、SGF 下载）。下面是用 mock 模型跑的 40 盘演示数据：

![run 页面](docs/screenshots/run.png)
![对局回放](docs/screenshots/game.png)

mock 模型用的就是 greedy 那一档的启发式下法，最后被评到 800 ± 63，和 greedy 档的校准值 668 ± 78 在误差范围内一致。这算是对评分系统的一个端到端检查。

## 反作弊审计

```bash
python scripts/audit_run.py runs/<run id>     # 检索会话日志和工作区里的引擎、搜索算法、安装、联网痕迹，并列出引擎吻合率异常的对局
```

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests
```

测试覆盖（共 49 个）：规则（提子、打劫、全局同形、自杀、数子、SGF 往返）、arena HTTP 全流程（非法手上限、认输、鉴权、重启后恢复对局、暂停不计时、对手回复中断后重新同步、公开接口隐藏引擎复盘）、Dojo 在 mock 模型下的完整战役（含 episodic 和 single 两种上下文模式，以及崩溃后接着下）、runner 的反复拉起逻辑（用一个假的 Claude Code CLI）；gotree 的对称与换位、征子与 Benson、DAG 回传、Claude Code 任务目录协议、API 工具循环、记忆整理、第 37 手探针和 arena 整盘对局。测试不需要 KataGo。
