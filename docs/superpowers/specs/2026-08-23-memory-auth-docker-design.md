# ShoppingQnA 多租户记忆、认证与 Docker 设计

- 日期：2026-08-23
- 状态：待 database 复核后实施
- 范围：开发期本地 JWT、短期/语义/情景/程序四类记忆、多租户 RLS、Docker Compose
- 不包含：正式身份提供商、前端、M4、生产部署、现有推荐算法重构

## 1. 目标与验收边界

本设计在不改变现有 Chroma、Neo4j、MinIO 职责的前提下，为 `/assistant/message` 增加可信租户上下文和四类记忆，并允许全新 clone 通过一条 Compose 命令启动开发环境。

“启动成功”和“推荐数据可用”必须分开验收：仓库当前忽略 `data/processed/`、`chroma_data/`、MinIO 与 Neo4j 数据，且没有已确认可再分发的 seed 包。因此 Compose 可以保证全新 clone 的 API、PostgreSQL、MinIO、Neo4j 与 worker 启动；只有在提供经过许可、带校验和的 demo seed 后，才能承诺全新 clone 的 Polyvore 推荐链也可用。不得用空数据库冒充一键部署完成。

成功标准：

1. 未认证请求不能访问业务、记忆、反馈或管理接口；健康检查除外。
2. JWT 中的租户和用户身份不能由请求 body 覆盖。
3. 同一用户同一 thread 可恢复短期状态；不同 tenant 即使使用相同 UUID 也不可互读。
4. 语义记忆跨 thread 生效；情景记忆只从可信成功反馈生成；程序记忆只有审核后的版本可生效。
5. PostgreSQL RLS 在遗漏应用过滤条件时仍阻止跨租户读取和写入。
6. `docker compose up --build` 能从空 volume 幂等启动；seed 缺失时 readiness 明确报告 `data_not_ready`。

## 2. 已核实的当前事实

- `assistant_graph` 是无持久化的同步 StateGraph；没有 checkpointer、Store 或消息 reducer。
- `conversation_state` 当前完全由客户端回传，且 M3 依赖它定位商品。
- API 只负责 schema、路由和生命周期；图通过注入的 service 调用业务能力。
- Chroma 是 API 进程内的本地持久客户端，不是独立服务；当前只适合单 API 副本。
- 用户图片不得写入商品 Chroma；正式响应不得泄露内部图证据和商品技术标识。
- 当前没有关系型数据库、Dockerfile 或 Compose。

## 3. 最小架构

```text
                         PostgreSQL + pgvector
                    ┌──── thread/run/feedback
Bearer JWT → API ───┤──── semantic/episodic memory
                    ├──── procedural prompt versions
                    └──── memory jobs + audit
                         ↑
                    memory-worker
                         │ LangMem Core API

API ─→ assistant_graph ─→ 现有 services ─→ Chroma / Neo4j / MinIO / DashScope
```

Compose 只增加必要服务：

- `api`：FastAPI、LangGraph、现有推荐运行时；单副本。
- `memory-worker`：与 API 使用同一镜像，消费 PostgreSQL job；不引入 Redis。
- `postgres`：带 pgvector 的 PostgreSQL，保存所有新增状态和向量。
- `neo4j`、`minio`：沿用当前职责。
- `minio-init`：一次性幂等创建 bucket。
- `bootstrap`：一次性校验并导入获批 seed；没有 seed 时退出并让推荐 readiness 保持不可用。

不新增独立 Chroma 服务。`chroma_data` 和模型 cache 使用 named volume；API 保持一个 worker/副本，直到嵌入式 Chroma 的并发限制被替换或验证。

建议新增生产模块但不新增顶级目录：`src/auth.py`、`src/memory.py`、`src/memory_worker.py`。API schema 和路由仍留在现有 `src/api/`，不要为本次创建 repository/interface/factory 层级。

依赖方向：

```text
api → auth
api/runtime → memory → PostgreSQL / LangMem
assistant_graph → 注入的 memory service
memory_worker → memory / LangMem
```

`assistant_graph` 仍不得直接导入数据库 driver、Chroma、Neo4j 或 MinIO。

## 4. LangMem 存储选择

