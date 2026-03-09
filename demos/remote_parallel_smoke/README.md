# Remote Parallel Smoke Demo

这是一个为 Sibyl 固化的**极小型真实场景 demo**。它不追求论文效果，只追求把以下链路完整跑通：

- 远程 SSH 实验执行
- GPU 轮询与 experiment monitor
- 至少 2 个可并行实验 task
- 多 agent 讨论 / 写作
- 图表、论文、LaTeX 与 PDF 产出

## 默认资源

这个 demo 默认针对当前开发机上的远程服务器配置：

- SSH server: `__SSH_SERVER__`
- Remote base: `__REMOTE_BASE__`
- Remote conda path: `__REMOTE_CONDA_PATH__`
- GPT-2 source: `__GPT2_SOURCE_PATH__`
- Qwen2.5-1.5B-Instruct source: `__QWEN_SOURCE_PATH__`

如果远程环境变化，可以在 scaffold 时覆盖这些参数。

## 快速开始

在仓库根目录执行：

```bash
.venv/bin/python3 scripts/scaffold_remote_demo.py
```

它会生成一个工作区，并写入：

- `spec.md`
- `config.yaml`
- `shared/demo_prompts.jsonl`
- `shared/remote_bootstrap.sh`
- `shared/remote_registry_patch.json`

## 远程准备

先在远程服务器执行生成好的 `shared/remote_bootstrap.sh`，让 demo 所需的现有权重注册成共享 checkpoint。

脚本会：

1. 创建 `shared/checkpoints/`
2. 把现有模型挂到：
   - `shared/checkpoints/gpt2_local`
   - `shared/checkpoints/qwen2_5_1_5b_instruct_local`
3. 写入或更新 `shared/registry.json`

## 运行

```bash
/sibyl-research:start remote-parallel-smoke
```

## 验证

运行完成后可用：

```bash
.venv/bin/python3 scripts/validate_remote_demo.py workspaces/remote-parallel-smoke
```

验证器会检查：

- demo scaffold 文件是否存在
- `task_plan.json` 是否至少有 2 个并行 task
- `gpu_progress.json` 是否记录了至少 2 个完成 task
- 论文、review、LaTeX、PDF、reflection 是否产出
