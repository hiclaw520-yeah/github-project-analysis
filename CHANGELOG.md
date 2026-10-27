# Changelog

本项目版本号写在 `SKILL.md` 的 `metadata` 块中，遵循语义化版本。

## [1.1.12] — 2026-10-24

### Fixed

- **根下放多个技能目录的仓库不再被判成内容合集（1.1.11 引入的回归）**：1.1.11 的"本体侧占比 ≥ 50%"兜底按单个首层目录计算，多技能仓库里每个 `<n>/SKILL.md` 目录都只占全仓库一小部分，3–10 个技能目录（每个带 references/、scripts/）被判成 content-collection，技能强信号丢失（30 个时靠"SKILL.md 数量多"规则兜住，2 个时靠占比恰好够）。现在占比按**全部候选技能目录（非点、非噪声）合计** + 根下 references/、scripts/ + 根级散文件计算：根下 N 个技能目录合计接近 100%，恢复判技能包；30 页教程里只占约 3% 的单个模板、以及三个模板目录合计仍不足 50% 的情形，仍判 content-collection；根目录 `SKILL.md` 与 `skills/<n>/` 布局不受影响（`classify_repo.py`）
- 已知取舍：技能包旁边带体量很大的文档站（例如 3 个技能 + 40 页 `docs/`，技能侧合计不足 50%）会判 content-collection，并把 agent-skill-plugin 列为并列类型，按提示并列评估即可

### Tests

- 新增独立回归脚本 `regression_classify.py`（23 例：根下 2/3/5/10/30 个技能目录、`skills/<n>/`、单技能、极小技能仓库、开发辅助技能、教程仓库 + 8 种模板目录 + 3 个模板目录）；1.1.11 上 3 例失败（3/5/10 个技能目录），1.1.12 全部通过。相关用例已并入仓库：`tools/make_fixtures.py` 增至 29 类（新增根下 2/3/5/10/30 个技能目录、`skills/<name>/` 布局、3 模板目录合计 3 类 7 个夹具），`tests/test_probes.py` 增至 28 个测试，已验证新用例在 1.1.11 分类逻辑上恰好 3/5/10 三例失败

## [1.1.11] — 2026-10-24

### Fixed

- **黑名单外的模板目录不再把教程仓库抬成技能包**：噪声目录黑名单挡不住 `template/`、`templates/`、`assets/`、`spec/`、`resources/`、`reference/`、`snippets/`、`tutorial/` 这些目录名（`template/` 是 Anthropic 官方 skills 仓库用过的名字），首层 `<name>/SKILL.md` 强信号新增"本体侧占比 ≥ 50%"兜底：SKILL.md 所在首层目录 + 根下 `references/`、`scripts/` 卫星目录 + 根级散文件合计须占全仓库文件数一半以上才算技能强信号——单技能目录（含卫星与散文件）占比接近 100% 仍判技能包，30 页教程里只占约 3% 的格式模板不再命中强信号、不再压制"文档占比"内容信号，正确判 content-collection；根目录 `SKILL.md` 与 `skills/<name>/` 布局不受影响；极小仓库（n ≤ 5）的技能保底分同样适用占比兜底（`classify_repo.py`）

### Changed

- **项目更名为 github-project-analysis**（原名 github-project-review，即"GitHub 项目分析"）：SKILL.md `name` 与标题、README 标题与文件树、分发包文件名与 zip 顶层目录（`scripts/package.py` 的 `PREFIX`）、探针 User-Agent（`gh_probe.py` / `page_probe.py`）同步更名；本地克隆目录名与远程仓库名不变，克隆、推送与已安装技能的使用不受影响

### Tests

- 夹具增至 22 类（新增 8 个教程仓库夹具：guide/ 30 页正文 + 黑名单外目录各放一个 SKILL.md 模板）；测试 24 → 25 个

## [1.1.10] — 2026-10-23

### Fixed

- **噪声/构建目录里的 SKILL.md 不再判技能强信号**：`docs/SKILL.md`、`examples/SKILL.md`（教程仓库常放的格式讲解与模板）、`dist/SKILL.md`、`node_modules/**/SKILL.md` 等不再命中"根/skills 布局"强信号，也不再压制"文档占比"内容信号——此类教程仓库正确判 content-collection；极小仓库（n ≤ 5）的技能保底分同样不再被噪声目录命中；`.claude/` 点目录、根/skills/<name>/ 布局行为不变（`classify_repo.py`）

### Tests

