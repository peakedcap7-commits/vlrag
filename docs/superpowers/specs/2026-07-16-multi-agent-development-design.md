# ShoppingQnA 多 Agent 开发体系设计

- 状态：已批准
- 日期：2026-07-16
- 适用目录：`D:\pj\vlrag\shopping-qna`
- 设计目标：建立由用户统一指挥、主 Agent 统一调度、专业 Agent 按需执行的可观察开发体系

## 1. 背景

ShoppingQnA 当前是 Python 3.11+ 多模态 RAG 项目，已有数据处理、Embedding、向量库、混合检索、Neo4j、对话链和测试模块。项目尚未形成正式前端目录，也尚未建立稳定的多 Agent 协作规则。

本设计解决以下问题：

- 用户只和一个主 Agent 沟通，由主 Agent 汇报全局状态；
- 功能增加时防止目录、依赖和模块边界持续腐化；
- 前后端 Agent 在最小范围内实现需求；
- 数据库设计实用优先，并保护现有结构；
- 测试、代码审查和用户验收相互独立；
- 用户能够在 Codex 中查看专业 Agent 的活动线程；
- 不依赖完整对话共享，通过 Git 和项目文档保存跨 Agent、跨会话的权威记忆。

## 2. 设计原则

1. 八个名称代表角色池，不代表八个常驻进程。
2. 主 Agent 常驻，其他专业 Agent 按任务阶段启动。
3. 同时运行的 Agent 数量受控，禁止递归派生子 Agent。
4. 只读任务优先并行，写密集任务谨慎并行。
5. 并行写代码的 Agent 使用独立 Git Worktree。
6. 普通局部修改自动推进，高风险变更实行分级审批。
7. 共享记忆保存最终事实和已批准决策，不保存冗长推理过程。
8. 前端和后端开发强制应用 `karpathy-guidelines`：先说明假设，采用最小实现，进行手术式修改，并提供验证证据。

## 3. 采用方案

采用混合编排方案：

```text
阶段一：设计
主 Agent + 架构 Agent + 数据库 Agent

阶段二：实现
主 Agent + 后端 Agent + 前端 Agent

阶段三：质量
主 Agent + 测试 Agent + 审查 Agent

阶段四：验收
主 Agent + 验收 Agent
```

架构、数据库、测试、审查和验收任务通常作为同一主任务内的子 Agent 运行。前端、后端以及并行数据库迁移等写密集任务，在需要时使用独立任务和 Git Worktree。

## 4. 角色与权限

| 角色 | 职责 | 默认权限 | 启动条件 |
|---|---|---|---|
| 主 Agent | 接收用户指令、拆分任务、调度角色、维护状态、合并结果、向用户汇报 | 主 Workspace 写权限 | 始终常驻 |
| 架构 Agent | 检查模块边界、依赖方向和目录结构，防止架构腐化 | 默认只读；批准后可调整结构 | 新模块、跨模块接口或核心依赖变化 |
| 后端 Agent | 实现接口、业务逻辑、检索流程和外部服务集成 | 指定 Worktree 写权限 | 后端任务及验收标准明确后 |
| 前端 Agent | 实现页面、组件、状态、接口调用和交互 | 指定 Worktree 写权限 | 前端任务和接口契约明确后 |
| 数据库 Agent | 设计表、索引、约束和迁移，保护数据完整性 | 默认只读；批准后可写迁移 | 结构、索引、关系或迁移变化 |
| 测试 Agent | 编写和运行单元、集成及回归测试 | 测试范围写权限 | 实现前定义测试或实现后验证 |
| 审查 Agent | 检查正确性、回归、安全、架构违规和过度实现 | 只读 | 测试通过后、合并前 |
| 验收 Agent | 按原始需求和验收标准执行端到端检查 | 只读 | 审查问题处理完毕后 |

专业 Agent 不拥有扩大需求、改变验收标准或指挥其他专业 Agent 的权限。跨角色信息默认由主 Agent 中转。

## 5. 分级审批

### 5.1 自动推进

- 已明确范围内的普通前后端局部实现；
- 测试、静态分析和只读审查；
- 不改变公共契约的缺陷修复。

### 5.2 架构审批

以下变更必须由架构 Agent 评审，再由用户批准：

- 新增顶级目录；
- 改变模块依赖方向；
- 修改跨模块公共接口；
- 引入核心依赖或替换基础框架。

### 5.3 数据库审批

以下变更必须由数据库 Agent 评审，再由用户批准：

- 建表、删表；
- 修改字段类型、主键、外键或唯一约束；
- 可能影响已有数据的迁移；
- 生产索引和数据关系调整。

