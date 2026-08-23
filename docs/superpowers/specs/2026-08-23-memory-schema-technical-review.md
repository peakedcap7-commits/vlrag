# ShoppingQnA 记忆 Schema 技术评审

- 日期：2026-08-23
- 评审角色：database
- 评审范围：九张业务表、RLS、worker 权限、生命周期、迁移与回滚
- 依据：`2026-08-23-memory-auth-docker-design.md`
- 结论：有条件批准进入实现

## 1. 总结

设计选择合理：使用 LangMem Core API 生成结构化变更建议，业务记忆写入自管 PostgreSQL 表；不把 LangGraph `PostgresStore` 当业务记忆主存，也不为当前无中断、无 time travel 的图引入 `PostgresSaver`。

原因不是排斥官方组件，而是本项目的真实约束需要显式 `tenant_id`、RLS、反馈外键、程序版本审核和确定性删除。把租户藏进 PostgresStore 的序列化 prefix 后再解析，会增加升级耦合与安全验证成本。Core API 本身不要求特定存储，因此自管表仍属于正常 LangMem 集成。

按 ponytail full 复核后，九张表全部保留，不再增加第十张“通用 memory”或身份表：

| 表 | 结论 | 最小化处理 |
|---|---|---|
| `assistant_threads` | 保留 | 只存最新短期状态，不存完整消息历史 |
| `assistant_runs` | 保留 | `user_id` 从 thread 派生，不重复保存 |
| `semantic_memories` | 保留 | 结构化偏好独立成表，不塞入通用 JSONB |
| `assistant_feedback` | 保留 | `thread_id/user_id` 从 run 派生，不重复保存 |
| `episodic_memories` | 保留 | 与 semantic 的审核、scope 和字段不同，不合并 |
| `procedural_prompt_versions` | 保留 | 内容版本不可变，保留已批准历史供回滚 |
| `procedural_prompt_active` | 保留 | 一个极小活动指针比在版本行上切换多种状态更清楚 |
| `memory_jobs` | 保留 | PostgreSQL 队列已足够，不新增 Redis/Celery |
| `audit_events` | 保留 | 管理动作不等同 assistant run；仅存安全元数据 |

首版删除两类冗余：run/feedback 上重复的用户归属列，以及没有数据证明需要的 ANN 索引。向量查询先使用租户、用户、状态过滤后的精确余弦距离；当真实数据和 `EXPLAIN (ANALYZE, BUFFERS)` 证明不足时再加 HNSW。

## 2. 数据类型约定

- UUID 由服务端生成；允许不同 tenant 使用相同业务 UUID，因此所有 PK/FK 均包含 `tenant_id`。
- 时间统一为 `timestamptz`，默认 `now()`；应用不得传无时区时间。
- 状态使用 `text + CHECK`，不使用 PostgreSQL ENUM，避免后续增加状态必须修改类型。
- 向量固定 `vector(1024)`；写入前校验现有 DashScope embedding 的维数。
- JSONB 只承载裁剪后的可演进摘要、job payload 和评测指标；可查询、可约束的一等字段不得藏入 JSONB。
- ID 文本（如 `prompt_key`、`idempotency_key`、`dedupe_key`）必须非空；长度上限由 API 校验，数据库至少使用 `CHECK (btrim(value) <> '')`。
- 所有含 `updated_at` 的表由 SQL 显式更新，不为一个时间戳增加通用 trigger。

## 3. 最终推荐表结构

以下为实现契约，不要求迁移逐字使用同一 DDL 排版。

