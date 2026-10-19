# 项目体检：TNT-Likely/PanWatch（参考示例 · 采集日期 2026-10-15）
> 注：本示例写于通用化重构之前，章节与现行模板略有差异（例如没有"类型/规模"行），可用于校准深度，不要照抄章节名。

> 示例用途：对照报告的结构、语气、证据写法。**数字会变，写新报告必须重新采集，不要复用。**

**一句话定位**：自托管的 A 股/港股/美股 AI 盯盘与持仓分析服务（FastAPI + React PWA），含价格提醒、定时 Agent、纸盘模拟，并深度适配上游 TradingAgents 做多智能体分析。
**评估目的假设**：学习其工程设计 + 评估能否自托管使用。
**证据强度**：较深入。读了 README、架构文档、边界测试、应用装配根、Agent 基类、TradingAgents 适配层入口、CI、依赖文件；跑了 `local_probe` / `arch_probe`；核对了 T+1、交易日历、CORS 鉴权；**对 3 个对手也克隆并跑了同一套脚本**，并核对了其中 2 条核心声明。**未通读**：策略逻辑、适配层全文、前端、failover 实现细节、对手核心逻辑全文；**未试跑**（沙箱无 Docker）。

## 结论卡
- 推荐度：🟢 学习（3.9）　🟡 直接使用（3.6）
- **核心是什么**：长驻的"调度 → Agent → AI(带 failover) → 通知(去重/策略)"流水线 + 显式的交易规则建模（日历/T+1/资金结算）；并用 4.1k 行适配层把上游多智能体框架改造成能吃 A 股数据。护城河属于**工程集成广度**，不是算法独创。
- 最大亮点：用 AST 测试把架构规则变成"会失败的测试"；交易规则各自成模块并各有测试；整体代码结构明显优于热度高得多的同类。
- 最大风险：**单人项目（98% 提交来自同一邮箱）+ 爆发式维护**；金融工具**未检索到风险声明**；依赖多为 `>=`；CI 无 lint/类型检查；固定的上游版本已落后 3 个 tag。
- 适合：想学模块化单体 + 架构守护 + 交易规则建模 + Agent 可观测的开发者。不适合：把其信号/评分当交易依据的人。

## 架构
```mermaid
flowchart TB
  FE["frontend (React/PWA)"] --> APP["bootstrap: FastAPI 唯一装配根"]
  APP --> M
  subgraph M["modules 业务层"]
    AUTO["automation<br/>Agent+调度(编排层)<br/>含 TradingAgents 适配层"]
    RES["research<br/>分析/信号"]
    STR["strategy<br/>信号·后验评估·调权"]
    MKT["market<br/>行情·价格提醒"]
    PT["paper_trading<br/>T+1·资金结算"]
  end
  AUTO <-->|硬环| RES
  AUTO -.->|软环| STR
  M --> P
  subgraph P["platform 技术层(不含业务决策)"]
    SCH["scheduling<br/>交易日历"]
    DATA["marketdata"]
    AI["ai<br/>FailoverAIClient"]
    NOTI["notifications<br/>去重/策略"]
    DB["persistence"]
  end
  DATA -.->|软环(函数内延迟import)| SCH
```
- 形态：单进程 FastAPI（`python server.py`）+ SQLAlchemy + APScheduler（3 处调度器）；前端另有内部 packages；4 个内部 Python 子包（marketdata / agent-runtime / token-meter / tool-research）。
- 枢纽：`platform.persistence`（被 14 个模块依赖）、`scheduling`、`marketdata`；编排层：`modules.automation`（依赖 12 个模块）。
- **边界**：`tests/test_architecture_boundaries.py` 强制——`platform` 不得 import `modules`、模块间不得互引 ORM、旧包必须已删除、`bootstrap` 是唯一应用工厂、router 归属模块。**未覆盖循环依赖**：脚本发现 4 对环，`automation ↔ research` 互相 import 公共函数（不碰 ORM，所以放行），实质是同一领域被拆成两半；`marketdata ↔ scheduling` 靠函数内延迟 import 绕开。
- 规模：Python 9.0 万行 / TS 3.8 万行；约 390 个路由装饰器、约 211 个 ORM 模型类。