### 4.1 选择：LangMem Core API + 自管 PostgreSQL 表

使用：

- `create_memory_manager`：从已裁剪轨迹生成语义或情景记忆变更；
- `create_prompt_optimizer`：生成程序提示候选版本；
- 应用代码负责按 tenant/user 查询、upsert、软删除和 pgvector 相似检索。

不使用 `create_manage_memory_tool`，因为当前图不是 ReAct agent，没有工具调用循环。也不让模型决定租户 namespace。

### 4.2 与 PostgresStore 的比较

| 方案 | 优点 | 本项目问题 | 结论 |
|---|---|---|---|
| LangMem Core API + 自管表 | tenant/user 为显式列，RLS、审计、反馈外键和程序版本都直接可控 | 需写少量 CRUD 与向量查询 | 采用 |
| LangGraph PostgresStore | 官方 BaseStore，LangMem manager 可直接 upsert/search | tenant 位于序列化 `prefix`，不是一等列；RLS 需解析库内部格式；程序版本与审核仍需自建表；升级会耦合内部 schema | 不采用为业务记忆主存储 |

PostgresStore 曾出现 namespace prefix 越界问题；即使使用修复版本，也不应把字符串 namespace 当唯一租户安全边界。若其他功能以后采用它，至少固定 `langgraph-checkpoint-postgres>=3.1.1`，且仍需显式 tenant 授权。

短期状态也不引入 PostgresSaver。当前图没有中断恢复或 time travel，只需一次请求前读取、请求后保存最新业务状态；自管 `assistant_threads` 比引入四张 checkpoint 内部表更少、更容易做 RLS。以后真正加入 human-in-the-loop 时再评估 PostgresSaver。

## 5. JWT 信任边界

### 5.1 开发期 token

使用成熟 JWT 库验证 HS256，不自行实现密码学。开发 token 由本地 CLI 生成，不提供匿名 `/login` 或可公开调用的发 token HTTP 接口。

必需 claims：

- `iss`：固定开发 issuer；
- `aud`：固定 API audience；
- `sub`：用户 UUID；
- `tenant_id`：租户 UUID；
- `roles`：`user` 或 `tenant_admin`；
- `iat`、`exp`、`jti`。

验证要求：固定允许算法、校验签名/issuer/audience/exp，UUID 规范化，拒绝缺字段和未知角色。`DEV_JWT_SECRET` 至少 32 个随机字节，只从 `.env`/secret 注入，不提供仓库默认值。日志不得记录 token。

### 5.2 请求边界

- `tenant_id`、`user_id`、`roles` 只来自验证后的 token。
- body 中不接受这些字段；出现额外字段继续由 Pydantic `extra="forbid"` 拒绝。
- 客户端提供 `thread_id`，但每次都按当前 tenant/user 验证归属。
- API 在每个数据库事务开始执行 `SET LOCAL app.tenant_id`、`app.user_id`、`app.roles`；使用参数化值并在事务结束自动清除。
- API 数据库角色没有 `BYPASSRLS`、建表和改 policy 权限；migration owner 不用于运行 API。
- worker 可以领取跨租户 job，但实际处理每个 job 时必须进入该 job 的 tenant 上下文；不能把 worker owner 连接传给 LangMem 业务读写。

健康接口可匿名。`POST /warmup`、程序记忆管理和 tenant 共享情景晋升要求 `tenant_admin`。

## 6. 四类记忆的数据流

### 6.1 短期记忆

作用域：`tenant_id + user_id + thread_id`。

读取：认证和 thread 归属校验后、调用 graph 前读取最新 `conversation_state`。请求显式提供非空 `conversation_state` 时，以当前请求为准；省略时复用服务端状态。调用 graph 使用 `payload.model_dump(exclude_none=True)`，防止 `None` 清空已有状态。

写入：业务返回 `status=ok` 后保存本轮可继续对话的状态和最后意图；失败、`not_ready`、`unsupported` 不推进状态。第一阶段不自动从推荐结果猜造完整下一轮状态，继续兼容客户端显式传入。

不保存原始图片、图片向量、模型 chain-of-thought 或无限消息历史。run 表只保存必要的裁剪请求/结果摘要，thread 设置最后活动时间和可清理时间。

