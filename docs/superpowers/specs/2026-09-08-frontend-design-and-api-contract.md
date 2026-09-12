# ShoppingQnA 前端设计与接口契约草案

- 日期：2026-09-08
- 状态：2026-09-11 已实现，进入最终验收
- 2026-09-09 修订：用户已确认撤销冲突更新时恢复旧偏好，限 7 天内且无后续变更。
- 范围：开发环境前端、图片上传、记忆提示与 Docker 集成
- 非目标：生产认证、M4 场景穿搭、真人穿搭生成、SSR、PWA

## 1. 已确认的产品决策

| 项目 | 决策 |
|---|---|
| 前端技术 | React + TypeScript + Vite |
| 主布局 | 左侧会话栏，中央对话流 |
| 结果位置 | 穿搭结果直接显示在对话内容中 |
| 图片输入 | 本地上传 + 演示商品选择器 |
| 视觉方向 | 时尚编辑部：暖白、墨黑、酒红、大图与留白 |
| 结果视觉 | 杂志式平铺搭配板，不生成真人合成图 |
| 调整方式 | 自然语言 + “保留这件 / 换一件 / 不喜欢”快捷操作 |
| 记忆交互 | 平衡型：明确偏好轻提示可撤销；推断或敏感内容先确认 |
| 普通用户记忆入口 | 不设置记忆管理页，通过日常对话完成记忆操作 |
| 管理员入口 | 独立 `/admin` 页面 |
| JWT | 首次进入粘贴，仅存 `sessionStorage` |
| 主题 | 浅色 / 深色 / 跟随系统 |
| 等待反馈 | 编辑部式阶段文案轮播，不增加 SSE |
| 会话历史 | 浏览器本地保存标题、消息和 `thread_id` |
| 上传链路 | 浏览器 → FastAPI → MinIO |
| 响应式 | 桌面与移动端完整可用，移动端侧栏改抽屉 |
| 记忆清理 | 复用现有 Worker，以独立 maintenance 身份定时清理 |

## 2. 当前事实与缺口

### 已有能力

- FastAPI 已提供开发 JWT、多租户身份、推荐、统一 Assistant、反馈、记忆查询与管理员提示词接口。
- Assistant 已支持单品推荐、多图搭配判断和对话式改搭。
- Memory Worker 已支持语义提取、正向反馈情景提取与程序提示词优化。
- PostgreSQL 已有 RLS、任务租约、重试和清理数据库函数。
- Docker Compose 已能启动 API、Worker、PostgreSQL、Neo4j 和 MinIO。

### 实现前必须补齐

1. 浏览器图片上传接口。
2. 商品及上传图片的同源鉴权内容接口。
3. 异步记忆事件的查询、确认、拒绝和撤销接口。
4. 语义记忆冲突处理：向 LangMem 传入已有记忆并启用更新建议。
5. Memory Worker 定时调用现有清理函数。
6. 前端容器与同源 `/api` 反向代理。
7. 由后端生成、持久化并返回公开 `conversation_state`，供后续改搭使用。

## 3. 信息架构

### `/` 普通用户工作台

```text
应用外壳
├── 左侧会话栏
│   ├── 新建对话
│   ├── 本地会话列表
│   ├── 服务状态
│   └── 主题与退出开发身份
└── 中央对话区
    ├── 空状态与示例问题
    ├── 消息流
    │   ├── 文本消息
    │   ├── 用户图片组
    │   ├── 穿搭画布
    │   ├── 搭配建议
    │   └── 记忆提示/确认
    └── 固定输入区
        ├── 图片上传
        ├── 演示商品选择器
        ├── 文本输入
        └── 发送
```

### `/admin` 租户管理员页

- 使用同一 JWT，不提供独立登录或发 Token 接口。
- 非 `tenant_admin` 显示 403，不渲染管理数据。
- 功能仅包括：情景记忆审批、程序版本列表、优化、审批、激活与回滚。
- 不提供数据库浏览器、任意 SQL、租户切换或用户模拟功能。

