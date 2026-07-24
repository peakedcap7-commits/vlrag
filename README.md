# ShoppingQnA 多模态穿搭问答助手

ShoppingQnA 是一个面向潮流穿搭场景的 AI 应用后端。它把商品图像、中文语义检索、Neo4j outfit 关系和大模型建议生成串起来，用来支持“单品推荐”“多件单品搭配判断”和“对话式改搭”。

当前版本重点是后端闭环：数据、向量库、图数据库、FastAPI 接口和 LangGraph 编排都已接入；正式前端仍未开始。

## 当前能力

| 能力 | 接口 | 状态 |
|---|---|---|
| 单品推荐 | `POST /polyvore/recommend`、`POST /assistant/message` | 已接入 |
| M2 多件单品搭配判断 | `POST /assistant/message`，传入 2～4 张图片 key | 已接入 |
| M3 对话式改搭 | `POST /assistant/message`，传入 message 和 conversation_state | 已接入 |
| M4 场景穿搭生成 | `POST /assistant/message` | 暂缓，返回 not_ready |

## 技术栈

- FastAPI / Uvicorn：HTTP 服务入口。
- LangGraph：规则意图路由和业务流程编排。
- Chroma：本地向量库。
- Chinese-CLIP：中文图文向量，负责文本搜图和图片相似检索。
- text-embedding-v3：中文文本语义向量。
- Neo4j：保存 Polyvore outfit 共现关系。
- MinIO：保存商品图片和用户临时上传图片。
- qwen-turbo：把内部分析事实转成用户可读的穿搭建议。
- pytest：单元、集成和契约测试。

## 架构概览

```text
FastAPI
  ├── /polyvore/recommend
  │     └── polyvore_recommend_service
  │           ├── text-embedding-v3 → Chroma 文本库
  │           ├── Chinese-CLIP → Chroma 图片库
  │           ├── BM25 关键词通道
  │           ├── RRF 融合与轻量规则加权
  │           └── Neo4j outfit provider
  │
  └── /assistant/message
        └── LangGraph assistant_graph
              ├── single_item_recommend
              ├── outfit_analyze：多图匹配 + Neo4j 共现 + LLM 建议
              ├── outfit_revise：约束解析 + 候选召回 + Neo4j 验证 + LLM 建议
              └── scene_outfit_generate：暂缓
```

核心边界：

- API 只负责 HTTP schema、参数校验、路由和生命周期。
- `assistant_graph` 只负责编排，不直接访问 Chroma、Neo4j、MinIO 或模型客户端。
- `polyvore_recommend_service` 负责组装 Chroma、Embedding、Neo4j provider 和 resolver。
- 用户图片只做临时读取和临时向量化，不进入商品向量库。

## 本地环境准备

### 1. 创建并安装依赖

项目推荐使用本地 `.venv`：

```powershell
cd D:\pj\vlrag\shopping-qna
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

如果只安装图数据库相关依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[graph]"
```

### 2. 配置环境变量

复制示例文件：

```powershell
Copy-Item .env.example .env
```

至少需要配置：

```env
DASHSCOPE_API_KEY=<your-dashscope-api-key>

CHINESE_CLIP_MODEL=C:\Users\Administrator\.cache\chinese-clip-vit-base-patch16
ENABLE_MODEL_WARMUP=false

MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=<your-minio-access-key>
MINIO_SECRET_KEY=<your-minio-secret-key>
MINIO_SECURE=false
MINIO_BUCKET=shopping-qna

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-neo4j-password>
OUTFIT_PROVIDER=neo4j
```

`CHINESE_CLIP_MODEL` 建议指向本地已缓存模型目录，避免启动时访问 HuggingFace 导致卡顿。

### 3. 启动 MinIO

示例命令：

```powershell
docker run -d `
  --name shopping-minio `
  -p 9000:9000 `
  -p 9001:9001 `
  -e "MINIO_ROOT_USER=<your-minio-access-key>" `
  -e "MINIO_ROOT_PASSWORD=<your-minio-secret-key>" `
  -v D:\pj\vlrag\shopping-qna\data\minio:/data `
  quay.io/minio/minio server /data --console-address ":9001"
```

控制台：

```text
http://localhost:9001
```

### 4. 启动 Neo4j

示例命令：

```powershell
docker run -d `
  --name shopping-neo4j `
  -p 7474:7474 `
  -p 7687:7687 `
  -v D:\pj\vlrag\shopping-qna\data\neo4j:/data `
  -e NEO4J_AUTH="neo4j/<your-neo4j-password>" `
  neo4j:5-community