### 3.1 `assistant_threads`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `thread_id` | `uuid` | NOT NULL |
| `user_id` | `uuid` | NOT NULL |
| `conversation_state` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb`，必须为 object |
| `last_intent` | `text` | NULL；非空时限制为现有五种 intent |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `expires_at` | `timestamptz` | NOT NULL |

- PK：`(tenant_id, thread_id)`。这直接禁止同 tenant 内把同一 thread UUID 绑定给两个用户。
- CHECK：`jsonb_typeof(conversation_state) = 'object'`；`expires_at >= updated_at`。
- 索引：`(tenant_id, user_id, updated_at DESC)`；清理索引 `(expires_at) WHERE expires_at IS NOT NULL`。
- 不增加软删除状态；短期状态到期或用户清除时直接硬删。

### 3.2 `assistant_runs`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `run_id` | `uuid` | NOT NULL |
| `thread_id` | `uuid` | NOT NULL |
| `intent` | `text` | NOT NULL，限制为现有五种 intent |
| `status` | `text` | NOT NULL，`ok/not_ready/unsupported/error` |
| `request_summary` | `jsonb` | NOT NULL DEFAULT `'{}'`，必须为 object |
| `response_summary` | `jsonb` | NOT NULL DEFAULT `'{}'`，必须为 object |
| `prompt_key` | `text` | NULL |
| `prompt_version_id` | `uuid` | NULL；与 prompt_key 同为空或同非空 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `expires_at` | `timestamptz` | NOT NULL |

- PK：`(tenant_id, run_id)`。
- FK：`(tenant_id, thread_id) -> assistant_threads`，`ON DELETE CASCADE`。
- FK：`(tenant_id, prompt_key, prompt_version_id) -> procedural_prompt_versions`，`ON DELETE RESTRICT`。
- CHECK：两个 summary 是 object；prompt 两列成对；`expires_at >= created_at`。
- 索引：`(tenant_id, thread_id, created_at DESC)`；`(expires_at)`。
- 不保存 `user_id`；RLS 通过 thread 归属判断，消除重复身份漂移。

### 3.3 `semantic_memories`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `memory_id` | `uuid` | NOT NULL |
| `user_id` | `uuid` | NOT NULL |
| `dimension` | `text` | NOT NULL，`color/style/category/scene/constraint` |
| `value` | `text` | NOT NULL，存白名单规范化值 |
| `polarity` | `smallint` | NOT NULL，`-1` 或 `1` |
| `context` | `text` | NULL，裁剪后的非敏感上下文 |
| `confidence` | `real` | NOT NULL，0..1 |
| `source_run_id` | `uuid` | NULL |
| `embedding` | `vector(1024)` | NULL；active 时必须存在，用户删除时清空 |
| `status` | `text` | NOT NULL，`active/superseded/deleted` |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `expires_at` | `timestamptz` | NULL；仅推断记忆默认设置 |
| `deleted_at` | `timestamptz` | NULL |

- PK：`(tenant_id, memory_id)`。
- FK：`(tenant_id, source_run_id) -> assistant_runs`，`ON DELETE SET NULL (source_run_id)`，不得把非空 tenant_id 一并置空。
- CHECK：`btrim(value) <> ''`；`confidence BETWEEN 0 AND 1`；active 时 embedding 必须存在；deleted 时 embedding 必须为空；删除状态与 `deleted_at` 一致。
- 去重：唯一部分表达式索引 `(tenant_id, user_id, dimension, lower(value), polarity) WHERE status='active'`。首版白名单值足以作为稳定键；不再增加 `normalized_value`。
- 查询索引：`(tenant_id, user_id, status)`；清理索引 `(expires_at) WHERE expires_at IS NOT NULL AND status='active'`；`(deleted_at) WHERE status='deleted'`。
- 首版不建 HNSW/IVFFlat。查询必须先限定 tenant/user/active，再按 `embedding <=> query_vector` 精确排序并 LIMIT。

### 3.4 `assistant_feedback`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `feedback_id` | `uuid` | NOT NULL |
| `run_id` | `uuid` | NOT NULL |
| `event` | `text` | NOT NULL，`accepted/saved/purchased/thumbs_up/thumbs_down/rating` |
| `rating` | `smallint` | NULL，1..5 |
| `comment` | `text` | NULL，裁剪且有 API 长度上限 |
| `idempotency_key` | `text` | NOT NULL，非空 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `expires_at` | `timestamptz` | NOT NULL |

- PK：`(tenant_id, feedback_id)`。
- FK：`(tenant_id, run_id) -> assistant_runs`，`ON DELETE CASCADE`。
- UNIQUE：`(tenant_id, run_id, idempotency_key)`。
- CHECK：rating 在 1..5；`event='rating'` 时 rating 必填，其他 event 不强制 rating 为空，以兼容点赞附评分。
- 索引：`(tenant_id, run_id, created_at DESC)`；`(expires_at)`。
- 不保存 `thread_id/user_id`，均从 run/thread 派生。

### 3.5 `episodic_memories`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `memory_id` | `uuid` | NOT NULL |
| `owner_user_id` | `uuid` | NULL；tenant shared 时必须为空 |
| `scope` | `text` | NOT NULL，`user/tenant` |
| `observation` | `text` | NOT NULL |
| `action` | `text` | NOT NULL |
| `result` | `text` | NOT NULL |
| `source_run_id` | `uuid` | NULL |
| `source_feedback_id` | `uuid` | NULL |
| `embedding` | `vector(1024)` | NULL；未删除时必须存在，用户删除时清空 |
| `status` | `text` | NOT NULL，`pending/active/rejected/deleted` |
| `reviewed_by` | `uuid` | NULL |
| `reviewed_at` | `timestamptz` | NULL |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `expires_at` | `timestamptz` | NOT NULL |
| `deleted_at` | `timestamptz` | NULL |

- PK：`(tenant_id, memory_id)`。
- FK：source run/feedback 分别引用对应复合 PK，使用 `ON DELETE SET NULL (source_run_id)` / `ON DELETE SET NULL (source_feedback_id)`，保留 tenant_id。
- CHECK：三段文本非空；`scope='user'` 等价于 owner 非空；tenant scope 的 active/rejected 必须有 reviewer 和 reviewed_at；未删除时 embedding 必须存在、deleted 时必须为空；删除状态与 deleted_at 一致。
- 索引：用户读取 `(tenant_id, owner_user_id, status)`；共享读取 `(tenant_id, status) WHERE scope='tenant'`；清理 `(expires_at) WHERE status IN ('pending','active')` 和 `(deleted_at) WHERE status='deleted'`。
- 首版不建 ANN；private 与 tenant shared 分两次精确查询，各 LIMIT 1..3。

### 3.6 `procedural_prompt_versions`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `prompt_key` | `text` | NOT NULL，非空 |
| `version_id` | `uuid` | NOT NULL |
| `parent_version_id` | `uuid` | NULL |
| `content` | `text` | NOT NULL，非空 |
| `content_hash` | `bytea` | NOT NULL，SHA-256 共 32 bytes |
| `status` | `text` | NOT NULL，`draft/review/approved/rejected` |
| `evidence_summary` | `jsonb` | NOT NULL DEFAULT `'{}'`，object |
| `evaluation_metrics` | `jsonb` | NOT NULL DEFAULT `'{}'`，object |
| `created_by` | `uuid` | NOT NULL |
| `approved_by` | `uuid` | NULL |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `approved_at` | `timestamptz` | NULL |

- PK：`(tenant_id, prompt_key, version_id)`。
- 自引用 FK：parent 指向同 tenant/key 的版本，`ON DELETE RESTRICT`。
- UNIQUE：`(tenant_id, prompt_key, content_hash)`，防止相同内容重复建版。
- CHECK：hash 长度 32；两个 JSONB 为 object；approved 状态必须有审批人/时间，其他状态不得伪造审批字段。
- 索引：`(tenant_id, prompt_key, created_at DESC)`。
- 内容、hash、parent、created_by、created_at 创建后不可修改。数据库通过列级 UPDATE 权限或审核函数限制；不为此编写通用审计 trigger。
- 不使用 `retired` 状态。版本是否在线由 active pointer 决定；approved 历史天然可回滚。

### 3.7 `procedural_prompt_active`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `prompt_key` | `text` | NOT NULL |
| `version_id` | `uuid` | NOT NULL |
| `generation` | `bigint` | NOT NULL DEFAULT 1，必须 > 0 |
| `activated_by` | `uuid` | NOT NULL |
| `activated_at` | `timestamptz` | NOT NULL DEFAULT now() |

- PK：`(tenant_id, prompt_key)`，天然保证唯一 active。
- FK：`(tenant_id, prompt_key, version_id) -> procedural_prompt_versions`，`ON DELETE RESTRICT`。
- `generation` 是最小乐观并发令牌；API 必须提交期望 generation。
- 不能用 FK 表达“目标必须 approved”，由唯一激活函数在同一事务内锁行并校验。

### 3.8 `memory_jobs`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `job_id` | `uuid` | NOT NULL |
| `user_id` | `uuid` | NULL；tenant 级程序任务可为空 |
| `job_type` | `text` | NOT NULL，`semantic_extract/episodic_extract/procedural_optimize` |
| `source_run_id` | `uuid` | NULL |
| `dedupe_key` | `text` | NOT NULL，非空 |
| `payload` | `jsonb` | NOT NULL DEFAULT `'{}'`，object |
| `status` | `text` | NOT NULL，`pending/running/done/failed` |
| `attempts` | `smallint` | NOT NULL DEFAULT 0，>= 0 |
| `available_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `locked_at` | `timestamptz` | NULL |
| `locked_by` | `uuid` | NULL |
| `last_error_code` | `text` | NULL，只存安全错误类型 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `expires_at` | `timestamptz` | NOT NULL |

