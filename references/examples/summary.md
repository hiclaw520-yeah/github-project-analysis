# 示例摘要（精简版）

> 完整报告见 `app-service-panwatch.md`（14KB），首次使用时读此摘要校准语气即可。

## PanWatch — app-service 类型，完整深度报告

**结论卡**：🟢 学习 3.9 / 🟡 使用 3.6。自托管 A 股盯盘+纸盘服务（FastAPI+React），交易规则建模与架构守护测试是最大亮点；单人项目+无风险声明是最大风险。

**结构要点**：单进程 FastAPI，4 个业务模块 + 4 个技术平台模块；`test_architecture_boundaries.py` 用 AST 强制分层规则；4 对循环依赖（1 硬 3 软）。

**核心链路**：APScheduler → BaseAgent(ABC) → FailoverAIClient → 通知去重 → agent_runs 落库，交易日历做闸门。对上游 TradingAgents 有 4.1k 行深度适配层（monkeypatch），版本落后 3 个 tag。

**评分要点**：D(4) 测试+迁移扎实但 CI 无 lint；F(3) 无风险声明是硬伤；H(4) 边界被强制但有环。

**报告结构**（校准用）：结论卡 → 架构图(Mermaid) → 核心链路 → 亮点(6条,每条带代价) → 取舍(结构/局部/风险) → 数据快照 → 同类对比矩阵(4个对手) → 九维评分表 → 声明核对表 → 红旗复核 → 建议阅读路线 → 局限。

---

> 更多示例见 `gallery-quick-reports.md`（四种不同类型的快速报告，9.5KB），按需加载。
