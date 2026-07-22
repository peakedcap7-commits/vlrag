# ShoppingQnA 当前项目状态

- 最后更新时间：2026-07-22
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
- 图检索抽象接口（Neo4j 二期占位）
- pytest 测试代码

## 已有模块

- src/data/：数据加载和增强。
- src/embeddings/：文本和图文 Embedding。
- src/vectordb/：文本及图片向量库。
- src/retrievers/：文本、多模态和混合检索。
- src/graph/：包含图检索抽象、DummyGraphRetriever 空实现、Neo4j 二期占位，以及独立的 Polyvore outfit JSON 内存共现索引 smoke；Neo4j 尚未接入。
- src/llm/：百炼模型客户端。
- src/chatbot/：提示词、历史和问答链。
- src/api/：仅负责 FastAPI schema、HTTP 路由和应用生命周期，不包含检索或图关系算法。
- src/cli.py：命令行入口和对象组装。
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
- 关系型数据库表结构尚未引入。
- Chroma 数据和处理后数据属于本地产物，不进入 Git。
- Polyvore 五条小样本已同时写入 `products_image_cnclip_v1` 和 `products_text_v3_v1`，两者使用相同字符串 `item_id`。
- `tools/cli_polyvore_retrieval.py` 已提供 text-embedding-v3、Chinese-CLIP 文本搜图与本地 BM25 三路查询，并按 `item_id` 去重执行 RRF 融合；融合后使用增强 JSONL 中的颜色、类别、风格、细节和场景做轻量规则加权 smoke，明确不使用材质字段，也不接管现有 Chatbot 检索主链。
- `tools/cli_polyvore_outfit.py` 可只读解析 Polyvore `valid.json`，通过进程内双向索引查询同 outfit 共现候选；不写缓存、不接 Neo4j，也不接管现有 Chatbot 检索主链。
- `tools/cli_polyvore_recommend.py` 已将独立三路检索 Top1 与 outfit 共现索引串联为“中文查询 → 锚点商品 → 搭配候选”smoke；只做顺序编排，不重新打分，也不接管现有 Chatbot 检索主链。
- `src/data/polyvore_item_resolver.py` 可只读合并 100 条 sample manifest 与 5 条 enriched JSONL，为推荐 anchor 和候选附加稳定的 `resolved` metadata；无法解析的商品保留原关系结果并明确返回 `found=false`，不会补图或调用外部服务。
- `src/polyvore_recommend_service.py` 是 CLI 与 FastAPI 共用的唯一 Polyvore 推荐运行时组装边界；`src/api/app.py` 暴露 `GET /health` 与 `POST /polyvore/recommend`，应用启动时只组装一次 service。
- 现有部分测试依赖 DashScope、LangChain、Chinese-CLIP 及有效 API Key，纯配置测试必须使用 Python 标准库独立运行。
- backend 与 frontend 配置中的 `karpathy-guidelines` 使用当前开发机绝对路径；迁移到其他机器时需要调整该路径。
- `PolyvoreRecommendConfig.valid_path`、`src/data/polyvore_import.py` 的 `DEFAULT_PARQUET_PATH` 等使用本机硬编码绝对路径（如 `D:\datasets\...`）；迁移到其他机器时需要调整。

## 命令入口

- 正式交互入口保留为 `python -m src.cli`。
- 开发工具从项目根运行：`python -m tools.cli_cnclip_index`、`python -m tools.cli_polyvore_text_index`、`python -m tools.cli_polyvore_retrieval`、`python -m tools.cli_polyvore_outfit`、`python -m tools.cli_polyvore_recommend`。
