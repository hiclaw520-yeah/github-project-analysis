# scripts/ — 数据采集与分析脚本

所有脚本只依赖 Python 标准库，无需 `pip install`。任何单项失败不中断，缺失项标注"获取失败/未取到"。

## 脚本一览

| 脚本 | 输入 | 输出 | 职责 |
| --- | --- | --- | --- |
| `page_probe.py` | GitHub 仓库 URL | Markdown / JSON | 解析仓库主页内嵌 JSON，不耗 API 额度，采集 star/fork/协议/简介等 |
| `gh_probe.py` | GitHub 仓库 URL 或 `owner/repo` | Markdown / JSON | 调 GitHub API 采集详细元数据，未认证限 60 次/小时 |
| `local_probe.py` | 本地仓库路径 | Markdown | 提交历史、代码规模、测试比例、技术债、工程化信号、安全红旗 |
| `classify_repo.py` | 本地仓库路径 | Markdown / JSON | 项目类型识别、规模档位、领域线索、建议启用哪些分析脚本 |
| `arch_probe.py` | 本地仓库路径 | Markdown | 目录规模图、入口点、技术栈、模块依赖图、运行形态线索、变更热点 |
| `content_probe.py` | 本地仓库路径 | Markdown | SKILL.md 完整性、清单校验、链接有效性、风险扫描（不执行仓库脚本） |
| `package.py` | 无（读 HEAD） | `dist/*.zip` | 一键打包分发，产物不含 `.git/`，开发期文件 `export-ignore` |

## 执行顺序

```
page_probe.py（在线、不耗额度）
  → git clone --depth 300（只读克隆）
    → local_probe.py（本地体检）
    → classify_repo.py（类型识别 → 决定后续脚本）
      → arch_probe.py（代码型）/ content_probe.py（内容/技能包型）
    → gh_probe.py（可选、API 补充）
```

数据冲突时优先级：克隆 > 页面 > API。

## 安全约束

- 所有 git 调用禁用 `core.fsmonitor` / `core.sshCommand` / `hooksPath`
- 读文件时拒绝符号链接，要求真实路径在仓库内
- 浅克隆历史补全只对 `https://` origin 执行
- 不执行仓库内的任何脚本