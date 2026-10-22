# Changelog

本项目版本号写在 `SKILL.md` 的 `metadata` 块中，遵循语义化版本。

## [1.1.4] — 2026-10-21

### Fixed

- 带 BOM 的 SKILL.md 被误判为缺少 frontmatter（`content_probe.py`）
- 中文 description 被"过短"阈值误判为触发线索不足
- 性能截断时静默无提示，现在输出明确截断警告

## [1.1.3] — 2026-10-20

### Fixed

- 非 UTF-8 编码环境下 `arch_probe.py` / `content_probe.py` 输出崩溃（统一 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`）
- Windows 中文路径转义漏检（`os.fsdecode` 兜底）
- 提交历史在浅克隆补全失败时静默丢失数据，现在标注"补全失败"

### Changed

- 清理 `page_probe.py` / `gh_probe.py` 中的死代码
- README 补全文件树
- 依赖图节点数过多时自动降级（邻接矩阵 → 边列表）

## [1.1.2] — 2026-10-19

### Added

- Windows 兼容性：路径分隔符、管道输出编码（GBK / cp1252 模拟）
- 一键打包分发（`package.cmd` / `package.sh` / `scripts/package.py`）
- `.gitattributes` 行尾规范：`cmd=CRLF` / `sh=LF`，开发期文件 `export-ignore`

### Fixed

- Windows 路径分隔符导致脚本失效与误报
- 文档打磨：README 结构、使用前提、安装方式

## [1.1.0] — 2026-10-19

### Added

- 初始发布
- 七步工作流：确认目的 → 采集数据 → 类型识别 → 深度阅读 → 同类对比 → 九维评分 → 输出报告
- 8 种项目类型分析手册（`references/archetypes/`）
- 3 个领域专项清单（量化交易、AI Agent、安全双重用途）
- 7 个数据采集脚本（`scripts/`，纯标准库）
- 九维评分体系与类型权重调整表（`references/rubric.md`）
- 2 份完整示例报告（`references/examples/`）
- 安全守则：符号链接防护、git 危险配置屏蔽、只读克隆