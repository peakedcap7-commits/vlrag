# ShoppingQnA 多 Agent 开发体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在 ShoppingQnA 项目中建立一个可观察、可审查、按需调度并支持 Worktree 隔离的主 Agent + 七个专业 Agent 开发体系。

**Architecture:** 根任务通过 AGENTS.md 承担主 Agent，七个项目级 TOML 文件定义专业 Agent。Git 和少量 Markdown 文件承载跨 Agent、跨会话的权威记忆；只读角色共享集成视图，前后端等并行写任务使用临时 Worktree。

**Tech Stack:** Codex CLI 0.144.1、项目级 Codex TOML 配置、Git Worktree、Markdown、Python 3.11+ 标准库 unittest 与 tomllib。

---

## 范围与文件映射

本计划只建立多 Agent 开发基础设施，不修改 ShoppingQnA 业务逻辑。

**修改：**

- .gitignore：补充测试缓存和文档渲染产物忽略规则。

**创建：**

- .codex/config.toml：限制 Agent 并发、派生深度和中断记录。
- .codex/agents/architect.toml：架构边界检查和获批结构调整。
- .codex/agents/backend.toml：最小范围后端实现。
- .codex/agents/frontend.toml：最小范围前端实现。
- .codex/agents/database.toml：实用优先的数据结构和迁移。
- .codex/agents/tester.toml：测试编写与验证。
- .codex/agents/reviewer.toml：只读代码审查。
- .codex/agents/acceptance.toml：只读用户验收。
- AGENTS.md：主 Agent 调度、审批、共享记忆和完成规则。
- docs/agent/PROJECT_STATE.md：当前项目事实。
- docs/agent/ARCHITECTURE.md：模块边界和依赖方向。
- docs/agent/DATABASE.md：当前存储事实和变更规则。
- docs/agent/DECISIONS.md：已批准技术决策。
- docs/agent/TASK_BOARD.md：当前任务和文件所有权。
- docs/agent/ACCEPTANCE.md：多 Agent 体系验收标准。
- tests/test_codex_global_config.py：全局 Agent 配置测试。
- tests/test_custom_agents.py：七个专业 Agent 配置测试。
- tests/test_agent_policy.py：主 Agent 项目规则测试。
- tests/test_agent_memory.py：共享记忆文档测试。

### Task 1：建立可回滚的项目 Git 基线

**Files:**

- Modify: .gitignore
- Track: .env.example
- Track: pyproject.toml
- Track: run_pipeline.py
- Track: _build_ai_shopping_plan_doc.py
- Track: _build_ai_shopping_plan_doc_v2.py
- Track: src/
- Track: tests/
- Track: docs/

- [ ] **Step 1：确认敏感文件和生成数据仍然被忽略**

Run:

~~~powershell
git check-ignore -v .env chroma_data/chroma.sqlite3 data/processed/products_enhanced.json
~~~

Expected：三条路径均显示由 .gitignore 命中。

- [ ] **Step 2：补充本地产物忽略规则**

将 .gitignore 完整调整为：

~~~gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
.pytest_cache/

# 环境变量
.env

# Chroma 向量库
chroma_data/

# 数据
data/raw/
data/processed/

# 文档渲染产物
_docx_render/

# Notebooks
.ipynb_checkpoints/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
~~~

- [ ] **Step 3：验证忽略规则**

Run:

~~~powershell
git check-ignore -v .env chroma_data/chroma.sqlite3 data/processed/products_enhanced.json .pytest_cache _docx_render
~~~

Expected：六条路径全部被忽略。

- [ ] **Step 4：验证现有 Python 文件至少能够编译**

Run:

~~~powershell
python -m compileall -q src tests run_pipeline.py
~~~

Expected：退出码为 0，无语法错误。现有联网测试暂不作为基线门禁，因为当前环境尚未安装全部项目依赖。

- [ ] **Step 5：确认示例环境文件不包含真实 DashScope 密钥**

Run:

~~~powershell
$example = Get-Content -Raw -Encoding utf8 .env.example
$containsRealKey = $example -match "(?m)=\s*sk-[A-Za-z0-9_-]{12,}\s*$" -and $example -notmatch "(?m)=\s*sk-(xxx|example|your-key)\s*$"

if ($containsRealKey) {
    throw ".env.example 疑似包含真实密钥"
}
~~~

Expected：退出码为 0，不输出密钥内容。

- [ ] **Step 6：暂存项目基线并检查没有密钥或本地数据**

Run:

~~~powershell
git add .gitignore .env.example pyproject.toml run_pipeline.py _build_ai_shopping_plan_doc.py _build_ai_shopping_plan_doc_v2.py src tests docs
git status --short
~~~

Expected：暂存列表不包含 .env、chroma_data/、data/processed/、.pytest_cache/ 或 _docx_render/。

- [ ] **Step 7：提交项目基线**

~~~powershell
git commit -m "chore: establish project baseline"
~~~

Expected：提交成功，现有源代码和测试具备可回滚基线。

### Task 2：配置主 Agent 的全局并发边界

**Files:**

