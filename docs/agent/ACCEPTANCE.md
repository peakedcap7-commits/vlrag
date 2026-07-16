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

## 2026-07-16 验收记录

- 主验收任务：`019f6a96-c116-7041-8d52-14b79acf3720`。
- architect 子线程：`019f6a99-6994-7292-8362-9ee284fdaff4`，活动路径 `/root/architect`。
- reviewer 子线程：`019f6a99-c85d-7333-8975-654c8727a085`，活动路径 `/root/reviewer`。
- App 在同一主任务内显示了两个独立子 Agent 活动节点，并返回了各自线程标识；两个子线程均已通过 App 专用导航独立打开，再成功返回主任务，三次结果均为 `navigated: true`。
- 两个子 Agent 均已完成、未继续派生、未修改文件。
- 项目根 `.codex/agents` 在任务启动时可发现，七个角色名称唯一；八个 TOML 文件均能解析。
- 十五项多 Agent 配置、策略和共享记忆测试全部通过。
- Codex CLI 使用 `--strict-config` 从项目根启动并返回 `config.load=ok`；校验任务线程为 `019f6aa7-93c3-7423-a808-87e8eb58dc99`。
- 首次只读验收结束时，`git status --short`、`git diff --stat` 和未跟踪文件检查均为零行输出。

## 验收问题处理

- architect 指出的真实依赖和对象组装边界已补充到 `ARCHITECTURE.md`；Chroma 具体类型耦合作为已知边界例外记录，本任务不改业务代码。
- reviewer 提出的“必须在 `.codex/config.toml` 逐个注册角色”不成立。Codex 官方规则是把项目级自定义 Agent 分别放在 `.codex/agents/*.toml`，而 `[agents]` 只保存 `max_threads`、`max_depth` 等全局调度设置。
- 官方依据：https://developers.openai.com/codex/subagents

## 验收结论

- 配置发现、并行调度、App 活动可见、禁止递归派生、只读约束和 Git 零污染均有实际证据。
- 多 Agent 开发基础设施验收通过。