### 5.4 强制单独审批

- 删除数据；
- 生产环境部署；
- 密钥、权限和网络策略变更；
- 不可逆操作。

## 6. Workspace 与 Worktree

主 Agent 使用项目主目录作为稳定集成 Workspace：

```text
D:\pj\vlrag\shopping-qna
```

临时 Worktree 建议放在同级独立目录：

```text
D:\pj\vlrag\shopping-qna-worktrees\
├── backend-<task-id>\
├── frontend-<task-id>\
└── database-<task-id>\
```

使用规则：

- 后端和前端并行写代码时分别使用独立 Worktree；
- 数据库 Agent 并行编写迁移时使用独立 Worktree；
- 架构 Agent 只有在获批并实际调整目录时才使用临时 Worktree；
- 测试、审查和验收默认在集成后的目标分支运行；
- 串行小修改不创建 Worktree；
- 合并完成并验证后删除临时 Worktree；
- 同一文件同一时间只能有一个写入所有者。

自定义 Agent 配置定义“如何工作”，Worktree 定义“在哪里工作”，两者相互独立。

## 7. 通信与可见性

唯一指挥链路：

```text
用户 ⇄ 主 Agent ⇄ 专业 Agent
```

专业 Agent 结束任务时统一返回：

```markdown
## Agent 汇报

- Agent：
- 当前阶段：
- 任务目标：
- 检查或修改的文件：
- 主要结论：
- 验证命令及结果：
- 风险和遗留问题：
- 请求的决策：
- 是否阻塞：
- 建议主 Agent 下一步：
```

用户可以通过 Codex 的 Subagents 活动面板查看同一任务内的专业 Agent 线程。独立 Worktree 开发任务在各自任务线程中查看。主 Agent 负责把专业 Agent 结果收敛为进度、决策、风险和下一步，不把大量中间日志复制到主线程。

主 Agent 在以下节点主动汇报：

- 任务拆分完成；
- 需要用户审批；
- Agent 遇到阻塞；
- 测试或审查失败；
- 一个开发阶段完成；
- 最终验收完成。

## 8. 共享记忆

项目级共享记忆结构：

```text
shopping-qna/
├── AGENTS.md
└── docs/agent/
    ├── PROJECT_STATE.md
    ├── ARCHITECTURE.md
    ├── DATABASE.md
    ├── DECISIONS.md
    ├── TASK_BOARD.md
    └── ACCEPTANCE.md
```

| 文件 | 权威内容 | 维护方式 |
|---|---|---|
| `AGENTS.md` | 角色、权限、审批、开发和完成规则 | 主 Agent 维护 |
| `PROJECT_STATE.md` | 当前技术栈、能力和已知限制 | 主 Agent 维护 |
| `ARCHITECTURE.md` | 模块职责、目录边界和依赖方向 | 架构 Agent 建议，主 Agent 合并 |
| `DATABASE.md` | 当前数据结构、约束、索引和迁移规则 | 数据库 Agent 建议，主 Agent 合并 |
| `DECISIONS.md` | 已批准的重要技术决策 | 主 Agent 追加或标记取代 |
| `TASK_BOARD.md` | 当前任务、状态、分支和文件所有权 | 主 Agent 在阶段变化时更新 |
| `ACCEPTANCE.md` | 当前功能可验证的验收标准 | 主 Agent 维护，验收 Agent 只读 |

每个专业 Agent 只获得当前任务所需的最小上下文。专业 Agent 的建议经过代码、测试或用户决定确认后，才由主 Agent 写入权威文档。

文档必须标明最后更新时间、对应提交、维护者和状态。文档与代码冲突时，Agent 必须暂停并报告，不得自行选择某一方作为事实。

## 9. Codex 配置

项目级配置结构：

```text
.codex/
├── config.toml
└── agents/
    ├── architect.toml
    ├── backend.toml
    ├── frontend.toml
    ├── database.toml
    ├── tester.toml
    ├── reviewer.toml
    └── acceptance.toml
```

`.codex/config.toml` 采用：

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

主 Agent 由根任务和 `AGENTS.md` 定义，不作为可被派生的自定义 Agent。七个专业 Agent 使用项目级 `.codex/agents/*.toml`。

每个自定义 Agent 文件至少包含：

- `name`；
- `description`；
- `developer_instructions`；
- 与职责相匹配的 `sandbox_mode`；
- 必要时启用的 Skill。

前端和后端 Agent 必须启用：

```toml
[[skills.config]]
path = "C:/Users/Administrator/.agents/skills/karpathy-guidelines/SKILL.md"
enabled = true
```