### 6.2 长期语义记忆

作用域：用户私有，跨 thread。

首版 schema 只允许稳定穿搭偏好：颜色、风格、品类、场景及明确长期约束。每条记忆包含维度、值、正负倾向、上下文、置信度和来源 run。临时指令、商品 ID、图片 key、内部证据和敏感自由文本不进入长期记忆。

读取：意图分类后、业务节点前，用当前消息向量检索同 tenant/user 的 active 记忆 Top-K。当前请求的明确约束优先；记忆只能作为软偏好，先转成结构化 `memory_context`，不得拼成伪造用户原话。

写入：`status=ok` 的 run 写入 `memory_jobs(type=semantic_extract)`；worker 使用 LangMem Core API 从裁剪轨迹生成 insert/update/delete 建议，再由白名单校验器写表。失败重试，超过次数保留 failed 状态，不影响原业务响应。

### 6.3 情景记忆

作用域：默认用户私有；管理员可把脱敏案例晋升为 tenant 共享。读取顺序为用户 private，再补 tenant shared，均只能取 active 小集合。

情景内容只保存可审计的 `observation/action/result`，不保存隐藏推理过程。它代表“什么做法在什么场景被验证有效”，不是普通聊天摘要。

成功信号：

- 强信号：`accepted`、`saved`、`purchased`；
- 明确信号：`thumbs_up` 或正评分；
- `thumbs_down`/负评分只进入失败轨迹，不生成成功 episode；
- HTTP 200、LLM 正常返回、用户继续说话都不是成功证据。

写入：反馈先幂等入库，再创建 `episodic_extract` job。worker 仅对正反馈 run 生成 episode，并保留 feedback/run 来源。tenant 共享必须脱敏并由 `tenant_admin` 审核；不得自动把单用户数据共享给租户。

读取：相似新任务进入相关业务节点前召回 1～3 个案例，以受限 few-shot 摘要注入。当前业务事实和安全规则高于 episode。

因此必须新增反馈 API；没有反馈时只能保留 run，不能声称已实现可信情景学习。

### 6.4 程序记忆

作用域：tenant + prompt_key。全局安全基线仍在代码中，程序记忆只能提供租户 overlay。

生成：管理员显式请求基于同 tenant 的脱敏 run/feedback 生成 `procedural_optimize` job；worker 调用 LangMem prompt optimizer，只产生 draft。线上用户文本不能直接修改 active prompt。

审核：draft 先通过确定性检查（长度、允许变量、允许段落、禁止新增工具/权限/数据源、禁止覆盖安全基线）和固定回归样例，再进入 review。`tenant_admin` 审核后才能激活。

读取：请求开始按 tenant/prompt_key 读取唯一 active version；与代码内基线合成并记录到 run。缓存键必须包含 tenant_id、prompt_key、version，短 TTL 或激活时失效。

激活与回滚：不原地修改内容。事务内锁定 active pointer，记录审计，再把指针切到已审核版本。回滚执行同一指针切换到历史已审核版本。删除 active 版本被禁止。

防注入规则：优化输入先裁剪和脱敏；候选只允许修改业务表达/偏好使用方式，不能修改身份、RLS、工具权限、输出 schema、技术字段隐藏规则或“当前请求优先”规则。生成者与审核者在开发期可为同一 admin，但生产化前应支持分离。

## 7. 拟建表与字段概念

以下是 database 复核输入，不是最终 DDL。所有业务表包含显式 `tenant_id`，时间统一为带时区时间；UUID 由服务端生成。

### 7.1 `assistant_threads`

- `tenant_id`、`user_id`、`thread_id`
- `conversation_state` JSONB
- `last_intent`
- `created_at`、`updated_at`、`expires_at`
- 概念约束：主键/唯一键覆盖 tenant、user、thread；同 thread 不能跨 user 复用

### 7.2 `assistant_runs`

- `tenant_id`、`user_id`、`thread_id`、`run_id`
- `intent`、`status`
- `request_summary`、`response_summary` JSONB（已裁剪）
- `prompt_key`、`prompt_version`
- `created_at`
- 概念约束：run 唯一；关联所属 thread；不保存 token、图片字节或 chain-of-thought

