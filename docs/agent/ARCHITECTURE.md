# ShoppingQnA 架构边界

- 最后更新时间：2026-07-23
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
api ──→ polyvore_recommend_service ←── tools.cli_polyvore_recommend
              ├── polyvore_retrieval
              ├── polyvore_recommend
              ├── graph
              │   └── neo4j_outfit_provider ──→ Neo4j
              ├── data
              ├── embeddings
              └── Chroma
```

统一 Assistant 编排入口：

```text
api ──→ assistant_graph ──→ polyvore_recommend_service
              ├── single_item_recommend（已接入）
              ├── outfit_analyze_service（M2-A/B/C，内部事实与评分）
              ├── outfit_advice_service（M2-D，文本 LLM 用户表达）
              ├── outfit_revise_service（M3-A+，标准化、状态绑定与追问）
              ├── outfit_revise_candidate_service（M3-B，文本候选召回与过滤）
              └── scene_outfit_generate（M4 暂缓）
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

图检索：

- `neo4j_outfit_provider` 是当前 Polyvore 推荐主链的 outfit 候选查询实现。
- DummyGraphRetriever 当前为空实现，所有方法返回空列表。
- Neo4jRetriever 是旧二期 TODO 占位；当前 Polyvore 链路使用专用 `neo4j_outfit_provider`，暂不重构旧抽象。

## 模块职责

- data 只负责数据读取、转换和增强。
- embeddings 只负责把文本或图片转换为向量。
- vectordb 只负责向量存储的建立和读取。
- retrievers 负责召回、结果模型和融合；当前还直接依赖 Chroma 具体类型。
- graph 定义图实体、关系和检索接口，并提供 Polyvore 专用 Neo4j outfit provider。
- neo4j_outfit_provider 只负责按 anchor item_id 查询同 outfit 候选；service 直接依赖该窄查询实现，API 不依赖 Neo4j driver。
- llm 负责模型客户端和模型配置。
- chatbot 负责会话编排、提示词、历史，并延迟组装 LLM、检索器和图片向量库；当前直接使用 Chroma 具体类型。
- cli 负责用户入口，加载文本向量库和增强数据，并创建 `ShoppingChatbot`。
- api 只负责 HTTP schema、参数校验、路由和生命周期，通过共享 service 调用推荐能力。
- api.runtime 负责重资源的线程安全懒加载、幂等预热、就绪状态和关闭；不包含推荐或 M2 算法。
- assistant_graph 只负责规则意图路由和流程编排，通过注入的 service 调用现有推荐能力；不得直接依赖 Chroma、Neo4j driver、MinIO 或 tools。
- outfit_analyze_service 负责 MinIO 图片读取、临时 Chinese-CLIP 编码、商品图片 collection 只读查询、resolver 元数据补齐、跨图 Neo4j 共现和规则评分；不得执行 upsert 或调用 LLM/VLM。
- outfit_advice_service 只接收裁剪后的 M2-C 事实并调用文本 LLM；输出固定五字段，不得向正式 API 泄露图证据、规则分、商品 ID 或 outfit ID。
- outfit_revise_service 只读取消息与结构化 conversation_state，标准化改搭约束、绑定当前商品并判断是否需要追问；不得查询 Chroma、Neo4j、MinIO，不得调用模型或执行候选替换。
- outfit_revise_candidate_service 仅通过 polyvore_retrieval 查询 `products_text_v3_v1`，再用 resolver 补齐 metadata 并过滤排除/锁定商品；不得查询 Neo4j、调用 LLM/VLM、写入 Chroma 或执行最终搭配排序。
- neo4j_outfit_provider 的 `query_pairwise` 只查询不同输入图候选组合的共享 outfit；同一输入图内部的三个相似候选不得参与搭配共现。
- polyvore_recommend_service 负责 CLI/API 共用的 Chroma、Embedding、Neo4j provider 和 resolver 一次性组装，并提供推荐用例接口。
- tools 只负责开发、建库和 smoke 命令入口，单向依赖 src 中的 service、graph、vectordb、embeddings 和 data；src 生产模块不得反向依赖 tools。

## 当前边界例外