### Token Gate

- 未设置 Token 时，任何业务页面先显示 Token Gate。
- 前端可无验签解析 JWT，仅用于展示租户、用户、角色和到期时间；服务端验证始终为准。
- Token 仅写入 `sessionStorage`，不写 `localStorage`、IndexedDB、URL 或日志；显式退出必须立即清除。浏览器会话恢复行为由浏览器决定，不承诺进程异常退出后绝对消失。
- 收到 401 时清除 Token 并回到 Token Gate。

## 4. 核心用户流程

### 新建并完成一次穿搭咨询

1. 用户粘贴开发 JWT。
2. 前端生成 UUID `thread_id`，在浏览器本地创建会话。
3. 用户上传 2～4 张图片，或从演示商品中选择。
4. 前端先调用上传接口，获得 `image_key` 与同源临时内容地址。
5. 前端调用 `POST /assistant/message`。
6. 等待时循环显示“分析单品 / 检索搭配 / 整理建议”。这些是等待文案，不伪装成真实后端进度。
7. 响应以穿搭画布和建议卡直接插入消息流。
8. 后端在响应中返回更新后的公开 `conversation_state`；前端原样保存并在下一轮回传。
9. 用户可以继续自然语言改搭，或点击快捷动作生成明确的新消息。

### 快捷操作语义

| 操作 | 前端行为 | 后端输入 |
|---|---|---|
| 保留这件 | 基于后端返回状态标记当前单品为锁定，并发送自然语言确认 | `conversation_state.locked_item_ids` |
| 换一件 | 打开一句可编辑的替换要求 | 普通 `message` + 当前状态 |
| 不喜欢 | 发送负向反馈，同时生成明确的排除请求 | `/assistant/feedback` + `message` |
| 喜欢/收藏 | 发送正向反馈 | `/assistant/feedback` |

快捷操作不得在前端复制后端约束解析逻辑。前端只组装用户可见动作和已有结构化状态。
首次分析与每次改搭成功后，后端必须生成新的完整公开状态并持久化；前端不得从展示文本或图片地址反推商品 ID。

### 平衡型记忆交互

| 类型 | 处理 |
|---|---|
| 当前对话临时约束 | 静默保存在短期状态，不进入长期记忆 |
| 用户明确表达稳定偏好 | 保存后显示轻提示，可在 7 天内撤销 |
| Agent 推断的偏好 | 保存为待确认，用户确认后激活 |
| 尺码、身体特征、预算等敏感内容 | 必须确认；默认不激活 |
| 收藏、采纳、购买等正向结果 | 形成用户级情景记忆并轻提示 |
| 程序记忆 | 仅管理员审批后激活 |

普通用户通过“记住这个”“忘掉这个”和提示卡按钮完成操作，不设置独立记忆管理页。

## 5. 穿搭画布

### 桌面端

- 画布宽度随消息容器变化，最大 760px，推荐宽高比 4:3。
- 主单品占视觉面积约 40%，其余单品围绕主单品形成非对称平衡。
- 使用 CSS Grid 定位，不进行图片像素合成。
- 图片使用 `object-fit: contain`；缺图时显示带品类名称的占位块。
- 画布下方依次显示结论、摘要、优点、问题和建议。
- 单品获得键盘焦点时显示名称及快捷操作。

### 移动端

- 画布宽度占满内容区，最小高度 360px。
- 单品保持平铺关系，不降级为横向滚动列表。
- 快捷操作进入单品底部操作条，触控目标不小于 44px。

## 6. 视觉系统

### 字体

```css
--font-display: "Songti SC", "STSong", Georgia, serif;
--font-ui: system-ui, "PingFang SC", "Microsoft YaHei", sans-serif;
--font-mono: ui-monospace, "Cascadia Code", monospace;
```

不下载 Web Font，避免增加首屏阻塞和外部依赖。

