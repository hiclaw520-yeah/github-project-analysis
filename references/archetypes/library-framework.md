# 类型：library-framework（被他人依赖的库 / SDK / 框架）

## 识别
可发布包（package.json 有 main/exports 且非 private、pyproject 有 build-system、Cargo [lib]、go 模块），README 以"安装 + API 用法"为主，无运行入口。

## 什么算好
- **API 面小而稳定**：公开接口有文档，内部实现不泄漏；破坏性变更有迁移指南与语义化版本
- 类型标注/类型声明齐全（TS 的 d.ts、Python 的 type hints + py.typed）
- 测试覆盖公开 API 与边界情形；多版本/多平台矩阵测试
- 依赖少且合理；对运行时环境的要求清楚
- 发布纪律：tag/release/CHANGELOG 对应；包管理器上的包与仓库一致

## 必读文件
1. 公开入口（`index`/`__init__`/`lib`）  2. 一个核心模块  3. 测试（看是否测公开行为）
4. `package.json`/`pyproject`（exports、依赖、engines）  5. CHANGELOG 与 CI 发布流程

## 类型特有检查
- **版本纪律**：`git tag` 序列、CHANGELOG 是否标注 breaking；长期停留在 0.x 要说明
- **API 表面积**：导出了多少符号？有无明确的 public/internal 划分？
- **依赖健康**：依赖数、是否固定上限、有无已弃坑的依赖；被谁依赖（dependents）
- **兼容性矩阵**：支持的语言版本/运行时是否在 CI 里被测

## 类型特有红旗
- 无版本标签却承诺稳定；频繁在小版本里破坏 API
- 把内部模块路径当公开 API 暴露；类型缺失
- 测试只测内部实现而不测公开行为

## 维度解释
D +3、E +2（API 文档）、B +2；A 看下载量/被依赖方比看 star 更重要。

## 同类对手怎么选
同一功能的 2–4 个库（含事实标准）；比较 API 设计、体积、依赖数、维护节奏、类型支持。

## 报告章节
架构图可简化为"模块与公开 API 图"；核心链路改为"一次典型调用的路径"。
