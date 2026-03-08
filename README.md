# 西比拉系统 (Sibyl System)

多 Agent 自动化科研系统，基于 Claude Code 原生架构，端到端编排从文献调研到论文发表的完整 ML 研究流程。

## 系统概览

Sibyl 通过 **状态机编排器** 协调 20+ 个 AI Agent，自动完成文献调研、创意生成、实验设计与执行、结果分析、论文撰写与审稿的全流程。系统支持多轮迭代优化，内置跨项目学习机制，持续提升研究质量。

### 核心特性

- **19 阶段研究流水线**：从文献搜索到论文完稿，全流程自动化
- **多 Agent 协作**：6 Agent 辩论生成创意、6 Agent 分析实验结果、6 Agent 并行写作
- **GPU 并行调度**：拓扑排序 + 贪心分配，自动管理实验任务依赖与 GPU 资源
- **迭代优化循环**：质量门控自动决定继续迭代或终止，支持 PIVOT 机制切换研究方向
- **跨项目进化学习**：自动提取教训、追踪有效性、生成 Agent 提示词改进
- **多模型协作**：Claude Opus/Sonnet + GPT-5.4 (Codex) 独立交叉审查

## 工作流程

```
+== Research Iteration =============+  +== Paper Writing ====================+
|                                    |  |                                     |
|  Literature Search (arXiv + Web)   |  |  Outline                            |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Idea Debate (6 Agents)            |  |  Section Writing (seq/para/Codex)   |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Experiment Planning               |  |  Cross Review (6 Agents)            |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Pilot Experiments                 |  |  Integration & Editing              |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Full Experiments (GPU parallel)   |  |  Final Review (NeurIPS level)       |
|       |                            |  |       | fail --> back to edit (x2)  |
|       v                            |  |       v                             |
|  Result Debate (6 Agents)          |  |  LaTeX --> compile PDF              |
|       |                            |  |       |                             |
|       v                            |  +-------|---------+-------------------+
|  Decision                          |          |
|       | PIVOT --> back to Idea     |          |
|       | PROCEED                    |          v
+-------|-----------+----------------+  +== Review & Reflection ==============+
        |                               |                                     |
        +----------> Outline            |  Review (Critic+Supervisor+Codex)    |
                                        |       |                             |
                                        |       v                             |
                                        |  Reflection (lessons learned)       |
                                        |       |                             |
                                        |       v                             |
                                        |  Lark Sync (cloud docs)             |
                                        |       |                             |
                                        |       v                             |
                                        |  Quality Gate                       |
                                        |       | >= 8.0 & >= 2 iter --> DONE |
                                        |       | else --> next iteration     |
                                        |                                     |
                                        +-------------------------------------+
```

### 阶段详解

| 阶段 | 说明 | Agent 模式 |
|------|------|-----------|
| `literature_search` | arXiv + Web 双源文献调研 | 单 Agent |
| `idea_debate` | 6 视角创意辩论（创新者/实用主义/理论/反对者/跨学科/实验主义） | 6 Agent Team |
| `planning` | 设计实验方案，生成带依赖关系的 task_plan.json | 单 Agent |
| `pilot_experiments` | 小规模验证实验可行性 | 单 Agent |
| `experiment_cycle` | GPU 并行执行完整实验，按拓扑排序分批调度 | 单 Agent + GPU 调度 |
| `result_debate` | 6 视角结果分析（乐观/怀疑/战略/方法论/比较/修正） | 6 Agent Team |
| `experiment_decision` | 监督者决策：PIVOT（换方向）或 PROCEED（继续） | 单 Agent |
| `writing_outline` | 生成论文大纲 | 单 Agent |
| `writing_sections` | 按章节写作（支持顺序/并行/Codex 三种模式） | 可配置 |
| `writing_critique` | 6 Agent 交叉评审各章节 | 6 Agent 并行 |
| `writing_integrate` | 编辑整合为完整论文 | 单 Agent |
| `writing_final_review` | NeurIPS/ICML 级别终审（不达标可循环修改） | 单 Agent |
| `writing_latex` | 转换为 NeurIPS LaTeX 格式并编译 PDF | 单 Agent |
| `review` | Critic + Supervisor + Codex 并行审稿 | 并行 Skills |
| `reflection` | 分类问题、生成改进计划、记录教训 | 单 Agent |
| `lark_sync` | 同步研究数据到飞书云文档 | 单 Agent |
| `quality_gate` | 评估是否达标（≥8.0 分且 ≥2 轮迭代即完成） | 自动判定 |