## 核心链路与核心抽象
`APScheduler → BaseAgent(ABC：持有 AIClient、NotifierManager、NotifyPolicy、去重键) → FailoverAIClient(错误分类+冷却) → 通知(去重/节流/策略) → agent_runs 落库`，**交易日历作为闸门**决定是否执行。
核心抽象：`BaseAgent`、`FailoverAIClient`、`NotifyPolicy`+去重、`trading_calendar`、`paper_settlement`。
**上游集成（深度适配，非薄封装）**：`modules/automation/tradingagents/` 共 7 个文件 4124 行，`TradingAgentsAgent` 继承 `BaseAgent`，通过 **monkeypatch 上游 `route_to_vendor`** 与 `apply_compat_patches`，让上游改吃 PanWatch 的 A 股数据，并补上进度回调、token 计量、同日缓存。**因此锁版本是被迫的：固定在 `v0.5.0`，上游已到 `v0.6.0`（落后 0.5.1 / 0.5.2 / 0.6.0 三个 tag），升级成本高。**多智能体辩论与决策流程本身仍来自上游。

## 亮点（证据 — 解决什么 — 可迁移 — 代价）
1. ⭐⭐⭐ **架构规则变成会失败的测试** — `tests/test_architecture_boundaries.py`（`ast` 解析 import）— 防止分层被悄悄破坏 — 高 — 代价：只卡方向，不查环。
2. ⭐⭐⭐ **交易规则显式建模** — `scheduling/trading_calendar.py`、`paper_trading/paper_settlement.py`，三个专门测试文件 — 避免模拟盘高估收益 — 高 — 代价：日历数据需年更、ETF T+0/费率未建模（README 自述）。
3. ⭐⭐ **AI 调用的错误分类 + 冷却 failover** — `platform/ai/ai_failover.py`（`classify_ai_error`、`_is_cooling`/`_mark_fail`）— 单提供商故障不拖垮流水线 — 高 — 代价：状态持久化方式未核实。
4. ⭐⭐ **对上游的深度适配** — 4.1k 行适配层 — 把美股导向的框架变成 A 股可用 — 中 — 代价：monkeypatch 脆弱、升级成本高、版本已落后。
5. ⭐⭐ **内部子包拆分** — `packages/*` 各有 pyproject — 数据层与 Agent 运行时可复用 — 中 — 代价：多包版本维护。
6. ⭐ 可观测与引导（`agent_runs`+trace_id+可选 OTel；校验真实操作的新手引导）— 仅 README 层面，**未读实现**。

## 取舍与缺陷
- **结构性**：4 对循环依赖（新版脚本口径：**1 对硬环** `automation ↔ research`，另 3 对靠函数内延迟导入/TYPE_CHECKING 掩盖）；模块化单体靠"局部测试 + 自觉"守边界。
- **局部性（ast 实测）**：最长函数 `build_panwatch_tool_registry` **1260 行**（工具注册表）、`import_template` 520 行；>100 行函数 62 个（占 3%）；最长类 `AssistantRepository` 1193 行（4 个类在 900–1200 行）；15 个 >1000 行文件；**前端 `Stocks.tsx` 3085 行同时是最大变更热点（54 次）**，风险最高。
- **风险性**：单人 + 爆发式（6 月 65 次 → 7 月 2 次 → 8 月 4 次 → 9 月 29 次）；`requirements-runtime.txt` 23 项仅 1 项固定版本；**CI 无 lint/类型检查**（对比：DSA 有 flake8 与前端 lint，TradingAgents 有严格 ruff）；无风险声明；免费源爬取且 `verify=False`（有注释，东财证书链）；固定的上游版本落后 3 个 tag。
- **演进痕迹**：722 次历史改动落在已迁移/删除路径，测试断言旧包已移除——近期完成过大重构，是作者**已知且在偿还**的；早期版本升级需看 `migrations.py`（2311 行）。

## 数据快照（2026-10-15）
2.1k star / 378 fork（0.18，docker 部署，比值可直接解读）；47 开放 issue / 26 开放 PR（页面）；270 次提交（克隆内即全史），最近 1 天前；按邮箱头号作者 98%；测试行/源码行 0.35（`tests/` 下 146 项）；CI 8 个 workflow，跑 pytest 与多运行时/多时区矩阵；MIT。