- Create: tests/test_codex_global_config.py
- Create: .codex/config.toml

- [ ] **Step 1：编写失败测试**

创建 tests/test_codex_global_config.py：

~~~python
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".codex" / "config.toml"


class TestCodexGlobalConfig(unittest.TestCase):
    def test_agent_limits_are_safe(self):
        self.assertTrue(CONFIG_PATH.is_file(), "缺少 .codex/config.toml")

        with CONFIG_PATH.open("rb") as file:
            config = tomllib.load(file)

        self.assertEqual(config["agents"]["max_threads"], 4)
        self.assertEqual(config["agents"]["max_depth"], 1)
        self.assertTrue(config["agents"]["interrupt_message"])


if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2：运行测试并确认失败**

Run:

~~~powershell
python -m unittest tests/test_codex_global_config.py -v
~~~

Expected：FAIL，提示“缺少 .codex/config.toml”。

- [ ] **Step 3：创建最小全局配置**

创建 .codex/config.toml：

~~~toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
~~~

- [ ] **Step 4：运行测试并确认通过**

Run:

~~~powershell
python -m unittest tests/test_codex_global_config.py -v
~~~

Expected：1 个测试通过。

- [ ] **Step 5：让本机 Codex 严格解析配置**

Run:

~~~powershell
$json = codex --strict-config -C . doctor --json 2>$null
$report = $json | ConvertFrom-Json
$configCheck = $report.checks.'config.load'
if ($configCheck.status -ne 'ok' -or $configCheck.details.'config.toml parse' -ne 'ok') {
    throw "Codex 项目配置严格解析失败"
}
Write-Output "Codex 项目配置解析通过"
~~~

Expected：输出“Codex 项目配置解析通过”；只有 `config.load` 和 `config.toml parse` 均为 `ok` 时通过。

- [ ] **Step 6：提交全局配置**

~~~powershell
git add .codex/config.toml tests/test_codex_global_config.py
git commit -m "chore: configure codex agent limits"
~~~

### Task 3：定义七个专业 Agent

**Files:**

- Create: tests/test_custom_agents.py
- Create: .codex/agents/architect.toml
- Create: .codex/agents/backend.toml
- Create: .codex/agents/frontend.toml
- Create: .codex/agents/database.toml
- Create: .codex/agents/tester.toml
- Create: .codex/agents/reviewer.toml
- Create: .codex/agents/acceptance.toml

- [ ] **Step 1：编写专业 Agent 配置测试**

创建 tests/test_custom_agents.py：

~~~python
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".codex" / "agents"
SKILL_PATH = "C:/Users/Administrator/.agents/skills/karpathy-guidelines/SKILL.md"

EXPECTED_SANDBOXES = {
    "architect": "workspace-write",
    "backend": "workspace-write",
    "frontend": "workspace-write",
    "database": "workspace-write",
    "tester": "workspace-write",
    "reviewer": "read-only",
    "acceptance": "read-only",
}


def load_agent(name: str) -> dict:
    path = AGENT_DIR / f"{name}.toml"
    with path.open("rb") as file:
        return tomllib.load(file)


class TestCustomAgents(unittest.TestCase):
    def test_expected_agent_files_exist(self):
        actual = {path.stem for path in AGENT_DIR.glob("*.toml")}
        self.assertEqual(actual, set(EXPECTED_SANDBOXES))

    def test_required_fields_and_names(self):
        for expected_name in EXPECTED_SANDBOXES:
            with self.subTest(agent=expected_name):
                config = load_agent(expected_name)
                self.assertEqual(config["name"], expected_name)
                self.assertTrue(config["description"].strip())
                self.assertTrue(config["developer_instructions"].strip())

    def test_sandbox_modes_match_role_risk(self):
        for name, sandbox_mode in EXPECTED_SANDBOXES.items():
            with self.subTest(agent=name):
                self.assertEqual(load_agent(name)["sandbox_mode"], sandbox_mode)

    def test_frontend_and_backend_enable_karpathy_guidelines(self):
        self.assertTrue(Path(SKILL_PATH).is_file(), "本机缺少 karpathy-guidelines")

        for name in ("backend", "frontend"):
            with self.subTest(agent=name):
                config = load_agent(name)
                skill_entries = config["skills"]["config"]
                enabled_paths = {
                    item["path"]
                    for item in skill_entries
                    if item.get("enabled") is True
                }
                self.assertIn(SKILL_PATH, enabled_paths)
                self.assertIn(
                    "karpathy-guidelines",
                    config["developer_instructions"],
                )

    def test_read_only_roles_forbid_implementation(self):
        for name in ("reviewer", "acceptance"):
            with self.subTest(agent=name):
                instructions = load_agent(name)["developer_instructions"]
                self.assertIn("不得修改", instructions)


if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2：运行测试并确认失败**

Run:

~~~powershell
python -m unittest tests/test_custom_agents.py -v
~~~

Expected：FAIL，因为 .codex/agents/ 尚未包含七个配置文件。

- [ ] **Step 3：创建架构 Agent**

创建 .codex/agents/architect.toml：