### 7.3 `semantic_memories`

- `tenant_id`、`user_id`、`memory_id`
- `dimension`、`value`、`polarity`、`context`
- `confidence`、`source_run_id`
- `embedding` vector(1024)
- `status`（active/deleted）
- `created_at`、`updated_at`、`deleted_at`
- 概念索引：tenant/user/status；同用户相似检索向量索引；稳定去重键由 database 评估

### 7.4 `assistant_feedback`

- `tenant_id`、`user_id`、`feedback_id`
- `thread_id`、`run_id`
- `event`、`rating`、`comment`
- `idempotency_key`、`created_at`
- 概念约束：反馈必须引用同 tenant/user 的 run；tenant/user 下 idempotency 唯一

### 7.5 `episodic_memories`

- `tenant_id`、`memory_id`
- `owner_user_id`（tenant shared 时为空）
- `scope`（user/tenant）
- `observation`、`action`、`result`
- `source_run_id`、`source_feedback_id`
- `source_job_id`、`source_item_index`（worker 重放幂等键；旧数据可为空）
- `embedding` vector(1024)
- `status`（pending/active/rejected/deleted）
- `reviewed_by`、`reviewed_at`
- `created_at`、`updated_at`、`deleted_at`
- 概念约束：user scope 必须有 owner；tenant scope 必须经过审核才能 active；同 job/scope/item index 只能落一条

### 7.6 `procedural_prompt_versions`

- `tenant_id`、`prompt_key`、`version_id`、`parent_version_id`
- `content`、`content_hash`
- `status`（draft/review/approved/rejected/retired）
- `evidence_summary`、`evaluation_metrics` JSONB
- `created_by`、`approved_by`
- `created_at`、`approved_at`
- 概念约束：内容不可原地更新；tenant/prompt_key/version 唯一

### 7.7 `procedural_prompt_active`

- `tenant_id`、`prompt_key`、`version_id`
- `activated_by`、`activated_at`
- 概念约束：tenant/prompt_key 唯一；只能指向同 tenant/key 的 approved 版本

### 7.8 `memory_jobs`

- `tenant_id`、`user_id`（租户级任务可为空）、`job_id`
- `job_type`、`source_run_id`、`payload` JSONB
- `status`（pending/running/done/failed）
- `attempts`、`available_at`、`locked_at`、`locked_by`、`last_error_code`
- `created_at`、`updated_at`
- 概念约束：同来源/任务类型幂等；使用 `FOR UPDATE SKIP LOCKED` 领取；10 分钟租约过期后自动恢复，最多领取 3 次；错误只存安全类型

### 7.9 `audit_events`

- `tenant_id`、`event_id`
- `actor_user_id`、`action`、`resource_type`、`resource_id`
- `before_summary`、`after_summary` JSONB
- `created_at`
- 追加写；覆盖 prompt 激活/回滚、共享 episode 审核及记忆删除

未单独建立 tenants/users/memberships 表。开发期身份和角色来自已签名 JWT；等接入真实 IdP、成员撤销或租户生命周期时再建，避免两套身份真相。

## 8. RLS 规则

所有上述业务表启用并 `FORCE ROW LEVEL SECURITY`。

最小策略语义：

- 普通用户：只能访问 `tenant_id=current_tenant` 且 `user_id/owner_user_id=current_user` 的私有数据；可以读取同 tenant 已激活的 shared episode 和 active prompt。
- tenant admin：只能在当前 tenant 内审核共享 episode、管理 prompt 和查看必要审计；不能越过 tenant。
- 插入/更新同时使用 `WITH CHECK`，防止把行改写到其他 tenant/user。
- worker 领取 job 使用专用受限函数或专用 poll role；领取后业务写入仍使用目标 tenant context。
- migration owner 不被 API/worker 复用。

RLS 测试必须故意省略应用层 tenant WHERE，确认数据库仍拒绝或返回零行；还要覆盖相同 `thread_id/run_id/memory_id` 在两个 tenant 中并存。

## 9. API 契约

所有业务请求使用：