### 浅色主题

```css
--bg: #f5f1e8;
--surface: #fffdf8;
--surface-muted: #ece6da;
--text: #1b1917;
--text-muted: #68615a;
--border: #d8d0c3;
--accent: #8e2c3a;
--accent-contrast: #ffffff;
--success: #526854;
--warning: #9a641d;
--danger: #a33232;
```

### 深色主题

```css
--bg: #171514;
--surface: #211e1c;
--surface-muted: #2b2724;
--text: #f5f1e8;
--text-muted: #beb5aa;
--border: #443d38;
--accent: #d77b88;
--accent-contrast: #171514;
--success: #91aa93;
--warning: #d3a15d;
--danger: #e47f7f;
```

### 尺度

- 基础间距：4px。
- 间距序列：4、8、12、16、24、32、48、64。
- 正文：16px/1.65；辅助文字：14px/1.5；页面标题：32～44px。
- 内容圆角：12px；操作控件圆角：999px 或 8px；避免所有容器都使用卡片阴影。
- 动画：150～240ms；遵循 `prefers-reduced-motion`。

### 无障碍基线

- 正文对比度至少 4.5:1，大文字和非文字控件至少 3:1。
- 所有功能可通过键盘完成，提供清晰的 `:focus-visible`。
- 图片包含可读替代文本；纯装饰图使用空 `alt`。
- 消息发送、错误和记忆确认使用 `aria-live`，但等待文案不持续打断读屏。
- 支持浏览器 200% 文本缩放。

## 7. 前端技术边界

### 建议目录

```text
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── src/
    ├── main.tsx
    ├── app.tsx
    ├── api.ts
    ├── types.ts
    ├── storage.ts
    ├── styles.css
    └── components/
        ├── auth/
        ├── chat/
        ├── outfit/
        └── admin/
```

约束：

- 不引入状态管理框架，使用 React state/context。
- 不引入 UI 组件库，使用语义 HTML 和项目 CSS。
- 图片上传新增现有 FastAPI 所需的 `python-multipart`，不增加另一套上传框架。
- 不在前端实现 JWT 签名验证、租户授权或 MinIO 凭据处理。
- API 类型集中在 `types.ts`，请求集中在 `api.ts`。
- 本地会话使用一个带版本号的 `localStorage` 文档，损坏时安全重置。

### 本地会话结构

```ts
type LocalConversation = {
  version: 1;
  threadId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: LocalMessage[];
};
```

- 只保存用户可见消息和展示所需的公开结果。
- 不保存 JWT、内部图证据、模型提示词、原始向量或预签名 URL。
- 会话支持新建、重命名和删除；这是浏览器数据操作，不修改后端长期记忆。

## 8. 接口契约

### 8.1 复用现有接口

| 接口 | 前端用途 |
|---|---|
| `GET /health` | API 存活状态 |
| `GET /health/ready` | 模型、数据和 PostgreSQL 就绪状态 |
| `POST /warmup` | 管理员预热 |
| `POST /assistant/message` | 推荐、搭配分析和改搭 |
| `POST /assistant/feedback` | 喜欢、收藏、购买、评分和负反馈 |
| `/admin/prompts/...` | 程序记忆版本工作流 |
| `POST /admin/episodes/{memory_id}/approve` | 租户级情景审批 |

`GET /assistant/memories` 与 `DELETE /assistant/memories/{id}` 保留兼容，但普通用户 UI 不直接暴露列表页。

`POST /assistant/message` 的成功响应新增顶层 `conversation_state`。该字段由后端生成并在同一事务中持久化，不能由前端从公开结果推导：

```json
{
  "thread_id": "33333333-3333-3333-3333-333333333333",
  "run_id": "66666666-6666-6666-6666-666666666666",
  "intent": "outfit_analyze",
  "status": "ok",
  "result": {},
  "message": "整体搭配协调。",
  "conversation_state": {
    "anchor_item_id": "199614803",
    "candidate_item_ids": ["211259367"],
    "selected_item_ids": ["211259367"],
    "locked_item_ids": [],
    "excluded_item_ids": [],
    "item_metadata": [],
    "last_intent": "outfit_analyze"
  }
}
```