- PK：`(tenant_id, job_id)`。
- FK：source run 使用 `ON DELETE SET NULL (source_run_id)`，保留 tenant_id。
- UNIQUE：`(tenant_id, job_type, dedupe_key)`；它同时覆盖有/无 source run 的幂等，不再增加部分唯一索引。
- CHECK：payload 是 object；running 时 lock 两列必须存在，其他状态 lock 两列必须为空；`attempts >= 0`。
- 领取索引：`(available_at, created_at) WHERE status='pending'`。这是唯一跨租户索引。
- 租户运维索引：`(tenant_id, status, updated_at)`；清理索引 `(expires_at) WHERE status IN ('done','failed')`。

### 3.9 `audit_events`

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | `uuid` | NOT NULL |
| `event_id` | `uuid` | NOT NULL |
| `actor_user_id` | `uuid` | NULL；system/worker 可为空 |
| `actor_type` | `text` | NOT NULL，`user/worker/system` |
| `action` | `text` | NOT NULL，非空 |
| `resource_type` | `text` | NOT NULL，非空 |
| `resource_id` | `text` | NOT NULL，非空 |
| `details` | `jsonb` | NOT NULL DEFAULT `'{}'`，必须为 object |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `expires_at` | `timestamptz` | NOT NULL |

- PK：`(tenant_id, event_id)`。
- CHECK：actor_type=user 时 actor_user_id 必填；details 为 object。
- 索引：`(tenant_id, created_at DESC)`；`(tenant_id, resource_type, resource_id, created_at DESC)`；`(expires_at)`。
- 只保留一个 `details`，删除 before/after 双 JSONB。details 仅含版本号、状态、计数、不可逆主体哈希等安全元数据，不复制 prompt、评论或记忆正文。
- API/worker 只有 INSERT/SELECT，无 UPDATE/DELETE；过期硬删仅允许 maintenance 函数。