```

浏览器管理页：

```text
http://localhost:7474
```

## 数据准备

当前项目使用 Polyvore outfit 数据做演示切片：

- MinIO：保存商品图片，key 形如 `polyvore/items/{item_id}.jpg`。
- Chroma 文本库：`products_text_v3_v1`，使用 text-embedding-v3。
- Chroma 图片库：`products_image_cnclip_v1`，使用 Chinese-CLIP。
- Neo4j：保存 `(:Item)-[:IN_OUTFIT]->(:Outfit)`。

本地数据和向量库不进入 Git：

- `data/processed/`
- `data/minio/`
- `data/neo4j/`
- `chroma_data/`
- `.venv/`

常用开发工具：

```powershell
.\.venv\Scripts\python.exe -m tools.cli_polyvore_neo4j_import
.\.venv\Scripts\python.exe -m tools.cli_polyvore_neo4j_item_assets
.\.venv\Scripts\python.exe -m tools.cli_polyvore_neo4j_chroma_index
```

这些工具只用于建库、导入和 smoke 验证，不是线上 API 入口。

## 启动后端

```powershell
cd D:\pj\vlrag\shopping-qna
.\.venv\Scripts\python.exe -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

建议先手动预热：

```powershell
curl -X POST http://127.0.0.1:8000/warmup
```

查看就绪状态：

```powershell
curl http://127.0.0.1:8000/health/ready
```

## API 示例

### 单品推荐

```powershell
curl -X POST http://127.0.0.1:8000/polyvore/recommend `
  -H "Content-Type: application/json" `
  -d '{"query":"蓝色裤子","top_k":3,"retrieval_limit":3}'
```

返回内容包含：

- anchor：检索到的锚点商品。
- outfit_candidates：Neo4j 中与锚点共现的搭配候选。

### M2 多件单品搭配判断

```powershell
curl -X POST http://127.0.0.1:8000/assistant/message `
  -H "Content-Type: application/json" `
  -d '{
    "message":"看看这三件单品搭不搭，给我穿搭建议",
    "image_keys":[
      "polyvore/items/199614803.jpg",
      "polyvore/items/211259367.jpg",
      "polyvore/items/212057657.jpg"
    ],
    "top_k":5,
    "retrieval_limit":3
  }'
```

流程：

```text
MinIO 读图 → Chinese-CLIP 临时编码 → 图片 Chroma Top-3
→ Neo4j 查询跨图共现 → 规则评分 → qwen-turbo 生成用户建议
```

公开响应只返回用户可读字段：

- verdict
- summary
- strengths
- issues
- suggestions

不会暴露 `item_id`、`outfit_id`、`rule_scores` 等内部技术字段。

### M3 对话式改搭

```powershell
curl -X POST http://127.0.0.1:8000/assistant/message `
  -H "Content-Type: application/json" `
  -d '{
    "message":"不要裙子，换成裤子，整体更正式一点",
    "conversation_state":{
      "anchor_item_id":"199614803",
      "candidate_item_ids":["211259367","212057657","214479153"],
      "selected_item_ids":["211259367"],
      "locked_item_ids":["199614803"],
      "excluded_item_ids":[],
      "item_metadata":[
        {
          "item_id":"199614803",
          "category":"上衣",
          "sub_category":"衬衫",
          "colors":["蓝色"],
          "style":["休闲"]
        },
        {
          "item_id":"211259367",
          "category":"下装",
          "sub_category":"半身裙",
          "colors":["黑色"],
          "style":["休闲"]
        }
      ],
      "last_intent":"outfit_analyze"
    },
    "top_k":5,
    "retrieval_limit":3
  }'
```

流程：

```text
规则解析改搭约束 → 判断是否需要追问
→ 文本 Chroma 召回替换候选 → metadata 过滤
→ Neo4j 验证保留项与候选的 outfit 共现
→ qwen-turbo 生成自然语言改搭建议
```

如果用户指代不清，例如“换掉这个”，但 `conversation_state` 里无法唯一定位商品，系统会返回追问，不会硬猜。

## 测试

运行全量测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

最近一次提交前验证结果：

```text
167 passed, 6 skipped
```

依赖检查：

```powershell
.\.venv\Scripts\python.exe -m pip check
```

代码格式基础检查：

```powershell
git diff --check
```

## 当前限制

- 正式前端尚未实现。
- 当前 Polyvore 只导入了演示切片，不是完整商品库。
- M4 场景穿搭生成暂缓。
- 用户上传图的鉴权、清理任务和生产级 TTL 策略还未实现。
- 部分路径仍是本机开发路径，迁移环境时需要调整 `.env` 和数据路径。
- qwen-turbo 是建议表达核心，已设置超时、一次重试和格式修复；最终失败才会走安全 fallback。

## 面试展示亮点

- 中文文本可以直接检索图片：Chinese-CLIP 统一中文文本和图像向量空间。
- 文本、图片、BM25 三路召回后用 RRF 融合，兼顾语义和关键词。
- Neo4j 不替代向量检索，而是负责“这件商品和哪些商品历史上一起出现过”的关系扩展。
- LangGraph 不是噱头：它把单品推荐、多图搭配判断、对话式改搭拆成可维护的业务节点。
- LLM 不负责乱猜商品，只负责把确定性检索和图关系结果转成自然建议。
- 用户图片不进入商品向量库，避免临时数据污染长期索引。

## 仓库安全说明

不要提交以下内容：

- `.env`
- API Key、Neo4j 密码、MinIO 密码
- `data/` 下的数据文件
- `chroma_data/`
- `.venv/`
- 本地模型权重

这些路径已通过 `.gitignore` 隔离。