首次分析和后续改搭成功都返回完整状态；非成功响应返回当前已持久化状态或 `null`。前端只保存并原样回传。

### 8.2 新增：上传图片

```http
POST /assets/images
Authorization: Bearer <jwt>
Content-Type: multipart/form-data

thread_id=<uuid>
file=<jpeg|png|webp>
```

约束：

- 单文件最大 10 MiB；解码后最大 20 MP；每次只上传一张。
- 服务端验证真实图片格式并重新编码，不能仅信任扩展名和 MIME。
- 对象写入 `uploads/{thread_id}/{image_id}.jpg`，TTL 为 24 小时。
- MinIO metadata 写入 tenant/user/thread 标识，读取时重新校验。

```json
{
  "image_key": "uploads/33333333-3333-3333-3333-333333333333/44444444-4444-4444-4444-444444444444.jpg",
  "content_url": "/api/assets/content/<opaque-token>",
  "expires_at": "2026-09-08T12:15:00Z"
}
```

在 `/assistant/message` 读取任何 `image_keys` 之前，服务端必须执行同样的授权校验：只允许登录用户读取商品白名单前缀；`uploads/` 对象的 tenant/user/thread metadata 必须与 JWT 和请求 `thread_id` 一致。不能仅在展示接口检查。

### 8.3 新增：批量获取同源内容地址

```http
POST /assets/urls
Authorization: Bearer <jwt>
Content-Type: application/json
```

```json
{
  "keys": ["polyvore/items/199614803.jpg"]
}
```

- 每次最多 20 个 key。
- 商品公共前缀允许登录用户读取；`uploads/` 必须校验对象 metadata 与当前身份。
- 商品白名单前缀固定为 `polyvore/items/` 和 `demo/items/`；其他前缀默认拒绝。
- 返回 URL 有效期建议 15 分钟，前端不得持久化。

```json
{
  "items": [
    {
      "key": "polyvore/items/199614803.jpg",
      "content_url": "/api/assets/content/<opaque-token>",
      "expires_at": "2026-09-08T12:15:00Z"
    }
  ]
}
```

内容地址使用无状态短期签名 token。签名密钥由 `DEV_JWT_SECRET` 通过固定用途标签 `asset-content-v1` 派生；token 至少包含 tenant、user、key 和 exp，不新增 token 表或缓存：

```http
GET /assets/content/{token}
Authorization: Bearer <jwt>
```

- 前端使用带 JWT 的 `fetch` 获取 Blob，再创建仅存于内存的 Object URL。
- API 验证 token、tenant/user、对象前缀和上传 metadata 后，从 MinIO 流式返回内容。
- 不向浏览器返回基于 `minio:9000` 内网地址生成的预签名 URL。
- Object URL 和内容 token 均不得写入 `localStorage`。

演示商品选择器首版静态声明 `src/bootstrap.py` 中三个稳定 demo ID 与 `demo/items/{item_id}.jpg`，不为三条固定数据新增 catalog API；演示数据变化时同步更新前端清单。

### 8.4 新增：异步记忆事件

由于 Memory Worker 在 Assistant 响应之后异步运行，首版采用低频轮询，不引入 SSE。

```http
GET /assistant/memory-events?after=<cursor>&limit=20
Authorization: Bearer <jwt>
```

```json
{
  "cursor": "opaque-cursor",
  "events": [
    {
      "event_id": "55555555-5555-5555-5555-555555555555",
      "kind": "semantic_saved",
      "summary": "偏爱深色系上衣",
      "requires_confirmation": false,
      "reversible_until": "2026-09-15T12:00:00Z",
      "created_at": "2026-09-08T12:00:00Z"
    }
  ]
}
```

