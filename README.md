# GitHub 项目体检（Universal GitHub Project Review）

> 给任意 GitHub 仓库做一次有证据支撑的全面体检——分类、画像、评分、同类对比，20–40 分钟出报告。

## 这是什么

一个面向 AI Agent 的项目评估技能包（Skill）。输入一个 GitHub 仓库链接或 `owner/repo`，输出一份结构化体检报告，覆盖架构质量、可信度、安全风险、学习价值与同类竞争力。

不是 code review，不是 API 用法问答，是站在"要不要学、能不能用、有没有坑"的视角对陌生仓库做尽职调查。

## 支持的项目类型

| 类型                           | 典型特征                             |
| ------------------------------ | ------------------------------------ |
| 应用 / 服务                    | 有运行时入口、部署配置、业务逻辑分层 |
| 库与框架                       | 提供 API 供他人调用，有版本管理      |
| CLI / 开发工具                 | 命令行入口，面向开发者日常使用       |
| Agent 技能包 / 插件 / MCP 服务 | 提示词、hooks、工具定义、权限面      |
| 文档与内容合集                 | 以 Markdown/文档为主体，无运行时代码 |
| 研究与模型代码                 | 论文复现、实验代码、notebook 驱动    |
| 模板与配置                     | 脚手架、starter、配置集合            |
| 小型脚本                       | 单文件或少量文件，解决特定问题       |

## 工作流程

```
确认目的 → 采集数据 → 识别类型并画像 → 读代码/内容 → 同类对比 → 九维评分 → 领域补充 → 输出报告
```

1. **采集客观数据**：页面探测 → 只读克隆 → 本地体检 → API 体检（可选）
2. **自动分类**：脚本输出项目类型、规模档位、领域线索和建议分析路径
3. **深度阅读**：按类型手册的必读文件清单，追踪主链路、核对声明、复核红旗
4. **同类对比**：选 3–5 个竞争对手，同方法同日采集，输出对比矩阵
5. **九维评分**：热度真实性、维护、质量、验证、文档、安全合规、学习价值、结构设计、竞争力
6. **领域专项**：量化交易、AI Agent、安全双重用途等领域有专项检查清单
7. **输出报告**：结论卡 → 架构图 → 核心链路 → 亮点与取舍 → 评分表 → 行动建议

## 九个评估维度

维度对所有类型通用，**具体看什么信号随类型变化**（细则见 `references/rubric.md`）。

| 维度                  | 关键问题                                           | 随类型变化的例子                                                    |
| --------------------- | -------------------------------------------------- | ------------------------------------------------------------------- |
| A 热度真实性          | Star 是真实的还是异常增长？                        | 异常增长只标"未核验"，不下"刷星"结论                                |
| B 维护与可持续        | 还活着吗？谁在维护？能持续多久？                   | 内容类看更新与勘误；单人/爆发式提交要说明                           |
| C 质量（代码 / 内容） | 代码类看体量与类型；内容类看具体性、准确性、一致性 | 技能包看 description 触发质量与规范合规                             |
| D 验证与可靠性        | 怎么知道它是对的？                                 | 应用看测试/CI；内容看校验器与链接；研究看可复现                     |
| E 文档与上手          | 能在 30 分钟内跑起来吗？                           | 技能包看安装方式与多平台适配                                        |
| F 安全、合规与风险    | 许可证、密钥、数据去向、风险声明                   | 插件/MCP 额外看 hooks、安装器、权限面；双重用途看护栏在文字还是代码 |
| G 学习价值            | 值得精读吗？能学到什么？                           | 体量大时给出"只读哪几个文件"的路径                                  |
| H 结构与核心设计      | 边界清晰吗？核心抽象是什么？                       | 内容类看信息架构；硬环与"延迟导入掩盖的环"分开写                    |
| I 竞争力与差异化      | 同类中为什么选它？                                 | 分发能力与技术质量分开写                                            |

## 项目结构

