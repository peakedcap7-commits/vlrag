# ShoppingQnA 架构边界

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent，architect 负责评审
- 状态：已生效

## 当前依赖方向

```text
cli / chatbot
      ↓
retrievers
      ↓
vectordb / embeddings / graph
      ↓
外部模型、Chroma、Neo4j
```

数据准备链路：

```text
run_pipeline
      ↓
data
      ↓
llm
```

## 模块职责

- data 只负责数据读取、转换和增强。
- embeddings 只负责把文本或图片转换为向量。
- vectordb 只负责向量存储的建立和读取。
- retrievers 负责召回、结果模型和融合。
- graph 负责图实体、关系和图检索。
- llm 负责模型客户端和模型配置。
- chatbot 负责会话编排、提示词和历史。
- cli 负责用户入口和对象组装。

## 结构变更规则

- 新增顶级目录必须有当前功能需要，并经用户批准。
- 禁止从底层模块反向依赖 cli 或 chatbot。
- 公共接口变化必须先冻结调用契约。
- 不为单次使用场景建立抽象层。
- 不在架构调整任务中顺手重构无关代码。