## 4. RLS 与权限矩阵

所有九表 `ENABLE ROW LEVEL SECURITY` 且 `FORCE ROW LEVEL SECURITY`。表 owner 是 NOLOGIN 角色；migration、API、worker 均不是 owner，且均 `NOBYPASSRLS`。

事务开始由应用设置并在事务结束自动清除：

- `app.tenant_id`：必需 UUID；缺失或非法时 fail closed。
- `app.user_id`：用户请求必需；tenant job 可为空。
- `app.role`：`user/tenant_admin/worker`，只能来自已验证 JWT 或受控 worker 上下文。

策略矩阵中的“本人”通过 thread/run 归属链判断，不信任请求 body。

| 表 | user | tenant_admin | worker（已进入单个 job tenant context） | poll role |
|---|---|---|---|---|
| threads | 本人 SELECT/INSERT/UPDATE/DELETE | 仍仅本人；首版不提供代看 | 只读 job 对应本人 thread | 无 |
| runs | 本人 SELECT/INSERT | 同 user | 读取 job source，写摘要所需最小列 | 无 |
| semantic | 本人 SELECT/软删；正常写由 worker | 同 user | 同 tenant + job user 的 SELECT/INSERT/UPDATE | 无 |
| feedback | 本人 SELECT/INSERT | 同 user | 读取 job 对应 feedback | 无 |
| episodic | 本人 private SELECT/软删；读取同 tenant active shared | 可审核本 tenant shared；不可读其他用户 private 正文 | 仅 job user private；tenant job 仅 pending/shared | 无 |
| prompt versions | 只读 active 版本通过受控查询 | 本 tenant SELECT/创建 draft/审核函数 | procedural job 只创建 draft | 无 |
| prompt active | 只读本 tenant pointer | 仅通过 activate/rollback 函数修改 | 只读 | 无 |
| jobs | 仅 INSERT 自己允许的 semantic/episodic job；可读自身 job 状态 | 本 tenant 管理任务 | 处理已领取的单个 job | 仅 EXECUTE claim 函数 |
| audit | 无通用读取；自己的删除回执由受控接口返回 | 本 tenant SELECT | INSERT 自身动作 | 无 |

