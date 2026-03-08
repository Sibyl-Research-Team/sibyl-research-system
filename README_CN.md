# Sibyl System（西比拉系统）

**全自主 AI 科研系统，具备自我进化能力**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 受 [The AI Scientist](https://github.com/SakanaAI/AI-Scientist)、[FARS](https://analemma.ai/blog/introducing-fars/) 和 [AutoResearch](https://github.com/karpathy/autoresearch) 等先驱工作的启发，Sibyl 在此基础上更进一步，原生构建于 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 之上，充分利用其 Agent 生态——Skills、Plugins、MCP Servers 和多 Agent 团队。

[English](README.md)

Sibyl 是一个**全自动科学发现系统**，能自主驱动从文献调研到论文投稿的完整 ML 研究流程——并通过从每次迭代中学习来**自我进化**。它不是辅助人类研究者的工具，而是一个**自主运转的研究组织**：20+ 个专业化 AI Agent 在辩论中碰撞想法、设计并执行 GPU 实验、撰写论文、严格自我审查——全程无需人工干预。

### 为什么选择 Sibyl？

- **Claude Code 原生架构** — 不是 API 调用的封装。直接构建在 Claude Code 架构上（fork skills、agent teams、MCP tools），天然继承其完整生态：SSH 远程执行、Playwright 浏览器自动化、飞书云同步等。
- **自我进化** — 系统从自身的研究迭代中学习。自动分类问题、追踪经验有效性、降权无效经验、将验证有效的改进注入 Agent Prompt。每个项目都让系统变得更强。
- **全自主闭环** — 给定研究方向，然后放手。Sibyl 处理文献检索、多视角创意辩论、实验规划、GPU 并行执行、结果分析、论文写作、同行级评审和质量门控迭代——循环直到研究达到发表标准。

---

## 系统概览

Sibyl 通过 **19 阶段状态机 Pipeline** 编排 20+ 个 AI Agent，自动完成文献调研、创意生成、实验设计与执行、结果分析、论文写作和同行评审。系统支持多轮迭代优化，内置跨项目学习机制持续提升研究质量。

![Sibyl 系统架构](image/sibyl_architecture.png)

### 核心特性

- **19 阶段研究 Pipeline**：从文献检索到 camera-ready 论文的端到端自动化
- **多 Agent 协作**：6 Agent 创意辩论、6 Agent 结果分析、6 Agent 并行写作
- **GPU 并行调度**：拓扑排序 + 贪心分配，自动管理任务依赖和 GPU 资源
- **迭代优化闭环**：质量门控自动判定继续迭代或终止，PIVOT 机制可切换研究方向
- **跨项目自我进化**：自动提取经验、追踪有效性、生成 Agent Prompt 改进
- **多模型协作**：Claude Opus/Sonnet + GPT-5.4 (Codex) 独立交叉审查

## Pipeline 流程

```
+== 研究迭代 ====================+  +== 论文写作 =======================+
|                                 |  |                                   |
|  文献检索 (arXiv + Web)         |  |  大纲                              |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  创意辩论 (6 Agent)             |  |  章节写作 (顺序/并行/Codex)        |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  实验规划                       |  |  交叉评审 (6 Agent)                |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  先导实验                       |  |  整合编辑                          |
|       |                         |  |       |                           |
|       v                         |  |       v                           |
|  完整实验 (GPU 并行)            |  |  终审 (NeurIPS 级别)               |
|       |                         |  |       | 不通过 --> 返回编辑 (x2)   |
|       v                         |  |       v                           |
|  结果辩论 (6 Agent)             |  |  LaTeX --> 编译 PDF                |
|       |                         |  |       |                           |
|       v                         |  +-------|---------+-----------------+
|  决策                           |          |
|       | PIVOT --> 回到创意      |          |
|       | PROCEED                 |          v
+-------|-----------+------------+  +== 审查与反思 =====================+
        |                           |                                     |
        +----------> 大纲           |  审查 (Critic+Supervisor+Codex)     |
                                    |       |                             |
                                    |       v                             |
                                    |  反思 (提取经验教训)                |
                                    |       |                             |
                                    |       v                             |
                                    |  飞书同步 (云文档)                  |
                                    |       |                             |
                                    |       v                             |
                                    |  质量门控                           |
                                    |       | >= 8.0 且 >= 2轮 --> 完成   |
                                    |       | 否则 --> 下一轮迭代         |
                                    |                                     |
                                    +-------------------------------------+
```

### 各阶段详情

| 阶段 | 描述 | Agent 模式 |
|------|------|-----------|
| `literature_search` | arXiv + Web 双源文献调研 | 单 Agent |
| `idea_debate` | 6 视角创意辩论（创新者/实用主义者/理论家/反对者/跨学科/实验主义者） | 6-Agent 团队 |
| `planning` | 设计实验方案，生成含依赖关系的 task_plan.json | 单 Agent |
| `pilot_experiments` | 小规模可行性验证 | 单 Agent |
| `experiment_cycle` | GPU 并行完整实验，拓扑排序分批调度 | 单 Agent + GPU 调度器 |
| `result_debate` | 6 视角结果分析（乐观者/怀疑者/战略家/方法论者/比较者/修正者） | 6-Agent 团队 |
| `experiment_decision` | 监督决策：PIVOT（换方向）或 PROCEED（继续） | 单 Agent |
| `writing_outline` | 生成论文大纲 | 单 Agent |
| `writing_sections` | 分章节写作（顺序/并行/Codex 模式） | 可配置 |
| `writing_critique` | 6 Agent 交叉评审各章节 | 6-Agent 并行 |
| `writing_integrate` | 编辑整合为完整论文 | 单 Agent |
| `writing_final_review` | NeurIPS/ICML 级别终审（可循环修改） | 单 Agent |
| `writing_latex` | 转换为 NeurIPS LaTeX 格式并编译 PDF | 单 Agent |
| `review` | Critic + Supervisor + Codex 并行审查 | 并行 Skills |
| `reflection` | 分类问题、生成改进计划、记录经验 | 单 Agent |
| `lark_sync` | 同步研究数据到飞书云文档 | 单 Agent |
| `quality_gate` | 评估完成度（≥8.0 分 且 ≥2 轮迭代） | 自动 |

## Agent 角色

### 创意生成团队

| Agent | 视角 | 职责 |
|-------|------|------|
| 创新者 | 跨领域创新 | 大胆的方法论迁移和新颖组合 |
| 实用主义者 | 工程可行性 | 确保想法可落地实现 |
| 理论家 | 数学基础 | 关注理论保证和证明 |
| 反对者 | 挑战假设 | 寻找反面证据和盲点 |
| 跨学科者 | 类比启发 | 从认知科学、物理、生物等领域引入方法 |
| 实验主义者 | 实验优先 | 关注可复现性和数据质量 |

### 结果分析团队

| Agent | 视角 | 职责 |
|-------|------|------|
| 乐观者 | 积极发现 | 发掘正面结果和扩展方向 |
| 怀疑者 | 统计严谨性 | 质疑统计显著性和混淆因素 |
| 战略家 | 下一步行动 | 建议资源分配和研究方向 |
| 方法论者 | 方法审查 | 评估内外部效度 |
| 比较者 | SOTA 对标 | 与现有最佳方法对比定位 |
| 修正者 | 假设修正 | 基于结果反思和调整假设 |

### 模型层级

| 层级 | 模型 | 用途 |
|------|------|------|
| Heavy | Opus 4.6 | 综合决策、监督、编辑、批评、反思 |
| Standard | Opus 4.6 | 文献调研、规划、实验、写作 |
| Light | Sonnet 4.6 | 结果辩论、交叉评审、章节批评 |
| Codex | GPT-5.4 High | 独立第三方审查、可选写作模式 |

## 自我进化系统

Sibyl 自动从每次研究迭代中学习，形成持续提升系统性能的反馈闭环：

```
研究迭代
       |
       v
  反思 Agent ──> 记录结果（问题 + 分数 + 成功模式）
       |
       v
  进化引擎 ──> 分类问题（7 大类）
       |              ├── 时间加权频率分析
       |              ├── 有效性追踪（早期 vs 后期分数对比）
       |              └── 成功模式提取
       v
  生成叠加层 ──> 将验证过的经验注入 Agent Prompt
       |              ├── 有效经验：提升优先级
       |              └── 无效经验：0.3x 降权
       v
  自检 ──> 检测异常
              ├── 质量下降趋势
              ├── 反复出现的系统错误
              └── 无效经验堆积
```

**问题分类**：SYSTEM、EXPERIMENT、WRITING、ANALYSIS、PLANNING、PIPELINE、IDEATION —— 每类路由到相关 Agent 进行针对性改进。

## 项目结构

```
sibyl-system/
├── sibyl/                      # 核心 Python 模块
│   ├── orchestrate.py          # 状态机编排器（19 阶段 Pipeline）
│   ├── config.py               # 配置管理（模型/GPU/模式）
│   ├── workspace.py            # 工作区文件与 Git 管理
│   ├── gpu_scheduler.py        # GPU 拓扑排序与并行调度
│   ├── evolution.py            # 跨项目进化引擎
│   ├── reflection.py           # 迭代日志
│   └── prompts/                # 32 个 Agent Prompt 模板
├── .claude/
│   ├── agents/                 # Agent 层级定义（heavy/standard/light）
│   └── skills/sibyl-*/         # 30+ Fork Skills（隔离上下文执行）
├── plugin/commands/            # Claude Code 插件命令
├── workspaces/                 # 研究项目工作区
├── tests/                      # 单元测试（~320 个）
└── requirements.txt            # 依赖（PyYAML, rich）
```

### 工作区结构

每个研究项目在 `workspaces/<project>/` 下拥有独立的文件系统：

```
workspaces/<project>/
├── status.json                 # 编排器状态（阶段/迭代/分数）
├── config.yaml                 # 项目级配置覆盖
├── topic.txt / spec.md         # 研究主题与需求规格
├── context/literature.md       # 文献综述
├── idea/                       # 提案、备选方案、辩论记录
├── plan/                       # 实验方案、task_plan.json
├── exp/                        # 代码、结果、日志、GPU 进度
├── writing/                    # 大纲、章节、评审、完整论文、LaTeX
├── logs/                       # 迭代归档、研究日志
└── lark_sync/                  # 飞书同步注册表
```

## 快速开始

### 环境要求

- Python 3.12+、Node.js 18+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- GPU 服务器（SSH 可达）
- `ANTHROPIC_API_KEY` 环境变量
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 环境变量

### 安装与运行

```bash
git clone https://github.com/Sibyl-Research/sibyl-research-system.git
cd sibyl-research-system
chmod +x setup.sh && ./setup.sh

# 加载插件
claude --plugin-dir ./plugin

# 在 Claude Code 中:
/sibyl-research:init              # 创建研究项目
/sibyl-research:start <project>   # 启动自主循环
```

完整安装指南见 **[快速上手](docs/getting-started.md)**。

### 语言设置

系统默认使用英文输出。如需切换为**中文模式**（Agent 输出、日志、中间产物、控制台消息全部使用中文），可在以下位置配置：

```yaml
# 全局默认：config.yaml（项目根目录，不提交到 Git）
language: zh

# 或按项目配置：workspaces/<project>/config.yaml
language: zh
```

根目录 `config.yaml` 设置本机全局默认值，项目级 `config.yaml` 可覆盖。论文正文（paper.md、LaTeX）始终使用英文撰写，不受此设置影响。详见[配置参考](docs/configuration.md)。

## 文档

| 文档 | 说明 |
|------|------|
| [快速上手](docs/getting-started.md) | 完整安装与首次运行指南 |
| [配置参考](docs/configuration.md) | 全部 35+ 配置项参考 |
| [MCP 服务](docs/mcp-servers.md) | 第三方 MCP 依赖安装与配置 |
| [SSH 与 GPU 配置](docs/ssh-gpu-setup.md) | GPU 服务器环境配置 |
| [插件命令](docs/plugin-commands.md) | 全部 12 个插件命令参考 |
| [Codex 集成](docs/codex-integration.md) | GPT-5.4 交叉审查配置 |
| [飞书同步](docs/feishu-lark-setup.md) | 飞书云文档同步配置 |
| [系统架构](docs/architecture.md) | 系统内部实现（贡献者参考） |

## 第三方依赖

### MCP 服务

| 服务 | 必需 | 用途 | 来源 |
|------|------|------|------|
| SSH MCP | 是 | 远程 GPU 执行 | Claude Code 内置 |
| arXiv MCP | 是 | 论文搜索 | `pip install arxiv-mcp-server` |
| Google Scholar MCP | 推荐 | 学术引用搜索 | 社区实现 |
| Codex MCP | 可选 | GPT-5.4 审查 | [OpenAI Codex CLI](https://github.com/openai/codex) |
| Lark MCP | 可选 | 飞书 Bitable/IM | `@larksuiteoapi/lark-mcp` |
| Feishu MCP | 可选 | 飞书文档操作 | 社区实现 |
| bioRxiv MCP | 可选 | 生物预印本 | 社区实现 |

完整安装与 `~/.mcp.json` 配置见 **[MCP 服务指南](docs/mcp-servers.md)**。

### Python 依赖

- **PyYAML** >= 6.0 — 配置文件解析
- **rich** >= 13.0 — 终端格式化输出

### 可选工具

- [OpenAI Codex CLI](https://github.com/openai/codex) — 独立交叉审查（`codex_enabled: true`）
- [Ralph Loop](https://github.com/anthropics/claude-code) — 自主迭代循环（Claude Code 插件）

## 核心机制

### GPU 并行调度

实验阶段读取 `task_plan.json`，按依赖关系拓扑排序，然后根据可用 GPU 贪心分配并行执行：

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

### 跨项目自我进化

系统自动从每次迭代中提取经验，追踪有效性，将验证过的改进注入 Agent Prompt：

1. **记录**：每次反思后，分类问题（7 大类）和成功模式
2. **分析**：时间衰减加权聚合频率（30 天半衰期）
3. **评估**：对比早期和后期分数，标记经验有效性（需 >= 4 次出现）
4. **应用**：生成 Agent 专属的 Prompt 叠加层；无效经验降权（x0.3）
5. **自检**：检测质量下降、反复系统错误和无效经验堆积

### PIVOT 机制

当实验结果不理想时，监督决策 Agent 可触发 PIVOT：

- 分析结果是否支持原始假设
- 评估是否值得继续投入
- 若 PIVOT：回退到创意辩论阶段，携带备选方案
- 最多 6 次 PIVOT 循环（可配置）

## 横向对比

| 特性 | Sibyl System | [AI Scientist](https://github.com/SakanaAI/AI-Scientist) | [AutoResearch](https://github.com/karpathy/autoresearch) |
|------|-------------|-------------|--------------|
| 架构 | Claude Code 原生（skills, teams, MCP） | API 封装 | 单文件脚本 |
| Agent 数量 | 20+ 专业化 Agent | 单个 LLM | 单 Agent |
| 创意生成 | 6 Agent 多视角辩论 | LLM 头脑风暴 | 无 |
| 实验执行 | GPU 并行 + 拓扑排序调度 | 模板化执行 | 单 GPU 循环 |
| 论文写作 | 多 Agent 写作 + 评审 + 修改 | LLM 生成 | 无 |
| 自我进化 | 跨项目经验学习 | 无 | 无 |
| 质量控制 | 多轮审查 + 质量门控 | 自动审查 | 基于指标 |
| 人工干预 | 全自主 | 极少 | 极少 |

## 许可证

MIT License
