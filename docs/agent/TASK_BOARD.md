# ShoppingQnA Agent 任务看板

- 最后更新时间：2026-07-23
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## 当前任务

- 任务：M3-B 改搭替换候选召回与 metadata 过滤。
- 当前阶段：已完成文本 Chroma 召回、resolver 补齐、约束过滤和契约测试。

## Agent 状态

| Agent | 状态 | 当前任务 | 分支或 Worktree | 是否阻塞 |
|---|---|---|---|---|
| 主 Agent | 已完成 | 完成 M3-B 候选召回与过滤 | main / D:\pj\vlrag\shopping-qna | 否 |

## 文件所有权

当前没有专业 Agent 持有文件写入权。

## 收尾状态

- 当前稳定工作区：main / D:\pj\vlrag\shopping-qna。
- 当前无临时 Worktree，无专业 Agent 持有文件写入权。
- 父工作区 `.codex` Junction 已建立，指向本仓库的项目级配置。
- Codex App 子 Agent 可见性验收已完成，详细记录见 `ACCEPTANCE.md`。
- architect 已批准新增 `tools/` 开发工具边界；五个内部 CLI 已机械迁移，`src/cli.py` 正式交互入口保持不变。
- CLI 工具目录整理已提交并推送到远端 main，提交为 `78c5e43 refactor: move polyvore cli tools out of src`。
- “节省 token 模式”已固化到 `docs/agent/TASK_POLICY.md`，并由 `AGENTS.md` 引用。
- Polyvore JSON memory graph、对应 CLI 和测试已删除；推荐图关系主链保留 Neo4j provider。
- Neo4j 切片232个 Item 图片已补齐 MinIO，专用 manifest 已生成并接入 resolver。
- Chinese-CLIP 图片与 text-embedding-v3 文本 collection 均已幂等扩容至 232 条，ID 集合完全一致。
- LangGraph Assistant 已冻结 M2/M3 最小 schema；M2 已完成分析与建议，M3-A+/B 已完成约束解析与替换候选召回，最终替换和搭配验证尚未实现，M4 暂缓。
- 用户上传图片边界已冻结为临时 MinIO 前缀、24 小时开发期 TTL，且禁止进入商品向量库。
- `src.cli` 已标记为旧 Kream 隔离入口，不参与当前 FastAPI/LangGraph/Polyvore 主链。
- M2-A/B 已将 `outfit_analyze` 从占位切换为真实多图图片匹配；每图返回三个 Polyvore 商品，不写用户向量或商品数据。
- M2-C 已在不同输入图候选之间执行 Neo4j 共现查询，并返回 score、evidence_level、graph_evidence、rule_scores 和 warnings。
- M2-D 已将上述技术结果保留在内部，正式 outfit_analyze 仅返回 verdict、summary、strengths、issues、suggestions。
- FastAPI 已支持默认懒加载、`POST /warmup` 幂等手动预热、`ENABLE_MODEL_WARMUP=true` 自动预热和 `GET /health/ready` 状态查询。
- M3-A 已将 `outfit_revise` 从占位切换为确定性规则解析；缺少 conversation_state 时返回明确提示，不查询或写入任何业务存储。
- M3-A+ 已增加类目/颜色/风格标准化、基于 item metadata 的商品绑定，以及指代不明、多匹配、无匹配和保留/排除冲突追问。
- M3-B 已增加 `products_text_v3_v1` 只读召回、resolver 展示字段补齐及排除类目/商品/锁定商品过滤；追问状态不触发召回。

## 更新规则

- 只在任务开始、阶段切换、阻塞和结束时更新。
- 实时执行日志保留在 Codex 线程，不写入本文件。
- 任务结束后清理临时文件所有权和 Worktree 记录。
- M3-C 已完成：替换候选基于保留单品执行 Neo4j 只读共现验证，按 strong/medium/weak 用户态证据分级并稳定排序；追问状态不召回、不查图。
- M3-D 已完成：qwen-turbo 仅把确定性改搭结果转换为四字段用户建议；真实模型 smoke 由 `RUN_DASHSCOPE_SMOKE=1` 显式开启。
- 收口 smoke 已执行：warmup/ready、单品推荐、M2 成功；M3 的 Chroma/Neo4j 阶段成功，但 qwen-turbo 连续出现外部 SSL EOF，保留为环境阻塞证据。
- M2/M3 advice 稳定性治理已完成：显式 timeout/retry、一次 JSON 格式修复、最终失败 fallback 与无敏感正文的诊断日志均已覆盖 mock 测试。
- M3 advice 用户化表达已加固：保留商品以 metadata 描述替代内部 ID，成功、修复和 fallback 路径均不公开技术标识；本机 Chinese-CLIP 已固定到缓存目录。