并在 `developer_instructions` 中明确要求开发前读取并遵守该 Skill。

只读 Agent 使用 `sandbox_mode = "read-only"`。写入 Agent 使用 `workspace-write`，但仍受任务文件范围和分级审批约束。

## 10. 功能开发流水线

```text
接收需求
→ 明确范围、假设和验收标准
→ 判断所需角色和审批级别
→ 架构/数据库条件评审
→ 冻结接口契约和文件所有权
→ 前后端最小实现
→ 依次集成分支
→ 测试门禁
→ 审查门禁
→ 验收门禁
→ 更新共享记忆
→ 最终汇报
```

不是每个任务都运行所有角色：

| 任务类型 | 最小角色组合 |
|---|---|
| 单文件缺陷 | 开发 Agent + 测试 Agent |
| 普通后端功能 | 后端 + 测试 + 审查 |
| 普通前端功能 | 前端 + 测试 + 审查 |
| 前后端联动 | 架构 + 前端 + 后端 + 测试 + 审查 |
| 数据结构变化 | 数据库 + 对应开发 + 测试 + 审查 |
| 面向用户的重要能力 | 在相应组合后增加验收 Agent |

## 11. 质量门禁

### 11.1 测试

测试 Agent 检查正常路径、关键异常路径、回归行为、接口联调和迁移兼容性。测试失败时只提交证据，由主 Agent 退回原开发 Agent 进行最小修复。

### 11.2 审查

审查问题分为：

- P0：数据丢失、安全事故或系统不可用；
- P1：明确功能错误、接口破坏或迁移风险；
- P2：重要可维护性问题或测试缺失；
- P3：非阻塞建议。

P0、P1 禁止合并；P2 原则上修复，不修复必须记录原因；P3 不得用于扩大当前需求。

### 11.3 验收

验收 Agent 只依据用户原始目标、已批准变更、`ACCEPTANCE.md` 和实际运行结果。验收失败时不能降低验收标准来适配当前实现。

## 12. 失败与回退

- 同一 Agent 连续两次未解决同一问题时，主 Agent 暂停试错，汇总证据并启动审查或架构 Agent；
- 新功能必须破坏现有架构边界时，停止实现并请求架构审批；
- 数据库迁移必须包含执行前检查、向前迁移、回滚步骤和数据验证；
- 合并冲突由主 Agent 在集成 Workspace 处理，不让开发 Agent 互相覆盖文件；
- 验收失败时，主 Agent 判断是实现缺陷还是需求歧义，分别退回开发 Agent 或请求用户决定；
- 新会话丢失上下文时，从 `AGENTS.md`、`PROJECT_STATE.md`、`TASK_BOARD.md` 和相关领域文档恢复。

## 13. 完成定义

主 Agent 只有在以下条件全部满足时才能宣布任务完成：

- 实现没有超出已批准范围；
- 相关测试通过并有可复现证据；
- P0、P1 审查问题为零；
- 需要验收的功能已经验收通过；
- 数据库和架构变化已经批准并记录；
- 共享记忆已经收敛到当前事实；
- Git 工作区、分支和 Worktree 状态明确；
- 遗留风险和回滚方式已经向用户披露。

## 14. 非目标

当前阶段明确不实现：

- 八个 Agent 长期同时运行；
- 专业 Agent 自由群聊；
- 子 Agent 继续派生孙 Agent；
- Redis、向量数据库或独立记忆服务；
- 为每个只读角色永久保留 Workspace；
- 自动执行生产部署、数据删除或密钥变更；
- 为未来不确定需求预建复杂插件、消息队列或 Agent 平台。

## 15. 验证标准

多 Agent 体系建立完成后，必须验证：

1. Codex 能加载七个项目级自定义 Agent；
2. 主任务可以按名称启动专业 Agent；
3. 子 Agent 线程可在客户端中查看；
4. `max_depth = 1` 能阻止专业 Agent 递归派生；
5. 只读 Agent 无法修改项目文件；
6. 前端和后端 Agent 能加载 `karpathy-guidelines`；
7. 主 Agent 能按任务类型选择最小角色组合；
8. 高风险任务会在实施前请求用户审批；
9. 并行写任务能在独立 Worktree 中完成并被主 Agent 集成；
10. 一个示例功能能够通过测试、审查和验收完整闭环。

## 16. 参考资料

- [Codex Subagents 官方文档](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex Git Worktrees 官方文档](https://learn.chatgpt.com/docs/environments/git-worktrees)
- [Codex AGENTS.md 官方文档](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