`kind` 固定为：

- `semantic_saved`
- `semantic_confirmation_required`
- `episodic_saved`

```http
POST /assistant/memory-events/{event_id}/decision
Authorization: Bearer <jwt>
Content-Type: application/json
```

```json
{
  "action": "confirm"
}
```

`action` 固定为 `confirm | reject | undo`。服务端校验事件属于当前 tenant/user，并保证幂等；前端不得直接提交 `memory_id` 修改任意记录。

稳定游标基于 `(created_at, event_id)` 编码为不透明字符串；重复同一 decision 返回当前状态，不重复执行变更；不兼容的决策返回 409。候选允许 `open → confirmed → undone`，自动保存事件允许 `open → undone`；拒绝和过期不可再确认。

### 8.5 新增：管理员只读列表

独立 `/admin` 页面需要以下最小列表接口，否则现有审批接口只有已知 ID 时才能调用：

```http
GET /admin/episodes?status=pending&cursor=<cursor>&limit=20
GET /admin/runs?feedback=positive&cursor=<cursor>&limit=20
Authorization: Bearer <tenant-admin-jwt>
```

- 两个接口都只允许当前租户管理员访问。
- 游标使用稳定的时间与 UUID 组合，不提供跨租户筛选参数。
- 返回内容只包含审批或选择优化证据所需的用户态摘要和 ID。

## 9. LangMem 冲突与清理

### 冲突处理

1. Worker 在语义提取前读取当前用户相关的有效语义记忆。
2. 将候选作为 `existing` 传入 LangMem，并启用 `enable_updates=True`。
3. 保持 `enable_deletes=False`，LangMem 只提出插入或更新建议。
4. 应用层重新验证维度、敏感信息、身份和明确程度。
5. 明确反转时激活新记忆，将旧记忆标记为 `superseded` 并写审计事件。
6. 推断或敏感内容进入待确认状态，确认前不参与召回。

LangMem 不拥有 tenant/user 参数，也不能直接切换 RLS 上下文。

LangMem 返回的 `ExtractedMemory.id` 必须保留。应用层只接受本次作为 `existing` 输入的旧 ID；任何新增记忆 ID 仍由服务端生成。冲突落库在按 `tenant_id + user_id` 获取的事务级 advisory lock 内完成，避免并发 Worker 同时激活相反偏好。

### 已确认：撤销更新与遗忘

- `undo` 恢复本次更新前的旧偏好；纯新增没有旧值时仅撤销新记忆。
- 7 天从更新实际激活时开始计算；待确认候选在确认之前不得使旧偏好失效。
- 新版本必须仍有效、版本号与事件一致，旧版本必须仍为本次更新所替代。任何后续更新、遗忘、淘汰或撤销再恢复都改变版本号，旧事件不得覆盖后来的决定。
- 先读取旧值快照，在事务外生成恢复向量，再在 tenant/user 事务锁内重新校验事件、版本号、归属和数据库时间期限。向量生成失败不改状态；重验失败返回 409。
- 同一事务完成：新版本标记 deleted 并清除向量、旧版本恢复 active 并写回向量及递增版本号、事件标记 undone、写审计。不得恢复其他租户或用户的记录。
- 恢复保留旧偏好原有效期；旧记录已过期或被清理时拒绝恢复。清理不得提前删除仍处于有效撤销窗口中的旧版本。
- 重复成功撤销返回原结果；冲突决策返回 409；不存在或不属于当前用户返回 404；到期返回 409 和 `undo_expired`。
- “忘掉此偏好”使用独立删除语义，不恢复历史，并使对应未结束的确认/撤销失效；指代不清时先询问用户。
- 验收覆盖 A→B 后撤销恢复 A、A→B→C 后禁止撤销 B、B 被替代后又恢复仍不可复用旧事件、并发幂等、7 天边界、清理竞态、向量失败和跨用户访问。

### 最小数据库迁移

