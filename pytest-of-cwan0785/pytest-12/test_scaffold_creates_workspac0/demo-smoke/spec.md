# 项目: demo-smoke

## 研究主题
在远程 GPU 服务器上对 GPT-2 与 Qwen2.5-1.5B-Instruct 做极小型并行推理基准，完整验证 Sibyl 的远程实验、GPU 调度、实验监控、写作与 LaTeX 链路。

## 背景与动机
这是一个**基础设施 smoke test**，目标不是追求研究 novelty 或效果上限，而是用一个非常小、但真实使用远程 GPU 与现有权重的项目，把 Sibyl 的完整链路跑通：

- 文献检索与 proposal 生成
- 多 agent 讨论与实验规划
- 远程 SSH 实验执行
- GPU 轮询与 experiment monitor
- 并行 task 调度
- 结果综合、图表生成与论文写作
- LaTeX 模板与 PDF 产出

## 初始想法
- 比较两个远程**已存在**的共享 checkpoint：
  - GPT-2: `shared/checkpoints/gpt2_local`
  - Qwen2.5-1.5B-Instruct: `shared/checkpoints/qwen2_5_1_5b_instruct_local`
- 远程原始权重来源分别是：
  - `/models/gpt2`
  - `/models/qwen`
- 使用固定的极小 prompt 集：`shared/demo_prompts.jsonl`
- 重点评价：
  - latency / tokens per second
  - non-empty answer rate
  - keyword hit rate
  - 失败样例与定性分析

## 关键约束
1. **禁止下载新模型**。必须复用上面两份远程现有权重。
2. 如远程 `shared/registry.json` 或共享 symlink 未准备好，先执行工作区里的 `shared/remote_bootstrap.sh`。
3. `task_plan.json` 中至少要有 **2 个可并行实验 task**，每个 task `gpu_count=1`。
4. `PILOT` 与 `FULL` 都保持 very small，目标是几分钟级完成，而不是长时间训练。
5. 优先做**推理评测**而不是训练；如果需要 warmup，只做极小规模。
6. 必须生成至少 **1 张图** 和 **1 张表**。
7. 所有实验 task 都必须写 DONE marker 和 `gpu_progress.json` 记录。

## 可用资源
- SSH server: `default`
- Remote base: `/remote/base`
- Remote conda path: `/remote/conda/bin/conda`
- Demo 允许最多并行 GPU 数: `2`
- Demo 并行 task 上限: `2`

## 建议的最小实验设计
- Task A: `gpt2_instruction_smoke`
  - 用 GPT-2 在固定 prompt 集上做短文本生成
  - 记录 latency、输出长度、keyword hit rate
- Task B: `qwen_instruction_smoke`
  - 用 Qwen2.5-1.5B-Instruct 在同一 prompt 集上做短文本生成
  - 记录同样指标
- Task C: `analysis_and_visualization`
  - 读取 A/B 的 JSON 结果
  - 生成对比表和至少一张柱状图/折线图

Task A 与 Task B 应该能并行运行；Task C 依赖 A/B 完成后执行。

## 目标产出
- 一份极小型 benchmark 论文草稿
- 至少一张模型对比图
- 至少一张结果表
- 一份对系统基础设施可用性的总结