- 夹具增至 14 类（新增 skill_doc_template：docs/ 下放 SKILL.md 模板的教程仓库）；测试 23 → 24 个

## [1.1.9] — 2026-10-23

### Fixed

- **识别"技能目录直接放仓库根下"的布局**：根下首层非点目录的 `<name>/SKILL.md`（如 `alpha/SKILL.md`）现在算技能强信号（与根目录、`skills/<name>/` 并列），并压制"文档占比/精选词"内容信号——此前此类仓库被判 content-collection（`classify_repo.py`）
- 极小仓库保底条件从"SKILL.md 是唯一文档"改为"存在非点目录下的 SKILL.md"：3 文件的 `README + <name>/SKILL.md + 脚本` 仓库恢复判技能包（1.1.8 引入的回归）；`.claude/` 等点目录的开发辅助技能仍不保底，团队手册用例行为不变（`classify_repo.py`）
- `pyproject.toml` 的 `{file = "..."}` 输出句式改为"引用了许可证文件 LICENSE"（消除"声明为 引用的许可证文件"的不通顺）；"声明为/引用了"前缀移入各分支（`local_probe.py`）
- `architecture-core.md` 两处具名数字轶事（5471 行配置类、`.env.example` 改 70 次）改为通用表述

### Tests

- 夹具增至 13 类：新增根下 3 技能目录、单技能目录 + references、3 文件极小技能仓库三种布局；测试 20 → 23 个

## [1.1.8] — 2026-10-23

### Fixed

- 极小仓库的技能保底分收紧：`n <= 5` 时还需 SKILL.md 是仓库**唯一文档**（`doc_n == skill_md`）才保底——"4 个文件的团队手册 + 1 个 `.claude/skills/` 开发辅助技能"不再被抬成 agent-skill-plugin；中文路径下的单技能小仓库（SKILL.md 即全部文档）行为不变（`classify_repo.py`）
- `pyproject.toml` 的 `license = {file = "LICENSE"}` 输出改为"引用的许可证文件 LICENSE"，不把文件名当许可证名；`{text = ...}` 形式解析独立（`local_probe.py`）
- 通用文档中的具名轶事改为不带数字的通用表述（示例仓库的快照数字只保留在带采集日期与免责的 examples 里）：SKILL.md"页面提交数可能与克隆差几个数量级"、rubric 两处"热门项目也可能藏着巨大的上帝类"、peer-comparison 同步

### Tests

- 夹具增至 10 类（新增 team_handbook）；测试 18 → 20 个（团队手册不被保底抬成技能包、file 形式 license 措辞）

## [1.1.7] — 2026-10-23

### Changed

- `arch_probe.py`：混合语言仓库此前只报 Python 函数体量、无任何提示——现在"最长的函数与类"一节明确标注函数级测量仅覆盖 Python，并列出最大的非 Python 源码文件作为替代线索
- `rubric.md` C 维度补充：函数/类级精确测量仅覆盖 Python，其他语言以最大文件行数 + 抽样人工估计替代，报告需写明测量方式
- `references/examples/summary.md` 补采集日期（2026-10-15/16，与两份子报告一致）与引用免责：具名项目的评分仅代表采集时点，用于校准语气与结构，不代表当前评价，正式引用需自行重新采集

## [1.1.6] — 2026-10-23

### Fixed

- **回归修复**：仓库里任何位置存在 SKILL.md 都会关闭"文档占比/精选词"内容信号——`.claude/skills/`、`.agents/skills/` 等仓库自带的开发辅助技能会把纯教程/文档仓库整体误判成 agent-skill-plugin。现在只有根目录或 `skills/<name>/` 布局的 SKILL.md 才压制内容信号；文件数 ≤5 的极小仓库里 SKILL.md 就是本体，技能信号保底 4 分（`classify_repo.py`）
- **回归修复（安全）**：`-r/--requirement` 递归展开未走读文件防护，`-r /etc/passwd`、`-r ../xxx` 或指向仓库外的符号链接会把仓库外文件的行数并进依赖数。现在拒绝绝对路径与 `..` 越界引用，并复用 `inside_repo`（拒绝符号链接、真实路径必须落在仓库内）（`local_probe.py`）
- 无依赖清单的仓库（纯技能包/纯文档）不再输出"锁文件 ✗ 未发现（依赖不可复现）"误导行（`local_probe.py`）
- `pyproject.toml` 的 PEP 621 表格写法（`license = {text = "..."}` / `{file = "..."}`）与 `License :: OSI Approved ::` classifiers 现在能被识别为许可证声明，不再误报"清单也无声明"（`local_probe.py`）
- `rubric.md` 结论映射边界修正：恰好 3.8 分回到 🟢（`[2.8, 3.8)` → 🟡、`≥ 3.8` → 🟢），与 examples 既有结论一致
- README 末尾误留的空代码块

