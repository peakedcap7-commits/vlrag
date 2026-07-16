# ShoppingQnA 当前项目状态

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## 技术栈

- Python 3.11+
- DashScope / 百炼模型服务
- LangChain
- Chroma 本地向量库
- OpenCLIP 图文向量
- 图检索抽象接口（Neo4j 二期占位）
- pytest 测试代码

## 已有模块

- src/data/：数据加载和增强。
- src/embeddings/：文本和图文 Embedding。
- src/vectordb/：文本及图片向量库。
- src/retrievers/：文本、多模态和混合检索。
- src/graph/：仅有图检索抽象、DummyGraphRetriever 空实现和 Neo4j 二期占位；Neo4j 尚未接入。
- src/llm/：百炼模型客户端。
- src/chatbot/：提示词、历史和问答链。
- src/cli.py：命令行入口和对象组装。

## 多 Agent 开发状态

- Codex App 可见性验收：已完成。
- 项目级配置位于 `.codex/config.toml` 和 `.codex/agents/*.toml`，共七个专业 Agent。
- Codex App 保存的父工作区为 `D:\pj\vlrag`；父目录 `.codex` 是指向本仓库 `.codex` 的 Junction，仅用于项目配置发现。
- App 验收中已同时出现 `/root/architect` 与 `/root/reviewer` 两个独立子 Agent 活动节点，且二者均未继续派生。

## 当前限制

- 尚未形成正式前端目录。
- 关系型数据库表结构尚未引入。
- Chroma 数据和处理后数据属于本地产物，不进入 Git。
- 现有部分测试依赖 DashScope、LangChain、OpenCLIP 及有效 API Key，纯配置测试必须使用 Python 标准库独立运行。
- backend 与 frontend 配置中的 `karpathy-guidelines` 使用当前开发机绝对路径；迁移到其他机器时需要调整该路径。