`memory.semantic_memories`：

- 增加 `supersedes_memory_id uuid NULL`。
- 增加 `revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0)`，每次状态或内容变更递增。
- 增加 `(tenant_id, supersedes_memory_id)` 同租户自外键，并使用 PostgreSQL 16 的 `ON DELETE SET NULL (supersedes_memory_id)`，不得尝试将非空 `tenant_id` 置空。
- `status` 增加 `pending`。
- `active` 必须有 embedding 且无 `deleted_at`。
- `pending` 必须无 embedding、无 `deleted_at`，并设置不超过 7 天的 `expires_at`。
- `superseded/deleted` 必须无 embedding 且有 `deleted_at`。

新增 `memory.memory_events`：

| 字段 | 类型 | 约束 |
|---|---|---|
| `tenant_id` | uuid | 联合主键、RLS 租户边界 |
| `event_id` | uuid | 联合主键 |
| `user_id` | uuid | 必填、RLS 用户边界 |
| `kind` | text | `semantic_saved/semantic_confirmation_required/episodic_saved` |
| `status` | text | `open/confirmed/rejected/undone/expired` |
| `semantic_memory_id` | uuid | 可空、同租户外键 |
| `expected_memory_revision` | bigint | 语义事件必填且大于零；确认激活时原子更新 |
| `episodic_memory_id` | uuid | 可空、同租户外键 |
| `summary` | text | 必填、仅用户可见摘要 |
| `reversible_until` | timestamptz | 可空 |
| `decided_at` | timestamptz | 可空 |
| `created_at` | timestamptz | 必填 |
| `expires_at` | timestamptz | 必填 |

- 按事件 kind 约束两个 memory 外键恰有一个非空。
- 两个记忆外键使用同租户联合外键并 `ON DELETE CASCADE`，保证物理清理不会留下悬空事件。
- FORCE RLS：API 仅能读写当前 tenant/user；Worker 仅能为当前 job tenant/user 插入。
- 索引 `(tenant_id,user_id,created_at,event_id)`、`(expires_at)`，以及 open 事件部分索引。
- 不复用 `audit_events` 承载用户事件；审计与用户交互事件保持不同权限边界。

### 容量与保留

| 数据 | 策略 |
|---|---|
| 短期会话 | 30 天 |
| 用户有效语义记忆 | 每用户最多 100 条；超过后优先淘汰低置信度且最久未更新记录 |
| 待确认语义记忆 | 每用户最多 20 条，7 天未确认自动过期 |
| 被替代/撤销语义记忆 | 7 天后物理删除 |
| 情景记忆 | 180 天 |
| 已完成或失败任务 | 30 天后删除 |
| 程序记忆版本 | 首版永久保留以维持审计链；出现实际增长问题后再设计归档 |

### 定时维护

- 继续使用现有 `memory-worker` 容器，不新增常驻服务。
- 增加独立 `MEMORY_MAINTENANCE_DATABASE_URL`，不能复用 API、poller 或 worker 凭据。
- 每个 Worker 每日尝试一次幂等清理；重启后允许在同一天重复尝试。
- 使用数据库 advisory lock 防止并发执行，但不为“严格每日一次”新增执行账本。
- 新增受控 `run_memory_maintenance()` 数据库函数，内部调用标记和清理逻辑并固定 7 天宽限期；maintenance 角色只获得该入口的 EXECUTE 权限。
- 清理失败只记录并延后重试，不阻止正常记忆任务。
- 清理范围包括过期 pending、`deleted/superseded` 语义记忆、过期 memory events、情景记忆和完成任务。

## 10. Docker 与网络

```text
Browser :3000
    │
    ▼
frontend (Nginx)
    ├── /        → React 静态文件
    └── /api/*   → api:8000/*
                       ├── PostgreSQL
                       ├── MinIO
                       ├── Neo4j
                       └── DashScope
```