### Tests

- 夹具增至 9 类：新增 `dev_skill_docs`（仅带 `.claude/skills/` 开发辅助技能的教程仓库 + 表格式 license 声明）；`env_files` 的 requirements.txt 加入 `../` 越界与绝对路径两条仓库外 `-r` 引用（指向夹具目录外的恶意外部文件）
- 测试 14 → 18 个：新增开发辅助技能不压制内容分类、`-r` 路径安全、无依赖不输出锁文件行、表格式 license 识别 4 项

## [1.1.5] — 2026-10-23

### Fixed

- 单技能仓库（根 `SKILL.md` 或 `skills/<name>/SKILL.md`）被"文档占比"误判为 content-collection：技能包布局现在给 4/6 分强信号，有 SKILL.md 时"文档占比/精选词"不再给内容合集加分（`classify_repo.py`）
- 根目录 `SKILL.md` 的 name 被拿去与克隆目录名比对导致误报；克隆目录名任意，该比对只对子目录技能生效（`content_probe.py`）
- 注入措辞正则漏词边界：`README`、`category`、`blueprint` 等普通词命中"读取敏感文件"（`content_probe.py`）
- LICENSE 检测：只认根目录（子目录 `third_party/lib/LICENSE` 不再冒充），文件名补齐 `COPYING` / `LICENCE` / `unlicense`；检不出时输出"需人工核实"并尝试读取 pyproject/package.json 的 license 声明，不再直接判无（`local_probe.py`）
- 依赖统计：`requirements.txt` 的 `-r/--requirement` 引用递归展开计入总数；`pyproject.toml`（PEP621/poetry）、`go.mod`、`Cargo.toml` 从"存在"改为实际计数（`local_probe.py`）
- 新增锁文件检测：package-lock.json / pnpm-lock.yaml / yarn.lock / poetry.lock / uv.lock / Cargo.lock / go.sum 等，缺失时按 rubric D 提示（`local_probe.py`）
- monorepo 标志文件（pnpm-workspace.yaml / lerna.json / turbo.json / nx.json / go.work）从只认根目录改为任意层级（`local_probe.py`）

### Changed

- 安全守则消除自相矛盾：`extra-checks.md` 第 1 节试跑规程补齐前置条件（一次性容器、无密钥、先审计安装钩子、`--ignore-scripts`），与 SKILL.md"不执行未审阅代码"统一为"条件全满足才试跑，否则静态审阅"
- `rubric.md` 结论映射改为优先级判定（一票否决/低分 > 单项≤1 封顶 🟡 > 总分），并说明 N/A 归一化的具体算法
- SKILL.md 命令块标注需先 `cd` 到 skill 目录（相对路径）

### Tests

- 夹具增至 8 类（新增 single_skill 单技能仓库）；env_files 夹具扩展依赖展开/锁文件/子目录 LICENSE
- 测试 14 个：新增单技能分类、注入词边界、LICENSE 根目录规则、依赖展开与锁文件 5 项；中文技能仓库的过时断言（固化了分错类行为）随修复修正

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

## [1.1.1] — 2026-10-19

### Fixed

- `SKILL.md` frontmatter 格式规范化
- Python 3.8 兼容性（去除 3.9+ 语法依赖）
- 类型手册的路由与相互引用修正
- 安全守则补齐（仓库文字当数据不当指令、不执行未审阅仓库代码）

## [1.1.0] — 2026-10-19

### Added

- 初始发布
- 七步工作流：确认目的 → 采集数据 → 类型识别 → 深度阅读 → 同类对比 → 九维评分 → 输出报告
- 8 种项目类型分析手册（`references/archetypes/`）
- 3 个领域专项清单（量化交易、AI Agent、安全双重用途）
- 6 个数据采集脚本（`scripts/`，纯标准库；打包工具 `package.py` 于 1.1.2 加入）
- 九维评分体系与类型权重调整表（`references/rubric.md`）
- 2 份完整示例报告（`references/examples/`）
- 安全守则：符号链接防护、git 危险配置屏蔽、只读克隆