每个可 INSERT/UPDATE 的 policy 同时定义 `WITH CHECK`，阻止改变 tenant/user/scope。DELETE policy 只给用户自己的 semantic/private episodic 软删接口对应 UPDATE；普通 API 不直接获得这些表的 DELETE 权限。

### worker 跨租户领取的最小权限

不授予 worker 表级跨租户 SELECT，也不授予 `BYPASSRLS`。单独创建 `memory_job_poller` 登录角色，仅有一个 `SECURITY DEFINER` 函数的 EXECUTE 权限：

1. 函数固定 `search_path`，不接受 tenant 参数；
2. 在事务中按 `available_at, created_at` 执行 `FOR UPDATE SKIP LOCKED LIMIT 1`；
3. 原子更新为 running，递增 attempts，写入 `locked_by/locked_at`；
4. 只返回处理所需的 `tenant_id/job_id/user_id/job_type/source_run_id/payload`；
5. 函数 owner 为 NOLOGIN 专用角色，撤销 PUBLIC EXECUTE；
6. poller 取得 job 后关闭领取事务，业务处理改用普通 `memory_worker` 连接，并以该 job 的 tenant/user 执行新事务；
7. 完成/失败只能通过按 `tenant_id + job_id + locked_by` 条件更新，防止 worker 完成他人 lease。

首版不实现自动续租。worker 超时后由同一个受控函数回收超过固定 lease 的 running job；当真实任务耗时超过 lease 时再增加 heartbeat。

## 5. TTL、软删除与硬删除

建议默认值由配置传入迁移/应用，不写死为不可改约束：

| 数据 | 默认保留 | 到期动作 |
|---|---:|---|
| thread、run | 最后活动后 30 天 | 硬删 thread，run/feedback 级联 |
| feedback | 180 天，且不超过所属 run 生命周期 | 随 run 或独立硬删 |
| semantic explicit | 无自动 TTL | 用户删除先软删，24 小时内硬删 |
| semantic inferred | 90 天 | 到期软删并在 24 小时内硬删 |
| episodic private/shared | 180 天 | 到期软删并在 24 小时内硬删 |
| jobs done/failed | 30 天 | 硬删；pending/running 不因普通 TTL 丢失 |
| prompt versions/active | 无 TTL | 不自动删除；active 禁删 |
| audit | 365 天 | maintenance 硬删 |

用户记忆 DELETE 的外部语义是立即不可见：事务内把 semantic/episodic 设为 deleted、清空 embedding，并写安全 audit。maintenance 在 24 小时内硬删正文行。这样既支持审计又不让向量继续召回。

用户主体清除采用幂等顺序：阻止新请求和新 job；删除/取消 jobs；软删后硬删 semantic/episodic；删除 thread（级联 run/feedback）；写无正文删除凭证。程序 prompt 只能使用脱敏聚合证据，不能引用单个用户正文；否则主体删除时必须停用相应版本并重新审核。

备份不能承诺逐行即时擦除。开发/首版规则：备份加密，保留不超过 30 天；删除账本保留不可逆主体哈希；任何恢复必须先重放删除账本，再开放 API/worker 流量。不要把“主库已删”等同“所有历史备份已物理擦除”。

## 6. 程序版本激活、并发与回滚

只暴露数据库函数，不给 API 直接 UPDATE active 表：

