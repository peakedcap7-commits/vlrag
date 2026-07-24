# ShoppingQnA 技术决策

- 最后更新时间：2026-07-23
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## DEC-001：采用混合多 Agent 编排

- 状态：已批准
- 决策：主 Agent 常驻，专业 Agent 按阶段启动。
- 原因：满足可观察协作，同时控制并发、冲突和 Token 消耗。

## DEC-002：使用 Git 和 Markdown 作为共享记忆

- 状态：已批准
- 决策：不引入 Redis、向量记忆库或独立 Agent 平台。
- 原因：当前规模下 Markdown 可审查、可回滚且足够可靠。

## DEC-003：采用分级审批

- 状态：已批准
- 决策：普通局部实现自动推进；架构、数据库和高风险操作按级别请求用户批准。
- 原因：兼顾开发效率和变更安全。

## DEC-004：并行写任务使用临时 Worktree

- 状态：已批准
- 决策：主 Agent 保留稳定集成 Workspace；前端、后端及并行迁移使用临时 Worktree。
- 原因：隔离写操作并保留清晰的提交和审查边界。

## DEC-005：当前产品主链隔离旧 Kream CLI

- 状态：已批准
- 决策：当前产品主链以 FastAPI、LangGraph 和 Polyvore service 为准；`src.cli` 仅作为旧 Kream 交互入口保留，不参与 M2/M3。
- 原因：避免旧 `products_text` 使用路径与当前 Polyvore 双向量库职责混淆，同时不在本轮删除历史能力或数据。

## DEC-006：M2/M3 实施，M4 暂缓

- 状态：已批准
- 决策：后续实施 M2 多件搭配分析和 M3 对话式改搭；M4 场景整套生成暂缓。LangGraph 继续作为规则意图路由与流程编排层。
- 原因：先闭合已有数据与图关系可支撑的能力，避免提前扩大到场景生成和复杂记忆。

## DEC-007：用户上传图片采用临时隔离存储

- 状态：已批准
- 决策：对象键统一为 `uploads/{session_id}/{image_id}.jpg`，由服务端生成并校验会话归属；开发期 TTL 为 24 小时，生产前必须补齐鉴权与清理任务。
- 原因：用户图片只允许临时保存和临时向量化，不得写入商品 Chroma collection，也不得进入 Polyvore 商品库。

## DEC-008：冻结 Assistant 的 M2/M3 最小契约

- 状态：已批准
- 决策：请求固定支持 `message`、最多四个且不重复的 `image_keys`、结构化 `conversation_state`、`top_k` 和 `retrieval_limit`；conversation_state 可携带当前 item metadata。M3-A+/B 的改搭结果包含标准化约束、绑定商品 ID、追问信息、置信度和 replacement_candidates。
- 原因：先稳定 API 边界；M3-A+ 负责解析与消歧，M3-B 只读召回并过滤候选。歧义或冲突必须跳过召回，候选不得伪装为已完成最终替换。
