# ShoppingQnA 当前项目状态

- 最后更新时间：2026-07-23
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## 技术栈

- Python 3.11+
- DashScope / 百炼模型服务
- LangChain
- Chroma 本地向量库
- Chinese-CLIP 中文图文向量
- FastAPI / Uvicorn HTTP 服务
- LangGraph 规则意图路由与流程编排
- 图检索抽象接口（Neo4j 二期占位）
- pytest 测试代码

## 已有模块

- src/data/：数据加载和增强。
- src/embeddings/：文本和图文 Embedding。
- src/vectordb/：文本及图片向量库。
- src/retrievers/：文本、多模态和混合检索。
- src/graph/：包含图检索抽象、DummyGraphRetriever 空实现、Neo4j 二期占位，以及当前 Polyvore 推荐主链使用的 Neo4j outfit provider。
- src/llm/：百炼模型客户端。
- src/chatbot/：提示词、历史和问答链。
- src/api/：仅负责 FastAPI schema、HTTP 路由和应用生命周期，不包含检索或图关系算法。
- src/api/runtime.py：线程安全地懒加载并复用 Chinese-CLIP、Chroma、Neo4j 和推荐运行时，维护预热状态。
- src/assistant_graph.py：统一 assistant 意图路由与流程编排；M2-A/B/C/D 多图搭配分析与 M3-A+/B 改搭约束解析、候选召回已接入，其他未实现能力明确返回 `not_ready`。
- src/outfit_analyze_service.py：从 MinIO 只读获取 2～4 张输入图，执行逐图 Top-3 匹配、跨图 Neo4j 共现分析和可解释规则评分。
- src/outfit_advice_service.py：把 M2-C 内部评分事实交给文本 LLM，严格生成 verdict、summary、strengths、issues、suggestions 五个用户字段。
- src/outfit_revise_service.py：以确定性词典和规则标准化改搭约束，根据 conversation_state 商品元数据绑定具体商品，并在指代不明、匹配歧义或约束冲突时返回追问；不执行商品替换。
- src/outfit_revise_candidate_service.py：根据标准化约束构造中文查询，只读召回 Polyvore 文本候选，经 resolver 补齐展示字段并过滤排除/锁定商品；不做搭配验证。
- src/cli.py：旧 Kream 命令行入口和对象组装，不参与当前 M2/M3 产品主链。
- tools/：开发、建库和 smoke 命令入口；只依赖 src 生产模块，生产模块不得反向依赖 tools。

## 多 Agent 开发状态

