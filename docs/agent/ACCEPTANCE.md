# ShoppingQnA 多 Agent 体系验收标准

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## 配置验收

- .codex/config.toml 能被当前 Codex 严格解析。
- 七个项目级专业 Agent 配置完整且名称唯一。
- max_threads 为 4，max_depth 为 1。
- reviewer 和 acceptance 为只读。
- backend 和 frontend 启用 karpathy-guidelines。

## 调度验收

- 主 Agent 能按名称启动专业 Agent。
- 子 Agent 活动可以在 Codex 客户端查看。
- 专业 Agent 返回统一结构化报告。
- 专业 Agent 不继续派生其他 Agent。

## 安全验收

- 架构和数据库高风险变更会在实施前请求用户批准。
- 同一文件不会同时分配给多个写入 Agent。
- 并行前后端任务使用独立 Worktree。
- 测试、审查和验收不能自行降低标准。

## 完整闭环验收

选择一个不修改业务代码的只读检查任务：

1. 主 Agent 同时启动 architect 和 reviewer；
2. 两个 Agent 分别返回架构边界和代码风险报告；
3. 用户能打开两个子 Agent 线程；
4. 主 Agent 汇总结果且 Git 工作区没有新增业务修改。
