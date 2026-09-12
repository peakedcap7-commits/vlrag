# ShoppingQnA Agent 任务看板

- 最后更新时间：2026-09-11
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：有效

## 当前任务

- 任务：React 对话工作台、图片鉴权、记忆确认/撤销与 Docker 一键开发部署。
- 当前阶段：已完成
- 实现分支已合并到 `main`；前端、API、记忆与数据库改动不再由临时 Worktree 持有。

## 已完成

- React/Vite/Nginx 前端：本地会话、JWT Token Gate、主题、响应式对话与消息内穿搭画布。
- FastAPI：图片上传、归属校验、短期内容令牌、公开会话状态、记忆事件与管理员列表。
- LangMem Worker：已有记忆更新、推断/敏感确认、7 日撤销恢复、明确遗忘不恢复。
- PostgreSQL：事件表、revision、自引用替代链、RLS、容量限制和独立 maintenance 身份。
- Docker Compose：前端、API、Worker、PostgreSQL、MinIO、Neo4j、迁移与初始化一条命令启动。
- 方案与字段技术评审：`docs/superpowers/specs/2026-09-08-frontend-design-and-api-contract.md`、`2026-09-08-frontend-design-technical-review.md`。

## 验收门禁

- Python 单元与契约测试。
- React 单元测试、TypeScript/Vite 生产构建和无头浏览器桌面/移动 smoke。
- PostgreSQL 真实迁移、RLS、并发确认/撤销与维护权限集成测试。
- Compose 配置解析和镜像构建；完整模型数据初始化仍需有效 `DASHSCOPE_API_KEY`。

## 仍属产品限制

- M4 场景整套穿搭生成暂缓。
- 仓库只包含三件合成演示商品；完整 Polyvore 索引不是 Git 资产。
- 本地 JWT 仅供开发，生产环境必须接正式 OIDC/JWT。