```http
Authorization: Bearer <local-jwt>
```

### 9.1 消息

`POST /assistant/message` 请求新增必填：

```json
{
  "thread_id": "uuid",
  "message": "...",
  "image_keys": [],
  "conversation_state": null,
  "top_k": 5,
  "retrieval_limit": 5
}
```

响应在现有字段上新增：

```json
{
  "thread_id": "uuid",
  "run_id": "uuid",
  "intent": "single_item_recommend",
  "status": "ok",
  "result": {},
  "message": "推荐完成。"
}
```

`tenant_id/user_id` 不进入 body 或响应。过渡期保留 `conversation_state`；服务端状态仅在其缺省时补足。

### 9.2 反馈

`POST /assistant/feedback`：`thread_id`、`run_id`、`event`、可选 `rating/comment`、必填 `idempotency_key`。只允许反馈当前用户所属 run。

### 9.3 用户记忆

- `GET /assistant/memories?type=semantic|episodic`
- `DELETE /assistant/memories/{memory_id}`

删除为软删除并写审计；接口不得删除程序记忆或他人/共享记忆。批量删除和导出不是首版要求。

### 9.4 租户管理

- `POST /admin/prompts/{prompt_key}/optimize`
- `GET /admin/prompts/{prompt_key}/versions`
- `POST /admin/prompts/{prompt_key}/versions/{version_id}/approve`
- `POST /admin/prompts/{prompt_key}/versions/{version_id}/activate`
- `POST /admin/prompts/{prompt_key}/rollback`
- `POST /admin/episodes/{memory_id}/approve`

只接受 `tenant_admin`。激活/回滚必须提供目标版本或期望当前版本，避免并发覆盖。

`/polyvore/recommend` 也要求认证，避免形成绕过租户审计的第二业务入口。`/health`、`/health/ready` 匿名，但不返回配置、身份或数据库细节。

## 10. Docker 与 bootstrap

### 10.1 配置

Compose 内部地址使用服务名：PostgreSQL、MinIO、Neo4j 不再指向 localhost。需要把 Chroma、processed data、模型 cache 路径改为环境变量，消除 Windows 绝对路径。

必需 secrets：`DASHSCOPE_API_KEY`、`DEV_JWT_SECRET`、PostgreSQL/MinIO/Neo4j 密码。Compose 文件不写可用默认密码；用户从 `.env.example` 生成 `.env` 后运行一条启动命令。

### 10.2 幂等启动顺序

1. PostgreSQL 健康后，由 migration/init 命令创建扩展、表和 RLS；API 运行角色无迁移权限。
2. MinIO 健康后，`minio-init` 幂等创建 bucket。
3. Neo4j 健康后，bootstrap 执行幂等约束和数据导入。
4. bootstrap 校验 seed manifest 与 SHA-256 后导入 processed files、MinIO、Neo4j、Chroma。
5. API/worker 启动；`/health/ready` 分别报告 runtime、postgres、seed 状态。

不要把模型权重、`.env`、生成后的 Chroma 或数据库 volume 打进 Git。镜像使用固定 Python 基础版本；依赖先锁定并验证 LangMem/LangGraph 兼容，再构建。

### 10.3 新 clone 的真实限制

当前不存在可供 Compose 获取的获批 seed。实施前必须选择并记录一种：

1. 发布经过许可的固定 demo seed artifact，并配置 URL + SHA-256（推荐）；
2. 要求开发者提供本地 seed 路径，此时只能称“一键启动”，不能称“新 clone 推荐可用”；
3. 提交一个极小的自有/合成 seed，降低展示质量但无授权风险。

bootstrap 不能在构建时偷偷下载未固定版本的大数据集，也不能在失败后把 API 标记 ready。

## 11. 分阶段实施与验收

### 阶段 0：契约和依赖 spike

- 固定 LangMem、LangGraph/PostgreSQL driver、JWT 库版本。
- 用现有 DashScopeEmbeddings 验证 1024 维 pgvector 写入与查询。
- database 复核九张表、RLS、索引、迁移和回滚。

验收：最小脚本可抽取一条记忆、写入、同租户检索；跨租户零结果。

### 阶段 1：Docker、JWT、RLS、短期状态