## Agent 角色

### 创意生成团队（Idea Debate）

| Agent | 视角 | 职责 |
|-------|------|------|
| 创新者 (Innovator) | 跨领域创新 | 大胆的方法论迁移和创新组合 |
| 实用主义者 (Pragmatist) | 工程可行性 | 确保想法可落地实现 |
| 理论研究者 (Theoretical) | 数学基础 | 关注理论保证和证明 |
| 反对者 (Contrarian) | 挑战假设 | 寻找反面证据和盲点 |
| 跨学科者 (Interdisciplinary) | 类比启发 | 从认知科学、物理、生物引入方法 |
| 实验主义者 (Empiricist) | 实验优先 | 关注可复现性和数据质量 |

### 结果分析团队（Result Debate）

| Agent | 视角 | 职责 |
|-------|------|------|
| 乐观分析者 (Optimist) | 积极发现 | 挖掘正面结果和延伸方向 |
| 怀疑论者 (Skeptic) | 统计严谨 | 质疑统计显著性和混淆因素 |
| 战略顾问 (Strategist) | 下一步 | 建议资源分配和研究方向 |
| 方法论者 (Methodologist) | 方法审查 | 评估实验内外部效度 |
| 比较分析者 (Comparativist) | SOTA 对标 | 与现有最佳方法比较定位 |
| 修正主义者 (Revisionist) | 假设修正 | 基于结果反思和调整假设 |

### Agent 模型层级

| 层级 | 模型 | 用途 |
|------|------|------|
| Heavy | Opus 4.6 | 综合决策、监督审查、编辑整合、批评、反思 |
| Standard | Opus 4.6 | 文献调研、实验规划、实验执行、写作 |
| Light | Sonnet 4.6 | 结果辩论、交叉评审、章节批评 |
| Codex | GPT-5.4 High | 独立第三方审查、可选写作模式 |

## 项目结构

```
sibyl-system/
├── sibyl/                      # 核心 Python 模块
│   ├── orchestrate.py          # 状态机编排器（19 阶段流水线）
│   ├── config.py               # 配置管理（模型/GPU/模式）
│   ├── workspace.py            # 工作空间文件与 Git 管理
│   ├── gpu_scheduler.py        # GPU 拓扑排序与并行调度
│   ├── evolution.py            # 跨项目进化学习引擎
│   ├── reflection.py           # 迭代日志记录
│   └── prompts/                # 32 个 Agent 提示词模板
├── .claude/
│   ├── agents/                 # Agent 层级定义（heavy/standard/light）
│   └── skills/sibyl-*/         # 30+ Fork Skills（独立上下文执行）
├── plugin/commands/            # Claude Code 插件命令
├── workspaces/                 # 研究项目工作空间
├── tests/                      # 单元测试
└── requirements.txt            # 依赖（PyYAML, rich）
```

### 工作空间结构

每个研究项目在 `workspaces/<project>/` 下拥有独立的文件系统：

```
workspaces/<project>/
├── status.json                 # 编排器状态（阶段/迭代/分数）
├── config.yaml                 # 项目级配置覆盖
├── topic.txt / spec.md         # 研究主题与需求规格
├── context/literature.md       # 文献综述
├── idea/                       # 创意提案、备选方案、辩论记录
├── plan/                       # 实验方案、task_plan.json
├── exp/                        # 代码、结果、日志、GPU 进度
├── writing/                    # 大纲、章节、评审、完整论文、LaTeX
├── logs/                       # 迭代归档、研究日记、主日志
└── lark_sync/                  # 飞书同步注册表
```

## 快速开始

### 环境要求

