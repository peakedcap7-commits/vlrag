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

## 当前限制

- 尚未形成正式前端目录。
- 关系型数据库表结构尚未引入。
- Chroma 数据和处理后数据属于本地产物，不进入 Git。
- 现有部分测试依赖 DashScope、LangChain、OpenCLIP 及有效 API Key，纯配置测试必须使用 Python 标准库独立运行。
- 多 Agent 配置建立后仍需要在 Codex App 中进行一次真实子 Agent 可见性验收。