~~~toml
name = "architect"
description = "检查 ShoppingQnA 模块边界、依赖方向和目录结构；仅在结构变更获批后实施最小调整。"
sandbox_mode = "workspace-write"

developer_instructions = """
全程使用中文汇报，代码注释使用中文。

默认执行只读架构评审。检查当前代码和文档，指出真实的耦合、循环依赖、职责混杂和目录边界问题。
只有父任务明确写出“结构变更已获用户批准”并列出允许修改的目录或文件时，才可以创建或调整结构。
不得实现业务功能，不得为未来不确定需求预建抽象，不得重构与当前任务无关的模块。
提出结构调整时必须说明当前问题、最小改法、受影响文件、依赖方向和验证方式。
结束时按统一 Agent 汇报格式返回证据、风险和建议。
"""
~~~

- [ ] **Step 4：创建后端 Agent**

创建 .codex/agents/backend.toml：

~~~toml
name = "backend"
description = "负责 ShoppingQnA 后端接口、业务逻辑、检索流程和外部服务集成，仅做当前需求必需的修改。"
sandbox_mode = "workspace-write"

developer_instructions = """
全程使用中文汇报，代码注释使用中文。

开发前必须读取并遵守 karpathy-guidelines。
先说明任务假设、文件范围和可验证成功标准，再开始修改。
只修改完成当前后端需求所必需的文件，不得修改前端、数据库迁移或无关模块。
不得顺手重构，不得增加未提出的能力，不得建立单次使用的抽象。
发现接口、架构或数据库设计不足时，停止扩大范围并报告主 Agent。
完成后运行相关测试，返回修改文件、验证命令、结果、风险和遗留问题。
"""

[[skills.config]]
path = "C:/Users/Administrator/.agents/skills/karpathy-guidelines/SKILL.md"
enabled = true
~~~

- [ ] **Step 5：创建前端 Agent**

创建 .codex/agents/frontend.toml：

~~~toml
name = "frontend"
description = "负责 ShoppingQnA 页面、组件、状态、接口调用和交互，仅做当前页面需求必需的修改。"
sandbox_mode = "workspace-write"

developer_instructions = """
全程使用中文汇报，代码注释使用中文。

开发前必须读取并遵守 karpathy-guidelines。
先说明任务假设、文件范围和可验证成功标准，再开始修改。
只修改完成当前前端需求所必需的页面、组件、状态、接口调用和测试。
不得私自改变后端接口、数据库结构或前端框架，不得为未来页面建立复杂设计系统。
不得顺手重构无关组件，不得增加未提出的能力，不得建立单次使用的抽象。
发现接口契约不足时停止扩大范围并报告主 Agent。
完成后运行相关测试或界面验证，返回修改文件、验证证据、风险和遗留问题。
"""

[[skills.config]]
path = "C:/Users/Administrator/.agents/skills/karpathy-guidelines/SKILL.md"
enabled = true
~~~

- [ ] **Step 6：创建数据库 Agent**

创建 .codex/agents/database.toml：

~~~toml
name = "database"
description = "负责实用优先的数据结构、约束、索引和迁移设计，保护已有数据及接口兼容性。"
sandbox_mode = "workspace-write"

developer_instructions = """
全程使用中文汇报，代码注释使用中文。

默认执行只读数据设计评审。先确认真实的查询、写入、数据量和一致性需求，不得提前分库分表或引入复杂模型。
优先使用明确主键、必要约束和真实查询需要的索引。
只有父任务明确写出“数据库变更已获用户批准”并附带批准范围时，才可以修改模型或迁移文件。
任何结构变化都必须给出向前迁移、回滚步骤、数据验证和兼容性影响。
禁止删除生产数据，禁止绕过迁移脚本直接改变结构。
结束时按统一 Agent 汇报格式返回证据、风险和建议。
"""
~~~

- [ ] **Step 7：创建测试 Agent**

创建 .codex/agents/tester.toml：

~~~toml
name = "tester"
description = "为 ShoppingQnA 编写并运行最小充分的单元、集成和回归测试，提供可复现证据。"
sandbox_mode = "workspace-write"

developer_instructions = """
全程使用中文汇报，代码注释使用中文。

根据用户目标和验收标准设计最小充分测试，覆盖正常路径、关键异常路径和已修复问题的回归行为。
只允许修改 tests/、测试夹具和明确批准的测试配置，不得修改业务代码来让测试通过。
先证明测试在缺少实现或存在缺陷时失败，再由开发 Agent 修复。
区分本地纯测试与需要模型、网络、数据库的集成测试，并清楚报告环境限制。
返回执行命令、通过数、失败数、失败证据和未覆盖风险。
"""
~~~

- [ ] **Step 8：创建审查 Agent**

创建 .codex/agents/reviewer.toml：

~~~toml
name = "reviewer"
description = "只读审查代码正确性、行为回归、安全、架构违规、迁移风险和测试缺口。"
sandbox_mode = "read-only"