- Codex App 可见性验收：已完成。
- 项目级配置位于 `.codex/config.toml` 和 `.codex/agents/*.toml`，共七个专业 Agent。
- Codex App 保存的父工作区为 `D:\pj\vlrag`；父目录 `.codex` 是指向本仓库 `.codex` 的 Junction，仅用于项目配置发现。
- App 验收中已同时出现 `/root/architect` 与 `/root/reviewer` 两个独立子 Agent 活动节点，且二者均未继续派生。
- Claude Code 对等层：项目级 `CLAUDE.md` 与 `.claude/agents/*.md`（七个角色）已建立，与 `.codex/agents/*.toml` 角色对等、规则一致；主会话即主 Agent，以 `AGENTS.md` 为唯一权威。
- claude-bridge 文件桥：位于 `C:\Users\Administrator\Documents\Codex\claude-bridge\`，由主 Agent 写入、Codex 会话只读，协议见该目录 `PROTOCOL.md`；只承载结构化摘要，不承载原始逐字会话。

## 当前限制

- 尚未形成正式前端目录。
- M2 多件搭配分析与 M3 对话式改搭已明确进入后续实施；M4 暂缓。
- `/assistant/message` 已冻结 M2/M3 最小请求与响应 schema；M2-A/B/C/D 已实现多图匹配、初版评分和用户建议，M3-A+/B 已实现词典标准化、状态绑定、追问与文本 Chroma 替换候选召回，但尚未执行最终替换或搭配验证。
- 用户图片只能写入 MinIO 临时前缀 `uploads/{session_id}/{image_id}.jpg`；开发期 TTL 为 24 小时，生产前补鉴权和清理任务。用户图不得进入商品 Chroma collection 或 Polyvore 商品库。
- M2-A/B 对用户图片仅执行内存中的临时 Chinese-CLIP 编码和 `products_image_cnclip_v1` 只读查询，不保存用户图向量。
- M2-C 只读查询不同输入图 Top-3 候选之间的 Neo4j outfit 共现，并按图关系40、品类20、颜色20、风格20生成0～100分和证据等级；不调用模型生成建议。
- M2-D 只调用文本 LLM 组织用户建议；正式 API 不暴露 graph_evidence、rule_scores、item_id 或 outfit_id 等内部技术字段。
- 模型运行时默认不自动预热；可调用 `POST /warmup` 手动预热，或设置 `ENABLE_MODEL_WARMUP=true` 在 FastAPI 生命周期自动预热。`GET /health/ready` 返回就绪状态、耗时和安全错误类型。
- 关系型数据库表结构尚未引入。
- Chroma 数据和处理后数据属于本地产物，不进入 Git。
- Polyvore 232 条图切片已写入 `products_image_cnclip_v1` 与 `products_text_v3_v1`，两个 collection 的字符串 `item_id` 集合完全一致。
- 无 VLM 的 232 条基础中文检索清单位于 `data/processed/polyvore_neo4j_items_retrieval.jsonl`，只使用类别与显式颜色等基础 metadata，不推断材质或功能属性。
- `tools/cli_polyvore_retrieval.py` 已提供 text-embedding-v3、Chinese-CLIP 文本搜图与本地 BM25 三路查询，并按 `item_id` 去重执行 RRF 融合；融合后使用增强 JSONL 中的颜色、类别、风格、细节和场景做轻量规则加权 smoke，明确不使用材质字段，也不接管现有 Chatbot 检索主链。
- `tools/cli_polyvore_recommend.py` 已将独立三路检索 Top1 与 Neo4j outfit provider 串联为“中文查询 → 锚点商品 → 搭配候选”smoke；只做顺序编排，不重新打分，也不接管现有 Chatbot 检索主链。
- `src/data/polyvore_item_resolver.py` 可只读合并 232 条 Neo4j Item 基础 manifest、100 条 sample manifest 与 5 条 enriched JSONL；enriched 字段优先，Neo4j manifest 为图候选兜底图片和 object_key。
- `src/polyvore_recommend_service.py` 是 CLI 与 FastAPI 共用的唯一 Polyvore 推荐运行时组装边界；`src/api/app.py` 暴露 `GET /health` 与 `POST /polyvore/recommend`，应用启动时只组装一次 service。
- 本机 Neo4j 已通过幂等导入写入 Polyvore 最小图切片：40 个 Outfit、232 个 Item、233 条 `IN_OUTFIT`；推荐 service 在 `OUTFIT_PROVIDER=neo4j` 时直接查询 Neo4j，不执行内存降级。
- Neo4j 图切片的 232 张 Item 图片均已存在于 MinIO `shopping-qna/polyvore/items/`，基础清单位于 `data/processed/polyvore_neo4j_items_manifest.jsonl`。
- 现有部分测试依赖 DashScope、LangChain、Chinese-CLIP 及有效 API Key，纯配置测试必须使用 Python 标准库独立运行。
- backend 与 frontend 配置中的 `karpathy-guidelines` 使用当前开发机绝对路径；迁移到其他机器时需要调整该路径。
- `PolyvoreRecommendConfig.valid_path`、`src/data/polyvore_import.py` 的 `DEFAULT_PARQUET_PATH` 等使用本机硬编码绝对路径（如 `D:\datasets\...`）；迁移到其他机器时需要调整。

## 命令入口

- 当前产品 HTTP 入口为 FastAPI 的 `/polyvore/recommend` 与 `/assistant/message`。
- 运行时接口为 `POST /warmup` 与 `GET /health/ready`；`GET /health` 继续仅表示进程存活。
- `python -m src.cli` 仅保留为旧 Kream 交互入口，不参与当前 Polyvore M2/M3 主链。
- 开发工具从项目根运行：`python -m tools.cli_cnclip_index`、`python -m tools.cli_polyvore_text_index`、`python -m tools.cli_polyvore_retrieval`、`python -m tools.cli_polyvore_recommend`、`python -m tools.cli_polyvore_neo4j_import`、`python -m tools.cli_polyvore_neo4j_chroma_index`。
- M3-C 已接入只读 Neo4j 共现验证：替换候选按“图共现证据、metadata 偏好、原文本召回顺序”排序，公开响应仅返回 `match_level` 与 `reason`，不暴露图数据库技术字段。
- M3-D 已接入 qwen-turbo 文本建议：LLM 只接收用户可读的保留单品描述、已解析约束和已排序候选，正式成功响应仅返回 `verdict`、`summary`、`changes`、`suggestions`；成功、修复与 fallback 路径都会清理商品 ID 和技术标识。
- 关键 API 链路已使用结构化 INFO 日志记录 `total_ms`、预热、MinIO、Embedding、Chroma、Neo4j 与文本 LLM 耗时；日志不改变正式响应契约，也不记录密钥或业务正文。
- M2/M3 advice 的 qwen-turbo 显式使用 12 秒超时和一次传输重试；首次 JSON/schema 失败最多执行一次格式修复，最终失败返回仅基于既有事实的安全 fallback，并记录完整诊断字段。
- 本机开发环境通过 `CHINESE_CLIP_MODEL` 指向已缓存模型目录，避免预热时回退到 HuggingFace 远程解析；`.env.example` 仅提供路径占位示例。
