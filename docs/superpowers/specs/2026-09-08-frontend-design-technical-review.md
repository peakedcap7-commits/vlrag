# ShoppingQnA 前端设计技术评审

- 日期：2026-09-08
- 评审对象：`2026-09-08-frontend-design-and-api-contract.md`
- 评审角色：architect、database
- 状态：2026-09-11 设计复核问题已实现并进入最终验收

## 结论

方案方向可实现。新增 `frontend/`、React/Vite、Nginx 同源代理、FastAPI 图片入口和记忆事件接口的边界清晰；数据库迁移具备最小字段、约束、索引与 RLS 方案。

用户于 2026-09-09 确认：撤销新偏好并恢复被替代的旧偏好，限 7 天内且无后续变更。对应事务、版本校验和验收场景已写入方案。

## 已关闭问题

| 级别 | 原问题 | 修订结果 |
|---|---|---|
| P1 | 前端无法获得可靠改搭状态 | 后端生成、持久化并返回完整公开 `conversation_state` |
| P1 | Assistant 可读取未经归属校验的上传 key | 在进入图编排前校验白名单及 tenant/user/thread metadata |
| P1 | MinIO 内网预签名 URL 浏览器不可用 | 改为同源、无状态签名内容 token 和 JWT Blob fetch |
| P1 | 记忆确认/撤销没有落库模型 | 新增窄 `memory_events` 表、状态机、RLS、稳定游标与幂等决策 |
| P2 | Admin 无法列出待审批数据 | 增加管理员限定的情景与正向反馈运行列表接口 |
| P2 | 清理宽限期 24 小时与 7 天冲突 | 受控 maintenance 入口固定 7 天 |
| P2 | 容量淘汰依赖不存在的命中字段 | 改用现有 `confidence` 与 `updated_at` |
| P2 | 程序版本最近 20 个难以安全清理 | 首版永久保留，实际增长后再归档 |
| P2 | 缺少 multipart 与 Nginx 上传配置 | 增加 `python-multipart`、11 MiB 限制和 SPA fallback |
| P2 | MinIO 24 小时 TTL 只有文案 | `minio-init` 幂等配置 `uploads/` lifecycle |
| P2 | 内容 token 状态模型不明 | 使用无状态、用途隔离的短期签名 token，不新增存储 |

## 数据结构复核

### `semantic_memories` 修改

- 新增 `pending` 状态。
- 新增 `supersedes_memory_id` 与同租户自外键。
- 自外键使用 PostgreSQL 16 的 `ON DELETE SET NULL (supersedes_memory_id)`。
- active/pending/superseded/deleted 的 embedding、`deleted_at` 与 `expires_at` 一致性由 CHECK 约束保护。
- 冲突更新在 tenant/user 事务级 advisory lock 内执行。

### 新增 `memory_events`

- 主体字段覆盖 tenant、user、kind、status、关联记忆、摘要、可撤销时间、决策时间与过期时间。
- 采用 FORCE RLS，API 和 Worker 都受 tenant/user 上下文限制。
- `(tenant_id,user_id,created_at,event_id)` 支持稳定游标。
- 事件到语义/情景记忆使用同租户联合外键和 `ON DELETE CASCADE`。
- 用户事件不复用管理员审计表。

### 数据量控制

- active 语义记忆每用户 100 条。
- pending 语义记忆每用户 20 条、7 天自动过期。
- superseded/deleted 记录 7 天后物理清理。
- 情景记忆保留 180 天；任务保留 30 天。
- maintenance 使用独立登录身份和单一受控函数；清理幂等，advisory lock 只负责防并发。

## 已确认选择（2026-09-09）

### 冲突记忆的撤销语义

采用撤销新偏好并恢复旧偏好。恢复窗口从激活时间起算 7 天；旧偏好已过期或清理、发生后续变更时拒绝恢复。

- 增加语义记忆 revision 和事件 expected_memory_revision，防止旧撤销事件覆盖后续决定。
- 在事务外生成旧值向量，锁内重新校验快照、归属、期限和版本；同一事务更新新旧状态、事件和审计。
- 重复同一撤销幂等；不兼容决策返回 409；跨用户按 404 处理。
- “忘掉此偏好”只删除，不恢复历史。
- 本次是设计语义确认，不代表已经实施或验证数据库迁移。

## 评审门禁

- P0：0。
- 已关闭 P1：5（含最后的撤销语义）。
- 本次评审范围内未关闭 P0/P1：0。
- 架构结论：architect 增量复核批准。
- 数据库结论：database 增量复核批准数据库设计；迁移实现需验证 CHECK、revision 条件更新、RLS 及幂等。
- 实现已落入 `frontend/`、`src/assets.py`、`src/memory_events.py`、API、Worker、数据库迁移与 Compose；字段约束、RLS、revision、确认/撤销并发语义由自动化测试覆盖。