- cli 与 chatbot.chain 共同承担对象组装：cli 组装启动必需对象，chatbot.chain 组装按模式延迟加载的对象。
- chatbot.chain 与 retrievers 均直接依赖 Chroma，而不是只依赖 vectordb 边界；这是当前实现事实和后续可评估的解耦点，不在本次多 Agent 基础设施任务中重构。
- Polyvore 文本 collection 为 `products_text_v3_v1`，图片 collection 为 `products_image_cnclip_v1`；两者统一使用字符串 `item_id`。独立 `tools.cli_polyvore_retrieval` 使用两种查询向量与只读检索 JSONL 的本地 BM25，按 `item_id` 执行三路 RRF 后，再以同一 metadata 做轻量规则加权 smoke；材质字段不参与规则，旧 `products_text` 消费入口和现有 `HybridRetriever` 均保持不变。
- 独立 `tools.cli_polyvore_recommend` 仅通过共享 `polyvore_recommend_service` 间接调用 `polyvore_retrieval` 的检索能力与 Neo4j outfit provider，不直接依赖 `tools.cli_polyvore_retrieval`；它只负责参数解析、组装 service 和结果输出，不修改检索排序或图共现排序，不进入 Chatbot 主链。
- `polyvore_recommend_service` 负责从 `data.polyvore_item_resolver` 组装 Neo4j manifest、sample manifest、enriched JSONL 三层只读 resolver；resolver 仅装饰最终输出，不参与检索、规则加权或共现排序。
- FastAPI 封装后，`tools.cli_polyvore_recommend` 与 `api` 均只依赖共享 `polyvore_recommend_service`；纯检索逻辑位于 `polyvore_retrieval`，API 不依赖任何 tools 或 `cli_*` 模块。`src/api/` 当前仅含 app 与 schemas，不继续拆分 routers/dependencies 等目录。
- `/assistant/message` 的请求使用结构化 `conversation_state`，`image_keys` 最多四个且不可重复；响应 `result` 是推荐、搭配分析、改搭结果或空值的显式联合类型。M3-A+ 允许传入当前 item metadata，校验商品 ID 非空、唯一及锁定/排除集合不冲突；歧义和约束冲突返回结构化追问，不执行真实替换。
- M3-B 仅在 `needs_clarification=false` 时召回 replacement_candidates；查询由偏好类目、颜色和正式/休闲变化组成，结果按 metadata 匹配优先并保持文本召回次序作为次级顺序。
- FastAPI 生命周期从 `polyvore_recommend_service` 复用已加载的 Chinese-CLIP、Chroma client 和 resolver 组装 `outfit_analyze_service`，避免重复加载模型；API 和 LangGraph 不直接访问存储客户端。
- M2-C 评分固定为图关系40、品类20、颜色20、风格20；strong 要求图分至少30且总分至少75，medium 为存在少量共现或总分至少50，其余为 weak。
- M2-D 保持“确定性分析在前、LLM 表达在后”：LLM 不参与图片理解、相似检索、图查询或规则计分。
- FastAPI 默认以 `not_ready` 启动，首次业务请求或 `POST /warmup` 触发同一幂等初始化；`ENABLE_MODEL_WARMUP=true` 时在生命周期进入阶段提前初始化。健康存活与模型就绪状态分离。
- `src.cli` 是旧 Kream 交互入口，仍可能使用旧 `products_text`，但不属于 FastAPI/LangGraph/Polyvore 产品主链；当前不删除该历史入口和数据。
- `OUTFIT_PROVIDER=neo4j` 时，推荐 service 直接使用 Neo4j outfit provider；连接、认证、Cypher 或 schema 错误直接向上抛出，不回退 JSON 内存图。
- 当前扫描未发现循环依赖，也未发现底层模块反向依赖 cli 或 chatbot。

## 结构变更规则

- 新增顶级目录必须有当前功能需要，并经用户批准。
- 禁止从底层模块反向依赖 cli 或 chatbot。
- 公共接口变化必须先冻结调用契约。
- 不为单次使用场景建立抽象层。
- 不在架构调整任务中顺手重构无关代码。
- `outfit_revise_graph_service` 负责 M3-C 只读共现验证和用户态排序；通过 `neo4j_outfit_provider` 访问图数据，API/LangGraph 不直接依赖 Neo4j driver。`outfit_revise_candidate_service` 仍只负责文本召回与 metadata 过滤。
- `outfit_revise_advice_service` 负责 M3-D 文本表达，仅接收裁剪后的约束、用户可读的保留/上下文单品描述和已排序候选；不得向 LLM 传递保留商品 ID，并在所有返回路径清理内部标识。
- `performance` 提供同步轻量计时和结构化日志；API middleware 记录总耗时，各 service/provider 只记录自身外部依赖阶段，不向响应 schema 注入 debug 字段。
- M2/M3 advice 保持 LLM 主路径；格式修复只处理 JSON 结构、不改变语义。网络、超时或二次解析失败时由各 advice service 生成同 schema 的保守 fallback，且不得重新选品、改序或补充未知属性。
- Chinese-CLIP 模型位置由 `CHINESE_CLIP_MODEL` 配置；本机可指向已缓存目录以稳定冷启动，示例配置不得固化真实凭据。
