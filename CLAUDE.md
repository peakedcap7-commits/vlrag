# ShoppingQnA 项目级 Claude Code 规则

## 多 Agent 体系权威
本项目多 Agent 开发规则以仓库根 `AGENTS.md` 为唯一权威,由 `tests/test_agent_policy.py` 保护。本文件不重复其内容,仅补充 Claude Code 侧的运行约定。

新任务开始时,按 `AGENTS.md`「启动时读取顺序」依次加载:
1. `AGENTS.md`;
2. `docs/agent/TASK_POLICY.md`;
3. `docs/agent/PROJECT_STATE.md`;
4. `docs/agent/TASK_BOARD.md`;
5. 与需求相关的 `docs/agent/ARCHITECTURE.md` 或 `docs/agent/DATABASE.md`;
6. 需要验收时读取 `docs/agent/ACCEPTANCE.md`。

默认测试解释器固定为:

```powershell
D:\pj\vlrag\shopping-qna\.venv\Scripts\python.exe
```

除非用户明确要求,不要使用 Anaconda base、系统 Python 或其他全局 Python 作为验收环境。

## 角色派发(Claude Code 侧)
- 本主会话即主 Agent,是唯一调度入口;用户只向主 Agent 下达指令。
- 专业 Agent 定义在 `.claude/agents/*.md`,与 `.codex/agents/*.toml` 角色对等、规则一致:
  `architect` / `backend` / `frontend` / `database` / `tester` / `reviewer` / `acceptance`。
- 派发时严格按 `AGENTS.md`「专业 Agent 委派格式」给出:目标、已批准范围、禁止范围、可修改文件、必须读取的共享记忆、验收标准、是否允许写入、返回格式。
- 同时最多调度 3 个专业 Agent;专业 Agent 不得继续派生子 Agent(各 `.claude/agents/*.md` 已显式约束,且其 tools 不含 Agent 工具)。
- 只读调查、测试和审查可并行;多个写密集任务仅在文件所有权清晰且使用独立 Worktree 时并行。

## 最小实现约束
`backend` 与 `frontend` 的 agent 定义已要求其 Read 并遵守 karpathy-guidelines(`C:/Users/Administrator/.agents/skills/karpathy-guidelines/SKILL.md`,当前开发机绝对路径,迁移机器时需调整)。主 Agent 派发后无须重复叮嘱。

## 会话桥接(claude-bridge)
主 Agent 汇总专业 Agent 结果后,按 `C:/Users/Administrator/Documents/Codex/claude-bridge/PROTOCOL.md` 写入桥接文件,供 Codex 会话只读观察。只有主 Agent 写 bridge,专业 Agent 不直接写。

## 完成定义
宣布完成前必须满足 `AGENTS.md`「完成定义」全部条件;未通过必要测试、审查和验收时不得宣布完成。

本地 commit 与远端 push 分开授权;只有用户明确说“push/推送”时才允许推送远端。

## 模型说明
本会话及派发的 subagent 当前由 `glm-5.2` 驱动;输出质量受此影响,严守 `AGENTS.md` 统一汇报格式以补偿。