## 同类对比（代码层指标均为同口径克隆实测；star 来源见备注）
| | **PanWatch** | **daily_stock_analysis**（直接竞品） | **TradingAgents**（上游） | **ai-hedge-fund**（替代路线） |
|---|---|---|---|---|
| 形态 | 长驻自托管服务（docker） | Actions / Docker / 本地 / 桌面端 | LangGraph 研究框架 + CLI | 教育向 CLI/TUI（当前自述不做真实交易；VISION 规划纸盘与可选实盘） |
| Star / Fork | 2.1k / 378（0.18） | **63.0k / 53.0k（0.84，推荐"Fork 后跑 Actions"）** | ≥95.7k / 18.5k（0.19）¹ | ≈62.8k / 11.1k（0.18）² |
| 协议 | MIT | MIT | Apache-2.0 | MIT |
| 提交作者(按邮箱) | 4 人，头号 98% | 66 人（近 400 次），头号 48% | 26 人，头号 81% | 51 人，头号 90% |
| 源码行 / 测试比 | 9.5 万 / 0.35 | **24.8 万 / 0.86** | 1.3 万 / **1.08** | 1.1 万 / 0.56 |
| 最长类 / >1000 行文件 | 1193 行 / 15 个 | **5471 行 / 55 个** | 425 行 / 0 个 | TUI 单文件 3207 行 / 1 个 |
| >100 行函数占比 | 3% | 3%（189 个） | 1% | 未测 |
| 依赖环 | 4 对（1 硬 + 3 软） | 1 对 | **0 对** | 未测 |
| 架构守护测试 | **有** | 未发现（有 CI 契约测试） | 无 | 无 |
| CI | pytest 矩阵，**无 lint** | 语法 + flake8 + pytest 3 分片 + 前端 lint/build/smoke | 1 个 workflow：pytest + **严格 ruff（全仓）** | **无 CI** |
| 风险声明 | **未检索到** | 有 | 有（研究用途） | 有（仅教育） |
| 商业化 | 打赏/赞助邮箱 | 赞助商横幅 + 多处邀请/联盟链接 | 未采集 | 未采集 |
| 核心能力 | 盘中监控 + 组合条件提醒 + 纸盘(T+1/结算) + 持仓 + 深度分析 | 每日决策仪表盘推送 + Web/桌面 + Agent 问股(15 种 YAML 策略，已核实) + 多数据源按优先级 fallback(已核实) + 回测/持仓 | 4 类分析师 + 多空辩论 + 风控 + 交易员；多模型提供商 | 多个 investor agent + 回测（净值曲线对比基准）+ TUI；纸盘/实盘仅在 VISION 规划中 |

¹ GitHub 官方组织页，页面显示 "Updated Jul 18, 2026"，早于克隆里的最近提交（2026-10-03），属缓存页，star 作下限；同日其他来源给出 63.7k / 69.4k / 91.7k，彼此矛盾。
² star-history 快照（2026-08-12，**二手来源**），未取到 GitHub 页面当前值。

- **定位**：PanWatch 是"功能纵深、规则建模与代码结构扎实"的自托管盯盘+纸盘平台，但分发与社区规模远不及头部的 daily_stock_analysis。
- **PanWatch 领先**：代码结构（无 >1200 行的类，对手 DSA 有 5471 行的上帝类）、架构守护测试、交易规则建模、组合条件价格提醒、OTel/运行记录。**落后**：社区规模（约 1/30）、风险声明、零服务器部署、数据源冗余与 CI 强度（DSA 更强）、测试比（DSA 0.86）、单人维护。
- **DSA 的真实情况**：赢在分发（5 分钟 Actions 零成本）、多市场、多数据源 fallback、CI 与测试体量；输在结构——4 个 3700–5500 行的上帝类，配置面持续膨胀（`.env.example` 被改 70 次，为最大热点）。
- **场景 → 选谁**：要 5 分钟零服务器拿每日报告 → daily_stock_analysis；要长驻盘中监控 + 纸盘验证想法 → PanWatch；要研究多智能体投研方法本身、代码最干净 → 读 TradingAgents；要学"investor agent + 回测 + TUI"的教育向实现 → ai-hedge-fund（当前自述不用于真实交易，纸盘/实盘为规划）；要学工程设计 → 读 PanWatch（边界测试、规则建模）+ DSA 的 `BaseFetcher`/`DataFetcherManager` 优先级 fallback 模式。
- **组合建议**：PanWatch 与 DSA 可并用（后者出日报、前者做盘中提醒与纸盘），迁移成本主要是通知渠道与自选股清单；若要升级 PanWatch 的 TradingAgents，需先评估 monkeypatch 兼容性。

