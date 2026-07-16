# ShoppingQnA 架构边界

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent，architect 负责评审
- 状态：已生效

## 当前依赖方向

```text
cli
├── data
├── vectordb ──→ embeddings ──→ DashScope / OpenCLIP
└── chatbot
    ├── llm ──→ DashScope
    ├── vectordb ──→ Chroma
    ├── Chroma
    └── retrievers
        ├── llm
        ├── embeddings
        └── Chroma
```

当前代码中的直接依赖包括：

- `chatbot → llm`：`ShoppingChatbot` 创建生成模型客户端。
- `chatbot → vectordb`：切换到图像或混合模式时延迟加载图片向量库。
- `chatbot → Chroma`：`ShoppingChatbot` 的构造参数和成员直接使用 Chroma 具体类型。
- `retrievers → llm`：文本检索器用视觉模型把图片描述成文本。
- `retrievers → embeddings`：多模态检索器直接使用 OpenCLIP 编码查询。
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

- graph 是独立预留接口，不在当前检索主链。
- DummyGraphRetriever 当前为空实现，所有方法返回空列表。
- Neo4jRetriever 是二期 TODO 占位；Neo4j 尚未接入。

## 模块职责

- data 只负责数据读取、转换和增强。
- embeddings 只负责把文本或图片转换为向量。
- vectordb 只负责向量存储的建立和读取。
- retrievers 负责召回、结果模型和融合；当前还直接依赖 Chroma 具体类型。
- graph 只定义图实体、关系和检索接口，当前不提供实际图数据召回。
- llm 负责模型客户端和模型配置。
- chatbot 负责会话编排、提示词、历史，并延迟组装 LLM、检索器和图片向量库；当前直接使用 Chroma 具体类型。
- cli 负责用户入口，加载文本向量库和增强数据，并创建 `ShoppingChatbot`。

## 当前边界例外

- cli 与 chatbot.chain 共同承担对象组装：cli 组装启动必需对象，chatbot.chain 组装按模式延迟加载的对象。
- chatbot.chain 与 retrievers 均直接依赖 Chroma，而不是只依赖 vectordb 边界；这是当前实现事实和后续可评估的解耦点，不在本次多 Agent 基础设施任务中重构。
- 当前扫描未发现循环依赖，也未发现底层模块反向依赖 cli 或 chatbot。

## 结构变更规则

- 新增顶级目录必须有当前功能需要，并经用户批准。
- 禁止从底层模块反向依赖 cli 或 chatbot。
- 公共接口变化必须先冻结调用契约。
- 不为单次使用场景建立抽象层。
- 不在架构调整任务中顺手重构无关代码。