1. `activate_prompt(tenant, key, target_version, expected_generation, actor)` 在调用者 RLS tenant 上下文运行；
2. `SELECT ... FOR UPDATE` 锁定 `(tenant_id, prompt_key)` pointer；首次激活用 tenant/key 级 advisory transaction lock 防止双 INSERT；
3. 校验 target 属于同 tenant/key、状态 approved、content hash 正确；
4. 校验当前 generation 等于 API 提交值；不一致返回 conflict；
5. upsert pointer，generation + 1，并在同一事务 INSERT audit；
6. commit 后应用按 tenant/key/generation 使缓存失效。

回滚调用同一函数，把 target 指向任一历史 approved 版本；不修改历史 content/status，不执行数据库 down migration。active 版本 `ON DELETE RESTRICT`，普通角色无版本 DELETE 权限。

## 7. Forward migration

迁移保持一次向前、可重复验证，不在 API 启动时偷偷执行：

1. 创建/校验 `vector` extension；创建 NOLOGIN owner、migration、API、worker、poller、maintenance 角色。
2. 创建九表：threads → prompt versions → prompt active → runs → feedback → semantic → episodic → jobs → audit。
3. 添加 FK、CHECK、UNIQUE 和上述最小 B-tree/部分索引；不建 ANN。
4. 创建固定 `search_path` 的 job claim/reclaim、prompt activate/rollback、TTL/hard-delete 函数。
5. 启用并 FORCE RLS，创建 SELECT/INSERT/UPDATE/DELETE policy；随后才授予最小表/函数权限。
6. 以 migration 角色写入 schema version 记录（可使用迁移工具自身版本表，不新增业务表）。
7. 使用 API、admin、worker、poller 四种真实连接角色执行隔离测试。
8. 部署 API/worker，但保持 memory read/write/procedural feature flags 关闭；通过 smoke 后按短期、semantic、episodic、procedural 顺序启用。

现有 Chroma、Neo4j、MinIO 数据不迁移、不删除。生产回滚只关闭 feature flags 并回滚应用镜像，保留新增表；禁止自动执行 destructive down migration。

## 8. 测试与测试环境回滚

实现至少提供以下数据库集成测试：

- 相同 thread/run/memory UUID 在两个 tenant 可并存，彼此 SELECT 为零行；
- 故意省略应用 tenant WHERE，RLS 仍隔离；缺少 `SET LOCAL` 时 fail closed；
- INSERT/UPDATE 不能把行改写到另一 tenant/user；普通用户不能读他人 private episode；
- tenant admin 不能越 tenant，且不能直接激活未 approved prompt；
- 两事务以同 generation 并发激活，恰好一个成功、一个 conflict；回滚恢复历史 approved version；
- 重复 feedback idempotency 和重复 job dedupe 不产生第二行；
- 两个 poller 并发领取不取得同一 job；poller 无法直接 SELECT 业务表；
- 软删后立即不召回且 embedding 已清空，maintenance 后正文行为零；
- 到期 thread 级联 run/feedback，但 source run 被清理不会级联删除仍在保留期内的长期记忆；
- 向量维度错误写入失败；小数据精确检索顺序正确；
- 备份恢复演练在开放流量前重放删除账本。

测试环境 rollback：先停止 API/worker，确认数据库名称是专用测试库，再按依赖逆序 drop 九表、函数、policy 和测试角色；若 vector extension 非本测试独占则不 drop。生产环境不提供同等 down 命令作为日常回滚手段。

## 9. 审批结论与实施门禁

database **有条件批准进入实现**，条件如下：

1. 实现采用本评审的显式 tenant 列和 Core API 自管表，不临时改回 prefix-only PostgresStore；
2. 首版不建 ANN，不新增 tenants/users/repository/factory/Celery/Redis；
3. worker 跨租户领取只能走受限函数，运行角色不得 BYPASSRLS；
4. prompt 激活只能走带 generation 检查的事务函数；
5. migrations、RLS、角色/网络策略属于已批准开发范围，但任何生产执行、真实密钥或数据删除仍需单独批准；
6. 通过本评审第 8 节的 RLS、并发、删除和回滚测试后，才能声明数据库门禁通过。

当前不批准的事项：生产迁移、生产删除、生产密钥/网络策略、未经审核自动激活程序记忆，以及在没有真实规模证据时添加 ANN 或额外身份表。