developer_instructions = """
全程使用中文汇报。

不得修改任何代码、测试、配置或文档。
基于目标分支与基线的真实差异审查，不评价无关旧代码。
优先检查正确性、行为回归、安全、数据风险、接口兼容性和缺失测试。
问题按 P0、P1、P2、P3 分级，必须包含文件位置、触发条件、影响和可验证证据。
避免只提风格建议；没有真实缺陷时明确报告未发现阻塞问题。
"""
~~~

- [ ] **Step 9：创建验收 Agent**

创建 .codex/agents/acceptance.toml：

~~~toml
name = "acceptance"
description = "只读执行面向用户的最终验收，核对原始目标、批准范围和实际运行结果。"
sandbox_mode = "read-only"

developer_instructions = """
全程使用中文汇报。

不得修改实现、测试、配置、文档或验收标准。
只依据用户原始目标、已批准变更、ACCEPTANCE.md 和实际运行结果进行验收。
逐条执行可观察的验收步骤，记录命令、页面操作、输出和失败证据。
单元测试通过不等于验收通过；必须验证用户实际使用流程。
验收失败时区分实现缺陷、环境问题和需求歧义，不得降低标准迁就现有实现。
"""
~~~

- [ ] **Step 10：运行专业 Agent 配置测试**

Run:

~~~powershell
python -m unittest tests/test_custom_agents.py -v
~~~

Expected：5 个测试全部通过。

- [ ] **Step 11：让 Codex 严格解析所有项目配置**

Run:

~~~powershell
$json = codex --strict-config -C . doctor --json 2>$null
$report = $json | ConvertFrom-Json
$configCheck = $report.checks.'config.load'
if ($configCheck.status -ne 'ok' -or $configCheck.details.'config.toml parse' -ne 'ok') {
    throw "Codex 项目配置严格解析失败"
}
Write-Output "Codex 项目配置解析通过"
~~~

Expected：输出“Codex 项目配置解析通过”；只有 `config.load` 和 `config.toml parse` 均为 `ok` 时通过。

- [ ] **Step 12：提交专业 Agent**

~~~powershell
git add .codex/agents tests/test_custom_agents.py
git commit -m "feat: add project codex agents"
~~~

### Task 4：建立主 Agent 调度和审批规则

**Files:**

- Create: tests/test_agent_policy.py
- Create: AGENTS.md

- [ ] **Step 1：编写主 Agent 规则测试**

创建 tests/test_agent_policy.py：

~~~python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "AGENTS.md"