- `frontend` 使用 Node 构建阶段和 Nginx 运行阶段。
- 浏览器只访问前端同源 `/api`，开发部署不增加 CORS 配置。
- Nginx 对 `/api/` 明确去除前缀后代理到 `api:8000`，并设置 `client_max_body_size 11m`。
- SPA 路由使用 `try_files $uri /index.html`，保证直接刷新 `/admin` 可用。
- Compose 对外暴露前端端口；API 端口可继续保留用于 Swagger 调试。
- `docker compose up --build` 仍是唯一完整启动命令。
- 前端健康检查使用静态 `/healthz`，不能把 API 未就绪误报为前端容器故障。
- `minio-init` 幂等配置生命周期规则，仅删除 `uploads/` 前缀中超过 24 小时的对象；不得影响 `polyvore/items/`。

## 11. 状态与错误设计

| 状态 | 用户表现 |
|---|---|
| API 不可达 | 页面级提示，保留本地输入并提供重试 |
| API 存活但数据未就绪 | 显示预热说明；管理员可执行预热 |
| JWT 缺失或失效 | 清除会话 Token，返回 Token Gate |
| 上传失败 | 单张图片内联错误，可独立重试 |
| Assistant 超时 | 保留用户消息和图片，不插入虚假回答 |
| 不支持的意图 | 直接展示后端 `message`，不伪装成功 |
| 记忆事件延迟 | 不阻塞聊天；事件到达后显示提示 |
| 内容 token 过期 | 自动重新请求一次，仍失败则显示占位图 |

## 12. 验收标准

### 普通用户

- 能粘贴有效 JWT 并进入应用；刷新后当前标签页仍有效；显式退出立即清除，且 Token 不写入持久存储。
- 能新建、切换、重命名和删除本地会话。
- 能上传 2～4 张图片或选择演示商品并发送穿搭请求。
- 能在消息流中看到平铺搭配板和用户态建议。
- 能通过自然语言和快捷操作继续改搭。
- 能收到记忆轻提示、确认提示并执行撤销/确认/拒绝。
- 不能看到其他租户或用户的上传图片、记忆事件或会话状态。

### 管理员

- `/admin` 对普通用户返回无权限状态。
- 管理员能完成程序版本优化、审批、激活、回滚和情景审批。
- 所有管理员操作继续由服务端 JWT 与数据库策略授权。

### 质量

- 360px、768px、1280px 三档布局可用。
- 键盘可完成 Token 输入、会话切换、上传、发送、画布操作和管理审批。
- 支持浅色、深色和系统主题，刷新后保留非敏感主题偏好。
- `prefers-reduced-motion` 下停止非必要轮播动画。
- `docker compose up --build` 可启动完整开发环境。

## 13. 实施顺序

1. 用户批准本草案及新增顶级 `frontend/` 目录。
2. 冻结图片与记忆事件 Pydantic schema。
3. 实现并测试图片上传、URL 和记忆事件接口。
4. 实现 LangMem 更新建议、确认状态及维护定时器。
5. 建立 React/Vite 外壳、Token Gate、主题和本地会话。
6. 接入对话、上传、演示商品、搭配画布和快捷操作。
7. 实现独立 `/admin` 页面。
8. 集成 Nginx 与 Compose。
9. 执行前端、后端、Docker、无障碍和跨租户验收。

## 14. 待评审事项

- 新增 `frontend/` 顶级目录是否符合模块边界。
- `/assets/images`、`/assets/urls`、`/assets/content/{token}` 是否是满足前端的最小图片契约。
- 记忆事件轮询是否优于当前阶段引入 SSE。
- LangMem 更新建议与应用层软删除的职责边界是否明确。
- maintenance 凭据、advisory lock 与现有 Worker 复用是否保持最小权限。
- 浏览器本地会话与后端短期状态之间是否存在不可接受的一致性风险。
- 冲突撤销已确定：7 天内恢复旧偏好，存在后续变更则拒绝；复核原子性、版本校验及清理配合。
