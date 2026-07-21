# ShoppingQnA 架构边界

- 最后更新时间：2026-07-20
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent，architect 负责评审
- 状态：已生效

## 当前依赖方向

```text
cli
├── data
├── vectordb ──→ embeddings ──→ DashScope / Chinese-CLIP
├── polyvore_recommend_service
└── chatbot
    ├── llm ──→ DashScope
    ├── vectordb ──→ Chroma
    ├── Chroma
    └── retrievers
        ├── llm
        ├── embeddings
        └── Chroma
```

独立 FastAPI 推荐入口：

```text
api ──→ polyvore_recommend_service ←── cli_polyvore_recommend
              ├── polyvore_retrieval
              ├── polyvore_recommend
              ├── graph
              ├── data
              ├── embeddings
              └── Chroma
```

当前代码中的直接依赖包括：

- `chatbot → llm`：`ShoppingChatbot` 创建生成模型客户端。
- `chatbot → vectordb`：切换到图像或混合模式时延迟加载图片向量库。
- `chatbot → Chroma`：`ShoppingChatbot` 的构造参数和成员直接使用 Chroma 具体类型。
- `retrievers → llm`：文本检索器用视觉模型把图片描述成文本。
- `retrievers → embeddings`：多模态检索器直接使用 Chinese-CLIP 编码中文文本或图片查询。
- `vectordb → embeddings`：向量库存取模块负责选择对应的嵌入实现。

数据准备链路：

```text
run_pipeline
      ↓
data
      ↓
llm
```

图检索预留：

- graph 的抽象接口不在当前检索主链；`polyvore_outfit_graph` 是独立 JSON 内存共现 smoke，不实现该抽象接口，也不进入主链。
- DummyGraphRetriever 当前为空实现，所有方法返回空列表。
- Neo4jRetriever 是二期 TODO 占位；Neo4j 尚未接入。

## 模块职责

- data 只负责数据读取、转换和增强。
- embeddings 只负责把文本或图片转换为向量。
- vectordb 只负责向量存储的建立和读取。
- retrievers 负责召回、结果模型和融合；当前还直接依赖 Chroma 具体类型。
- graph 定义图实体、关系和检索接口，并提供独立 Polyvore outfit JSON 内存共现查询；该 smoke 不持久化关系，也不接 Neo4j。
- llm 负责模型客户端和模型配置。
- chatbot 负责会话编排、提示词、历史，并延迟组装 LLM、检索器和图片向量库；当前直接使用 Chroma 具体类型。
- cli 负责用户入口，加载文本向量库和增强数据，并创建 `ShoppingChatbot`。
- api 只负责 HTTP schema、参数校验、路由和生命周期，通过共享 service 调用推荐能力。
- polyvore_recommend_service 负责 CLI/API 共用的 Chroma、Embedding、outfit 索引和 resolver 一次性组装，并提供推荐用例接口。

## 当前边界例外

- cli 与 chatbot.chain 共同承担对象组装：cli 组装启动必需对象，chatbot.chain 组装按模式延迟加载的对象。
- chatbot.chain 与 retrievers 均直接依赖 Chroma，而不是只依赖 vectordb 边界；这是当前实现事实和后续可评估的解耦点，不在本次多 Agent 基础设施任务中重构。
- Polyvore 小样本文本 collection 为 `products_text_v3_v1`，图片 collection 为 `products_image_cnclip_v1`；两者使用同一组字符串 `item_id`。独立 `cli_polyvore_retrieval` 使用两种查询向量与只读增强 JSONL 的本地 BM25，按 `item_id` 执行三路 RRF 后，再以同一增强 metadata 做轻量规则加权 smoke；材质字段不参与规则，旧 `products_text` 消费入口和现有 `HybridRetriever` 均保持不变。
- 独立 `cli_polyvore_recommend` 仅通过共享 `polyvore_recommend_service` 间接调用 `polyvore_retrieval` 的检索能力与 `graph.polyvore_outfit_graph` 的共现查询，不直接依赖 `cli_polyvore_retrieval`；它只负责参数解析、组装 service 和结果输出，不修改检索排序或图共现排序，不进入 Chatbot 主链。
- `polyvore_recommend_service` 负责从 `data.polyvore_item_resolver` 组装只读 resolver，并注入纯推荐编排层；resolver 仅装饰最终输出，不参与检索、规则加权或共现排序，`data` 不反向依赖推荐模块。
- FastAPI 封装后，`cli_polyvore_recommend` 与 `api` 均只依赖共享 `polyvore_recommend_service`；纯检索逻辑已从 CLI 机械迁移到 `polyvore_retrieval`，API 不依赖任何 `cli_*` 模块。`src/api/` 当前仅含 app 与 schemas，不继续拆分 routers/dependencies 等目录。
- 当前扫描未发现循环依赖，也未发现底层模块反向依赖 cli 或 chatbot。

## 结构变更规则

- 新增顶级目录必须有当前功能需要，并经用户批准。
- 禁止从底层模块反向依赖 cli 或 chatbot。
- 公共接口变化必须先冻结调用契约。
- 不为单次使用场景建立抽象层。
- 不在架构调整任务中顺手重构无关代码。