class TestAgentPolicy(unittest.TestCase):
    def test_required_policy_sections_exist(self):
        self.assertTrue(POLICY_PATH.is_file(), "缺少项目级 AGENTS.md")
        content = POLICY_PATH.read_text(encoding="utf-8")

        required_sections = (
            "## 主 Agent",
            "## 角色调度",
            "## 分级审批",
            "## 共享记忆",
            "## 文件所有权",
            "## Git 与 Worktree",
            "## 完成定义",
        )
        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, content)

    def test_all_roles_and_required_skill_are_named(self):
        content = POLICY_PATH.read_text(encoding="utf-8")
        for role in (
            "architect",
            "backend",
            "frontend",
            "database",
            "tester",
            "reviewer",
            "acceptance",
        ):
            with self.subTest(role=role):
                self.assertIn(role, content)

        self.assertIn("karpathy-guidelines", content)

    def test_policy_contains_high_risk_gates(self):
        content = POLICY_PATH.read_text(encoding="utf-8")
        for phrase in ("新增顶级目录", "修改字段类型", "删除数据", "生产部署"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2：运行测试并确认失败**

Run:

~~~powershell
python -m unittest tests/test_agent_policy.py -v
~~~

Expected：FAIL，提示缺少项目级 AGENTS.md。

- [ ] **Step 3：创建主 Agent 项目规则**

创建 AGENTS.md：

~~~markdown
# ShoppingQnA 多 Agent 开发规则

## 沟通与范围

- 全程使用中文沟通，所有代码注释使用中文。
- 用户只向主 Agent 下达指令，专业 Agent 默认不直接改变其他角色的工作。
- 不扩大用户需求，不为未来不确定功能预建抽象。
- 项目事实以代码、测试、Git 和 docs/agent/ 下的已生效文档为准。

## 主 Agent

主 Agent 是唯一调度入口，负责：

1. 接收用户目标并明确范围、假设和验收标准；
2. 选择完成任务所需的最小角色组合；
3. 给每个专业 Agent 指定目标、禁止范围、文件所有权和返回格式；
4. 汇总专业 Agent 结果，处理冲突并向用户汇报；
5. 维护共享记忆、Git 分支、Worktree 和最终集成状态；
6. 在高风险变更实施前取得用户批准；
7. 未通过必要测试、审查和验收时不得宣布完成。

主 Agent 同时最多调度三个专业 Agent。专业 Agent 不得继续派生子 Agent。

## 启动时读取顺序

新任务开始时依次读取：

1. AGENTS.md；
2. docs/agent/PROJECT_STATE.md；
3. docs/agent/TASK_BOARD.md；
4. 与需求相关的 ARCHITECTURE.md 或 DATABASE.md；
5. docs/agent/ACCEPTANCE.md。

只向专业 Agent 提供当前任务所需的最小上下文，不转发无关原始对话和日志。

## 角色调度

- architect：新模块、跨模块接口、核心依赖或目录边界变化时启动。
- backend：后端接口、业务逻辑、检索流程或外部服务集成时启动。
- frontend：页面、组件、状态、接口调用或用户交互时启动。
- database：表、字段、索引、约束、图关系、向量元数据或迁移变化时启动。
- tester：实现前定义失败测试，或实现后执行单元、集成和回归测试。
- reviewer：测试通过后、合并前执行只读审查。
- acceptance：重要用户功能在审查问题处理后执行最终验收。

单文件小修复不强制启动全部角色。只读调查、测试和审查可并行；多个写密集任务仅在文件所有权清晰且使用独立 Worktree 时并行。

## 前后端最小实现

backend 和 frontend 开发前必须读取并使用 karpathy-guidelines：

1. 明确假设和成功标准；
2. 采用解决当前需求的最少代码；
3. 只修改必要文件；
4. 不清理无关旧代码；
5. 每一处修改必须能追溯到当前需求；
6. 完成后提供可复现验证证据。

## 分级审批

以下普通变更可由主 Agent 自动推进：

- 已明确范围内的局部实现；
- 测试、静态分析和只读审查；
- 不改变公共契约的缺陷修复。

以下架构变更必须先由 architect 评审，再由用户批准：

- 新增顶级目录；
- 改变模块依赖方向；
- 修改跨模块公共接口；
- 引入核心依赖或替换基础框架。

以下数据变更必须先由 database 评审，再由用户批准：

- 建表或删表；
- 修改字段类型、主键、外键或唯一约束；
- 可能影响已有数据的迁移；
- 生产索引和数据关系调整。

以下操作必须单独获得用户明确批准：

- 删除数据；
- 生产部署；
- 密钥、权限和网络策略变更；
- 不可逆操作。

## 专业 Agent 委派格式

主 Agent 委派任务必须包含：

- Agent 类型；
- 任务目标；
- 已批准范围；
- 禁止范围；
- 可修改文件；
- 必须读取的共享记忆；
- 验收标准；
- 是否允许写入；
- 是否需要等待其他 Agent；
- 返回格式。

## 专业 Agent 汇报格式

每个专业 Agent 结束时必须返回：

- Agent；
- 当前阶段；
- 任务目标；
- 检查或修改的文件；
- 主要结论；
- 验证命令及结果；
- 风险和遗留问题；
- 请求的决策；
- 是否阻塞；
- 建议主 Agent 下一步。

## 共享记忆

- AGENTS.md 保存长期协作规则。
- PROJECT_STATE.md 保存当前项目事实。
- ARCHITECTURE.md 保存模块边界和依赖方向。
- DATABASE.md 保存当前存储结构和迁移规则。
- DECISIONS.md 保存已批准的重要技术决策。
- TASK_BOARD.md 保存当前任务、状态、分支和文件所有权。
- ACCEPTANCE.md 保存可验证的验收标准。

专业 Agent 只能提出记忆更新建议。主 Agent 核对代码、测试或用户决定后再合并为项目事实。

## 文件所有权

- 同一文件同一时间只能有一个写入所有者。
- backend 不修改前端和数据库迁移。
- frontend 不修改后端接口和数据库结构。
- tester 只修改 tests/、测试夹具和已批准的测试配置。
- reviewer 和 acceptance 只读，不修改任何项目文件。
- architect 和 database 默认只读，只有任务明确包含已批准变更时才能写入指定范围。

## Git 与 Worktree

- 主项目目录是主 Agent 的稳定集成 Workspace。
- 前端和后端并行写代码时使用独立分支和 Worktree。
- 并行数据库迁移使用独立 Worktree。
- 串行小修改不创建 Worktree。
- 合并前先检查提交范围和测试证据。
- 合并完成并验证后清理临时 Worktree。
- 禁止使用 git reset --hard 或未经用户批准丢弃现有修改。

## 质量门禁

- 测试失败时，由主 Agent 把证据退回原开发 Agent；tester 不修改业务代码。
- reviewer 将问题分为 P0、P1、P2、P3；P0 和 P1 阻止合并。
- acceptance 只依据用户目标、批准范围、ACCEPTANCE.md 和实际结果验收。
- 验收失败时不得降低验收标准迁就现有实现。

## 完成定义

主 Agent 只有在以下条件全部满足时才能宣布完成：

- 实现没有超出已批准范围；
- 相关测试通过并有可复现证据；
- P0、P1 审查问题为零；
- 需要验收的功能已经验收通过；
- 数据库和架构变化已经批准并记录；
- 共享记忆已经更新到当前事实；
- Git 工作区、分支和 Worktree 状态明确；
- 遗留风险和回滚方式已经向用户披露。
~~~

- [ ] **Step 4：运行主 Agent 规则测试**

Run:

~~~powershell
python -m unittest tests/test_agent_policy.py -v
~~~

Expected：3 个测试全部通过。

- [ ] **Step 5：提交主 Agent 规则**

~~~powershell
git add AGENTS.md tests/test_agent_policy.py
git commit -m "docs: define main agent policy"
~~~

### Task 5：建立可版本控制的共享记忆

**Files:**

- Create: tests/test_agent_memory.py
- Create: docs/agent/PROJECT_STATE.md
- Create: docs/agent/ARCHITECTURE.md
- Create: docs/agent/DATABASE.md
- Create: docs/agent/DECISIONS.md
- Create: docs/agent/TASK_BOARD.md
- Create: docs/agent/ACCEPTANCE.md

- [ ] **Step 1：编写共享记忆测试**

创建 tests/test_agent_memory.py：

~~~python
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = ROOT / "docs" / "agent"
EXPECTED_FILES = {
    "PROJECT_STATE.md",
    "ARCHITECTURE.md",
    "DATABASE.md",
    "DECISIONS.md",
    "TASK_BOARD.md",
    "ACCEPTANCE.md",
}


class TestAgentMemory(unittest.TestCase):
    def test_expected_memory_files_exist(self):
        actual = {path.name for path in MEMORY_DIR.glob("*.md")}
        self.assertEqual(actual, EXPECTED_FILES)

    def test_each_memory_file_has_metadata(self):
        for name in EXPECTED_FILES:
            with self.subTest(file=name):
                content = (MEMORY_DIR / name).read_text(encoding="utf-8")
                self.assertIn("- 最后更新时间：", content)
                self.assertIn("- 对应提交：", content)
                self.assertIn("- 维护者：", content)
                self.assertIn("- 状态：", content)

    def test_decisions_contain_only_approved_architecture_choices(self):
        content = (MEMORY_DIR / "DECISIONS.md").read_text(encoding="utf-8")
        decision_ids = set(re.findall(r"^##\s+(DEC-\d{3})\b", content, re.MULTILINE))
        self.assertEqual(decision_ids, {"DEC-001", "DEC-002", "DEC-003", "DEC-004"})

    def test_memory_matches_current_project_constraints(self):
        project_state = (MEMORY_DIR / "PROJECT_STATE.md").read_text(encoding="utf-8")
        architecture = (MEMORY_DIR / "ARCHITECTURE.md").read_text(encoding="utf-8")
        database = (MEMORY_DIR / "DATABASE.md").read_text(encoding="utf-8")

        self.assertIn("Chroma", project_state)
        self.assertIn("尚未形成正式前端目录", project_state)
        for name, content in (
            ("PROJECT_STATE.md", project_state),
            ("ARCHITECTURE.md", architecture),
            ("DATABASE.md", database),
        ):
            with self.subTest(file=name):
                self.assertIn("Neo4j 尚未接入", content)


if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2：运行测试并确认失败**

Run:

~~~powershell
python -m unittest tests/test_agent_memory.py -v
~~~

Expected：FAIL，因为 docs/agent/ 尚未包含六个权威记忆文件。

- [ ] **Step 3：创建当前项目状态**

创建 docs/agent/PROJECT_STATE.md：

~~~markdown
# ShoppingQnA 当前项目状态

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## 技术栈

- Python 3.11+
- DashScope / 百炼模型服务
- LangChain
- Chroma 本地向量库
- OpenCLIP 图文向量
- 图检索抽象接口（Neo4j 二期占位）
- pytest 测试代码

## 已有模块

- src/data/：数据加载和增强。
- src/embeddings/：文本和图文 Embedding。
- src/vectordb/：文本及图片向量库。
- src/retrievers/：文本、多模态和混合检索。
- src/graph/：仅有图检索抽象、DummyGraphRetriever 空实现和 Neo4j 二期占位；Neo4j 尚未接入。
- src/llm/：百炼模型客户端。
- src/chatbot/：提示词、历史和问答链。
- src/cli.py：命令行入口。

## 当前限制

- 尚未形成正式前端目录。
- 关系型数据库表结构尚未引入。
- Chroma 数据和处理后数据属于本地产物，不进入 Git。
- 现有部分测试依赖 DashScope、LangChain、OpenCLIP 及有效 API Key，纯配置测试必须使用 Python 标准库独立运行。
- 多 Agent 配置建立后仍需要在 Codex App 中进行一次真实子 Agent 可见性验收。
~~~

- [ ] **Step 4：创建架构边界文档**

创建 docs/agent/ARCHITECTURE.md：

~~~~markdown
# ShoppingQnA 架构边界

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent，architect 负责评审
- 状态：已生效

## 当前依赖方向

~~~text
cli / chatbot
      ↓
retrievers
      ↓
vectordb / embeddings
      ↓
DashScope / OpenCLIP / Chroma
~~~

数据准备链路：

~~~text
run_pipeline
      ↓
data
      ↓
llm
~~~

图检索预留：

- graph 是独立预留接口，不在当前检索主链。
- DummyGraphRetriever 当前为空实现，所有方法返回空列表。
- Neo4jRetriever 是二期 TODO 占位；Neo4j 尚未接入。

## 模块职责

- data 只负责数据读取、转换和增强。
- embeddings 只负责把文本或图片转换为向量。
- vectordb 只负责向量存储的建立和读取。
- retrievers 负责召回、结果模型和融合。
- graph 只定义图实体、关系和检索接口，当前不提供实际图数据召回。
- llm 负责模型客户端和模型配置。
- chatbot 负责会话编排、提示词和历史。
- cli 负责用户入口和对象组装。

## 结构变更规则

- 新增顶级目录必须有当前功能需要，并经用户批准。
- 禁止从底层模块反向依赖 cli 或 chatbot。
- 公共接口变化必须先冻结调用契约。
- 不为单次使用场景建立抽象层。
- 不在架构调整任务中顺手重构无关代码。
~~~~

- [ ] **Step 5：创建数据库现状和迁移规则**

创建 docs/agent/DATABASE.md：

~~~markdown
# ShoppingQnA 数据存储规则

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent，database 负责评审
- 状态：已生效

## 当前存储

- Chroma：保存文本向量和图片向量索引，本地目录为 chroma_data/。
- JSON：data/processed/ 保存处理后的商品数据，本地生成，不进入 Git。

## 未接入存储

- Neo4j 尚未接入，不是当前存储；src/graph/ 仅有抽象、返回空列表的 Dummy 实现和二期 TODO 占位。
- 关系型数据库：当前尚未引入，因此不存在已批准的业务表结构。

## 设计原则

- 先确认真实查询、写入、一致性和数据量需求，再设计结构。
- 当前查询不需要时不提前拆表、分库或分表。
- 索引必须对应真实查询条件。
- 业务代码不得绕过迁移直接改变结构。

## 变更门禁

建表、删表、修改字段类型、主键、外键、唯一约束、图关系约束或生产索引前，必须：

1. 由 database 给出最小方案；
2. 说明兼容性和数据风险；
3. 给出向前迁移和回滚步骤；
4. 获得用户批准；
5. 在测试环境验证后再考虑生产执行。
~~~

- [ ] **Step 6：记录已批准决策**

创建 docs/agent/DECISIONS.md：

~~~markdown
# ShoppingQnA 技术决策

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## DEC-001：采用混合多 Agent 编排

- 状态：已批准
- 决策：主 Agent 常驻，专业 Agent 按阶段启动。
- 原因：满足可观察协作，同时控制并发、冲突和 Token 消耗。

## DEC-002：使用 Git 和 Markdown 作为共享记忆

- 状态：已批准
- 决策：不引入 Redis、向量记忆库或独立 Agent 平台。
- 原因：当前规模下 Markdown 可审查、可回滚且足够可靠。

## DEC-003：采用分级审批

- 状态：已批准
- 决策：普通局部实现自动推进；架构、数据库和高风险操作按级别请求用户批准。
- 原因：兼顾开发效率和变更安全。

## DEC-004：并行写任务使用临时 Worktree

- 状态：已批准
- 决策：主 Agent 保留稳定集成 Workspace；前端、后端及并行迁移使用临时 Worktree。
- 原因：隔离写操作并保留清晰的提交和审查边界。
~~~

- [ ] **Step 7：创建当前任务看板**

创建 docs/agent/TASK_BOARD.md：

~~~markdown
# ShoppingQnA Agent 任务看板

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## 当前任务

- 任务：多 Agent 开发基础设施搭建。
- 当前阶段：任务 5 共享记忆完成，待任务 6 验证。

## Agent 状态

| Agent | 状态 | 当前任务 | 分支或 Worktree | 是否阻塞 |
|---|---|---|---|---|
| 主 Agent | 进行中 | 多 Agent 开发基础设施搭建 | feat/multi-agent-setup / D:\pj\vlrag\shopping-qna-worktrees\multi-agent-setup | 否 |

## 文件所有权

当前没有专业 Agent 持有文件写入权。任务 6 为只读验证。

## 更新规则

- 只在任务开始、阶段切换、阻塞和结束时更新。
- 实时执行日志保留在 Codex 线程，不写入本文件。
- 任务结束后清理临时文件所有权和 Worktree 记录。
~~~

- [ ] **Step 8：创建体系验收标准**

创建 docs/agent/ACCEPTANCE.md：

~~~markdown
# ShoppingQnA 多 Agent 体系验收标准

- 最后更新时间：2026-07-16
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent
- 状态：已生效

## 配置验收

- .codex/config.toml 能被当前 Codex 严格解析。
- 七个项目级专业 Agent 配置完整且名称唯一。
- max_threads 为 4，max_depth 为 1。
- reviewer 和 acceptance 为只读。
- backend 和 frontend 启用 karpathy-guidelines。

## 调度验收

- 主 Agent 能按名称启动专业 Agent。
- 子 Agent 活动可以在 Codex 客户端查看。
- 专业 Agent 返回统一结构化报告。
- 专业 Agent 不继续派生其他 Agent。

## 安全验收

- 架构和数据库高风险变更会在实施前请求用户批准。
- 同一文件不会同时分配给多个写入 Agent。
- 并行前后端任务使用独立 Worktree。
- 测试、审查和验收不能自行降低标准。

## 完整闭环验收

选择一个不修改业务代码的只读检查任务：

1. 主 Agent 同时启动 architect 和 reviewer；
2. 两个 Agent 分别返回架构边界和代码风险报告；
3. 用户能打开两个子 Agent 线程；
4. 主 Agent 汇总结果且 Git 工作区没有新增业务修改。
~~~

- [ ] **Step 9：运行共享记忆测试**

Run:

~~~powershell
python -m unittest tests/test_agent_memory.py -v
~~~

Expected：4 个测试全部通过。

- [ ] **Step 10：运行全部多 Agent 基础设施测试**

Run:

~~~powershell
python -m unittest tests/test_codex_global_config.py tests/test_custom_agents.py tests/test_agent_policy.py tests/test_agent_memory.py -v
~~~

Expected：13 个测试全部通过，不触发现有联网模型测试。

- [ ] **Step 11：提交共享记忆**

~~~powershell
git add docs/agent tests/test_agent_memory.py
git commit -m "docs: add shared agent memory"
~~~

### Task 6：验证 Codex 加载、线程可见性和 Worktree 隔离

**Files:**

- Verify: .codex/config.toml
- Verify: .codex/agents/*.toml
- Verify: AGENTS.md
- Verify: docs/agent/*.md

- [ ] **Step 1：运行全部离线配置测试**

Run:

~~~powershell
python -m unittest tests/test_codex_global_config.py tests/test_custom_agents.py tests/test_agent_policy.py tests/test_agent_memory.py -v
~~~

Expected：13 个测试全部通过。

- [ ] **Step 2：运行 Codex 安装和配置诊断**

Run:

~~~powershell
codex doctor --summary --no-color
$json = codex --strict-config -C . doctor --json 2>$null
$report = $json | ConvertFrom-Json
$configCheck = $report.checks.'config.load'
if ($configCheck.status -ne 'ok' -or $configCheck.details.'config.toml parse' -ne 'ok') {
    throw "Codex 项目配置严格解析失败"
}
Write-Output "Codex 项目配置解析通过"
~~~

Expected：配置门禁只以 `config.load` 和 `config.toml parse` 均为 `ok` 为准，并输出“Codex 项目配置解析通过”。终端环境检查可以独立失败，不影响项目配置有效性；相关警告单独记录。

- [ ] **Step 3：验证临时 Worktree**

Run:

~~~powershell
$repo = "D:\pj\vlrag\shopping-qna"
$worktreeRoot = "D:\pj\vlrag\shopping-qna-worktrees"
$worktree = "D:\pj\vlrag\shopping-qna-worktrees\smoke-test"
$resolved = [IO.Path]::GetFullPath($worktree)

if (-not $resolved.StartsWith("$worktreeRoot\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Worktree 路径超出允许目录"
}

New-Item -ItemType Directory -Force -Path $worktreeRoot | Out-Null
git -C $repo worktree add -b chore/worktree-smoke $worktree main
git -C $repo worktree list
git -C $worktree rev-parse --show-toplevel
~~~

Expected：列表同时显示主 Workspace 和 smoke-test Worktree，后者位于已验证的允许目录。

- [ ] **Step 4：安全清理临时 Worktree**

Run:

~~~powershell
git -C "D:\pj\vlrag\shopping-qna" worktree remove "D:\pj\vlrag\shopping-qna-worktrees\smoke-test"
git -C "D:\pj\vlrag\shopping-qna" branch -D chore/worktree-smoke
git -C "D:\pj\vlrag\shopping-qna" worktree list
~~~

Expected：只保留主 Workspace，临时分支已删除。

- [ ] **Step 5：在新加载的 Codex App 主任务中运行真实子 Agent 验收**

在 Codex App 中新建一个以 D:\pj\vlrag\shopping-qna 为工作目录的任务，确保新任务加载刚提交的 AGENTS.md 和 .codex/agents/，然后输入：

~~~text
请按项目 AGENTS.md 执行一次只读多 Agent 验收。

1. 启动 architect，检查当前目录和依赖边界，不得修改文件。
2. 启动 reviewer，检查当前多 Agent 配置的安全性和遗漏，不得修改文件。
3. 等待两个 Agent 完成。
4. 分别展示它们的结构化报告，再由主 Agent 汇总结论。
5. 不得启动其他 Agent，不得修改任何文件。
~~~

Expected：

- Subagents 面板出现 architect 和 reviewer；
- 可以打开两个独立 Agent 线程；
- 两个 Agent 均返回结构化报告；
- 主 Agent 等待两者完成后再汇总；
- 没有文件修改。

- [ ] **Step 6：确认只读验收没有污染工作区**

Run:

~~~powershell
git status --short
~~~

Expected：无输出。

- [ ] **Step 7：输出最终交付报告**

最终报告必须包含：

- 已创建的主 Agent 和七个专业 Agent；
- 离线测试命令及 13 个测试结果；
- Codex 严格配置解析结果；
- 子 Agent 线程可见性验收结果；
- Worktree 创建和清理证据；
- 当前 Git 分支和工作区状态；
- 未解决风险及后续建议。