```
github-project-review/
├── SKILL.md                          # 技能入口：触发条件、工作流骨架、安全守则、各步指向
├── README.md                         # 你正在看的这个
├── LICENSE                           # MIT
├── package.cmd                       # 打包入口（Windows 双击）
├── package.sh                        # 打包入口（Unix）
├── .gitignore                        # 忽略 dist/、__pycache__/、tests/.baseline/
├── .gitattributes                    # 行尾规范：cmd=CRLF / sh=LF（跨平台）
├── .github/workflows/ci.yml          # CI：ubuntu/windows × Python 3.8/3.12 跑测试
├── tests/test_probes.py              # 自动化测试（夹具驱动的集成测试 + 纯函数单测）
├── tools/make_fixtures.py            # 离线夹具生成器（攻击/边界样本仓库 ×9 类）
├── tools/run_regression.py           # 回归比对器：改动前 baseline、改动后 compare
├── references/
│   ├── architecture-core.md          # 主链路追踪方法
│   ├── rubric.md                     # 九维评分细则与权重表
│   ├── extra-checks.md               # 容易遗漏的检查项（含安全守则）
│   ├── peer-comparison.md            # 同类对比方法论
│   ├── purpose-routing.md            # 第 0 步目的路由表
│   ├── report-template.md            # 报告输出模板
│   ├── archetypes/                   # 8 种项目类型的分析手册
│   │   ├── app-service.md
│   │   ├── library-framework.md
│   │   ├── cli-devtool.md
│   │   ├── agent-skill-plugin.md
│   │   ├── content-collection.md
│   │   ├── research-model.md
│   │   ├── template-config.md
│   │   └── script-tool.md
│   ├── domains/                      # 领域专项检查清单
│   │   ├── README.md                 # 四问模板（通用降级方案）
│   │   ├── quant-trading.md
│   │   ├── ai-agent-llm.md
│   │   └── security-dual-use.md
│   └── examples/                     # 示例报告
│       ├── summary.md                # 精简摘要（首次校准用）
│       ├── app-service-panwatch.md   # 完整深度报告
│       └── gallery-quick-reports.md  # 四种类型的快速报告
└── scripts/                          # 数据采集与分析脚本
    ├── page_probe.py                 # 页面数据探测（无需 API 额度）
    ├── local_probe.py                # 本地仓库体检
    ├── gh_probe.py                   # GitHub API 体检（常 403）
    ├── classify_repo.py              # 类型识别与画像建议
    ├── arch_probe.py                 # 运行时代码架构分析
    ├── content_probe.py              # 内容/文档型仓库分析
    └── package.py                    # 一键打包分发 zip（仅维护者环境，分发包不含）
```

> 上面 `package.cmd` / `package.sh` / `.github/` / `tests/` / `tools/` 与 `.gitignore`、`.gitattributes` 只存在于开发环境，`export-ignore` 已把它们排除在分发包之外；分发包里 `scripts/` 只有 6 个探针脚本。

## 设计原则

- **先分类，再评估**：不同类型"好"的标准不同，不拿测试覆盖率衡量纯文档仓库
- **热度 ≠ 质量**：Star 只证明"被看到"，热度异常要标注并核验
- **声明 ≠ 现实**：README 是营销文案，挑 3 条最强承诺验证
- **脚本是线索，不是结论**：依赖图、正则命中都要回到代码里核实
- **亮点必须成对写代价**：只夸不批的清单是营销稿
- **诚实标注证据强度**：没读的不评价，没采集到的写"未采集/未核验"

## 使用前提

- Python 3.8+，Windows / Linux / macOS（已在 Windows 上实测：路径分隔符、管道输出编码（GBK / cp1252 模拟）、中文文件名仓库、带 BOM 的 SKILL.md 均正常。1.1.2 修复 Windows 路径分隔符导致的脚本失效与误报；1.1.3 修复非 UTF-8 编码下的输出崩溃与提交历史静默丢失、中文路径转义漏检；1.1.4 修复带 BOM 的 SKILL.md 被误判为缺少 frontmatter、中文 description 被"过短"阈值误判、性能截断静默无提示；1.1.5 修复单技能仓库被误判为内容合集、注入正则的常见词误报、LICENSE 检测两处偏差，并增强依赖统计（-r 展开、锁文件检测、monorepo 任意层级）；1.1.6 修复开发辅助技能（.claude/skills/ 等）误压制内容分类、-r 展开绕过读文件防护两个 1.1.5 回归，并修正 3.8 分结论边界；1.1.7 补混合语言仓库的函数测量标注（仅 Python）与示例报告的采集日期/引用免责）
- git（只读克隆）
- 网络访问 GitHub

## 安全设计

这个技能分析的是**不可信仓库**，脚本因此内置了防护：

- 读文件时**拒绝符号链接**并要求真实路径在仓库内，防止恶意仓库借软链接把沙箱内其他文件读进报告
- 所有 git 调用禁用仓库自带的 `core.fsmonitor` / `core.sshCommand` / `hooksPath`，分析别人给的现成目录（含 `.git`）不会触发其中的命令
- 自动补全浅克隆历史只对 `https://` 的 origin 执行
- 工作流层面：仓库文字当数据不当指令；不执行未审阅的仓库代码

## 安装

将本目录放入 Agent 的 skills 路径下即可，脚本只用标准库，无需 `pip install`。

> 以下打包入口**仅供仓库维护者**使用；使用者把目录放进 skills 路径即可，无需打包。

**打包分发时不要带上 `.git/`**（会带上远程地址、提交者邮箱等信息）。一键打包（内容 = HEAD 提交，自动读版本号命名，产物在 `dist/`，天然不含 `.git/`，开发期文件如打包脚本本身经 `export-ignore` 排除）：

- Windows：双击 `package.cmd`
- Unix：`./package.sh` 或 `python3 scripts/package.py`

## 版本

当前版本 1.1.7（2026-10-23）。版本号写在 `SKILL.md` 的 `metadata` 中。变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可

[MIT License](LICENSE) © 2026 hiclaw520 <hiclaw520@yeah.net>