## 九维评分
| 维度 | 分 | 关键证据 |
|---|---|---|
| A 热度真实性 | 4 | fork/star 0.18；有下载量与 Trending 徽章；有真实 issue/PR |
| B 维护与可持续 | 3 | 近期活跃但单人 + 爆发式；7–8 月几乎停更；上游落后 3 个 tag |
| C 代码质量 | 3.5 | TODO 仅 5 处；最长函数 1260 行（注册表）、15 个大文件 |
| D 工程可靠性 | 4 | `tests/` 下 146 项、迁移、agent_runs；CI 无 lint、依赖未固定 |
| E 文档与上手 | 4.5 | 一条 docker 命令；架构文档中英；引导与时区文档 |
| F 安全与合规 | 3 | MIT、无泄露；`verify=False` 有注释；CORS 通配已复核为低风险；**无风险声明** |
| G 学习价值 | 4 | 可迁移设计 ≥3 个；体量大需阅读路线 |
| H 架构与核心设计 | 4 | 边界被强制且覆盖多项；抽象清晰；但有 4 对环（1 硬 + 3 软） |
| I 竞争力与差异化 | 3.5 | 结构与规则建模领先；分发、社区、CI 弱于头部 |
**加权总评：学习 3.9 → 🟢；直接使用 3.6 → 🟡。**

## 声明核对 | 红旗复核
| README 承诺 | 结果 | 证据 |
|---|---|---|
| 多智能体 TradingAgents 深度分析 | ⚠ 部分（深度适配上游，核心流程来自上游） | 适配层 4124 行 + monkeypatch；固定 `v0.5.0`，上游 `v0.6.0` |
| A 股 T+1 禁止当日卖出 | ✅ | `paper_trading_engine.py` + 两个专门测试文件（`paper_trading_t1_locked`） |
| 内置交易日历与半日市 | ✅ | `trading_calendar.py`、`exchange_calendar_data.py`、`tests/test_trading_calendar.py` |
| 可选 OTel | ⚠ 未核实 | 仅读 README |

红旗：`verify=False`×5 → 有注释的有意取舍；`eval(` → JS 运行时自检（误报）；**CORS 通配 + credentials → 已复核为低风险**：鉴权为 `HTTPBearer`（Authorization 头），后端无任何 `set_cookie`，浏览器不会跨站自动携带；残余风险是 token 存 `localStorage`，可被 XSS 读取；无风险声明 → 真问题。

## 值得学的 3 点 / 应避开的坑
学：①边界测试 ②交易规则显式建模+测试 ③AI failover 的错误分类。
避：①不要照抄超大文件/超长函数的组织 ②不要把信号阈值当真理，需样本外验证 ③自部署前固定依赖、补 lint 与风险声明，并先评估上游升级兼容性。

## 建议阅读路线（约 100 分钟）
`src/ARCHITECTURE.en.md`(10) → `tests/test_architecture_boundaries.py`(10) → `src/bootstrap/application.py`(10) → `src/modules/automation/base.py` + `agent_scheduler.py`(20) → `src/platform/ai/ai_failover.py`(15) → `trading_calendar.py` + `paper_trading_engine.py` 及其测试(35)。

## 建议行动
学习：直接按上面读。使用：可自托管试用；上线前固定依赖版本、确认持仓数据发往哪个 LLM（可用本地 Ollama）、不要用其信号直接下单。**结论条件**：若补上风险声明、固定依赖并加 lint、出现第二位活跃维护者，使用评级可升为 🟢。

## 局限
未通读策略逻辑/前端/适配层全文；未试跑（沙箱无 Docker，依据静态阅读）；issue/PR 数来自页面快照；对手只读了结构与核心声明，未通读其核心逻辑；TradingAgents 的 star 为缓存页下限，ai-hedge-fund 的 star 为二手快照；DSA 作者数基于最近 400 次提交的浅克隆。