- 建镜像/Compose、migration、开发 token CLI。
- 保护业务端点；接入 thread/run。

验收：空 volume 幂等启动；伪造/过期/错误 audience token 为 401；普通用户访问 admin 为 403；相同 thread UUID 跨 tenant 隔离；旧 M2/M3 结果 schema 除新增 ID 外保持。

### 阶段 2：语义记忆

- 接入读前召回、job、worker、LangMem Core 抽取和用户删除。

验收：一个 thread 表达稳定偏好，job 完成后另一 thread 可召回；当前明确相反要求覆盖旧偏好；删除后不再召回；失败不破坏推荐响应。

### 阶段 3：反馈与情景记忆

- 增加反馈接口、正负信号、用户 episode、管理员共享晋升。

验收：重复 idempotency 不重复写；HTTP 200 不自动生成 episode；负反馈不生成成功 episode；未审核 private episode 不可跨用户；共享后只在同 tenant 可读。

### 阶段 4：程序记忆

- 增加优化、校验、审核、激活、缓存和回滚。

验收：普通用户不能生成/激活；draft 不影响请求；未审核版本不能激活；激活后 run 记录版本；回滚立即恢复旧版本；恶意轨迹不能改变工具、RLS、安全基线或输出 schema。

### 阶段 5：seed 与完整验收

- 选定合法 seed 策略，验证全新 clone。
- 跑相关单元、RLS 集成、Compose smoke、现有推荐回归、reviewer 与 acceptance。

验收：清空 volumes 后按文档仅执行环境准备和一条 Compose 命令，服务健康且 seed 状态真实；若配置推荐 seed，单品/M2/M3 smoke 可复现。

## 12. 迁移和回滚

向前迁移：先部署 PostgreSQL 表/RLS和兼容旧 body 的 API，再要求客户端发送 `thread_id`；记忆功能用环境开关按 semantic、episodic、procedural 顺序开启。新增响应字段对能忽略未知字段的客户端兼容；严格客户端必须同步升级。

功能回滚：

- `MEMORY_READ_ENABLED=false`：停止注入长期记忆；
- `MEMORY_WRITE_ENABLED=false`：停止创建新 job；
- 保留 thread/run，不删除数据；
- 程序记忆回滚通过 active pointer 切换，不回滚表内容；
- API 镜像回滚前保持新增列/表，避免不可逆 down migration。

数据回滚：迁移必须提供对应测试环境回滚说明，但生产不自动 drop 表、向量或审计。删除和生产迁移仍需单独批准。

Docker 回滚：镜像使用版本 tag，volume 不随容器删除；禁止把 `docker compose down -v` 写成普通操作步骤。

## 13. 已知风险与明确不做

- LangMem 抽取是模型判断，可能误记；用白名单 schema、来源、置信度、用户删除和当前请求优先降低风险，不能保证零错误。
- pgvector 与商品 Chroma 是不同存储：前者只存用户记忆，后者继续存商品索引，不迁移或合并。
- 第一版不做真实 IdP、token revocation、租户成员后台、跨区域部署、自动 prompt 灰度、批量记忆导出。
- 第一版不让 checkpoint 接管完整消息历史，不实现 LangGraph time travel/HITL。
- 第一版不自动把 private episode 共享，也不自动激活程序候选。
- 全新 clone 推荐可用仍受 seed 授权和分发决定阻塞；基础设施启动不受阻塞。

## 14. database 复核清单

database 在写最终 DDL 前必须确认：

1. 九张表是否能进一步合并而不损害 RLS、审计或幂等；
2. UUID/枚举/JSONB/vector 类型、外键和唯一约束；
3. 1024 维向量的索引类型与小数据量下是否先不建 ANN；
4. RLS 的 SELECT/INSERT/UPDATE/DELETE 与 admin/worker policy；
5. worker 跨租户领取 job 的最小权限实现；
6. thread/run/feedback/记忆的 TTL、软删除和清理索引；
7. prompt active pointer 的原子激活、并发检查和回滚；
8. migration owner、API role、worker role 的权限分离；
9. forward migration、测试环境 rollback、备份恢复和不删除已有数据的路径。