- Python 3.12+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- GPU 服务器（通过 SSH 访问，用于实验执行）
- （可选）[OpenAI Codex CLI](https://github.com/openai/codex)（启用 Codex 交叉审查时需要）
- （可选）飞书 MCP Server（启用飞书同步时需要）

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/lose4578/sibyl-system.git
cd sibyl-system

# 2. 创建 Python 虚拟环境
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 加载插件

Sibyl 以 **Claude Code Plugin** 形式提供交互命令。启动 Claude Code 时需指定插件目录：

```bash
# 方式一：每次启动时指定（推荐先用此方式体验）
claude --plugin-dir /path/to/sibyl-system/plugin

# 方式二：在 Claude Code settings.json 中持久化配置
# 编辑 ~/.claude/settings.json，添加：
{
  "pluginDirs": ["/path/to/sibyl-system/plugin"]
}
```

> **注意**：将 `/path/to/sibyl-system` 替换为你本地的实际路径。

加载成功后，可以在 Claude Code 中使用 `/sibyl-research:*` 系列命令。

### 使用

在 Claude Code 中通过插件命令操作：

```bash
/sibyl-research:init       # 交互式初始化新研究项目（生成 spec.md）
/sibyl-research:start      # 启动研究（自动进入持续迭代循环）
/sibyl-research:status     # 查看所有项目状态
/sibyl-research:continue   # 恢复已有项目
/sibyl-research:debug      # 单步执行（调试模式，手动推进每个阶段）
/sibyl-research:pivot      # 强制切换研究方向
/sibyl-research:stop       # 停止研究并关闭循环
/sibyl-research:sync       # 手动同步数据到飞书
/sibyl-research:evolve     # 跨项目进化分析，提取可复用模式
```

### SSH 服务器配置

实验执行依赖 SSH 连接到 GPU 服务器。需要配置 [SSH MCP Server](https://github.com/anthropics/claude-code)：

1. 确保 `~/.ssh/config` 中配置了目标服务器（如 `Host cs8000d`）
2. 在项目的 `config.yaml` 中设置：

```yaml
ssh_server: "your-gpu-server"
remote_base: "/path/to/remote/workspace"
gpu_ids: [0, 1, 2, 3]
```

### 配置

创建 `workspaces/<project>/config.yaml` 覆盖默认配置：

```yaml
# GPU 配置
gpu_ids: [0, 1, 2, 3]
gpus_per_task: 1

# 写作模式: sequential | parallel | codex
writing_mode: parallel

# 实验模式: ssh_mcp | server_codex | server_claude
experiment_mode: ssh_mcp

# Codex 独立审查
codex_enabled: true

# 飞书同步
lark_enabled: true

# 迭代控制
idea_exp_cycles: 6        # 最大 PIVOT 次数
writing_revision_rounds: 2 # 最大写作修改轮数
debate_rounds: 2           # 辩论轮数
```

## 关键机制

### GPU 并行调度

实验阶段读取 `task_plan.json`，按任务依赖关系进行拓扑排序，再根据可用 GPU 数量贪心分配并行执行：

```json
{
  "tasks": [
    {"id": "train_baseline", "depends_on": [], "gpu_count": 2, "estimated_minutes": 60},
    {"id": "train_model_a", "depends_on": ["train_baseline"], "gpu_count": 1, "estimated_minutes": 90},
    {"id": "train_model_b", "depends_on": ["train_baseline"], "gpu_count": 1, "estimated_minutes": 90},
    {"id": "ablation", "depends_on": ["train_model_a", "train_model_b"], "gpu_count": 1, "estimated_minutes": 30}
  ]
}
```

### 跨项目进化学习

系统自动从每轮迭代中提取教训，追踪有效性，并将验证过的改进注入 Agent 提示词：

1. **记录**：每轮反思后记录问题分类（7 类）和成功模式
2. **分析**：聚合出现频率，按时间衰减（半衰期 30 天）加权
3. **评估**：比较早期 vs 晚期分数，标记教训有效性（需 ≥4 次出现）
4. **应用**：生成 Agent 专属的提示词 overlay，无效教训降权（×0.3）
5. **自检**：检测质量下降、反复错误、无效教训等异常

### PIVOT 机制

当实验结果不理想时，监督决策 Agent 可触发 PIVOT：

- 分析结果是否支持原始假设
- 评估是否值得继续投入
- 若决定 PIVOT，回退到创意辩论阶段，使用备选方案
- 最多允许 6 次 PIVOT 循环（可配置）

## 依赖

- **PyYAML** ≥ 6.0 — 配置文件解析
- **rich** ≥ 13.0 — 终端格式化输出

## 许可证

私有项目，保留所有权利。
