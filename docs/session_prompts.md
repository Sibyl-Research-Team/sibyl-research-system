# 会话历史 Prompt 记录

> 提取自会话 `e83a2dd5-4ee6-48d8-849c-3577c66ede72.jsonl`
> 提取日期：2026-03-07

---

## Prompt #1
https://gitlab.com/fars-a 你去看看这个仓，这么多能串起来么，你能用么，能实现https://analemma.ai/blog/introducing-fars/他宣传的这样么

## Prompt #2
你能参考他的思路搞一个这样的 pipeline 流程么，要用到多 agent 提升效率，你可以根据情况自己搞些 skill、plugin 之类的优化流程和提升效率

## Prompt #3（系统通知）
Background command "Run FARS pipeline with CLAUDECODE unset to allow nested sessions" completed (exit code 0)

## Prompt #4-#9（/plugin 命令，共6次）
/plugin

## Prompt #10（ralph-loop:help）
ralph-loop:help

## Prompt #11
Unknown skill: r

## Prompt #12
我要怎么用它布置任务

## Prompt #13
Unknown skill: ralph-loop

## Prompt #14（首次 Ralph Loop 启动 + 主任务 Prompt）
/ralph-loop:ralph-loop
现在帮我持续迭代改进以下几个任务
对于FARS Pipeline的流程上： 1. 持续改进FARS Pipeline，要勤用网络上现有的 mcp、plugin、skill、现成的工具和包等，来持续改进优化整个 pipeline 2. 要根据实际研究过程中出现的报错、问题来优化FARS Pipeline，使其更加完善完备 3. 要善用 agent，思考如何拆分任务，如何写agent 的 prompt，如何协调 agent 的分工能让整个pipeline 更顺更好 4. 当每次研究流程走完后，要有反思过程，要修复改正流程中错误、失败、不好的地方，要将好的经验固化成流程保留下来，持续改进流程 5. 整个流程中应该有单独的监督 agent 以第三方视角来审视流程，提出反思视角和建议 6. 每次系统迭代后都要留存日志，以说明本次迭代改进了哪些方面

FARS Pipeline的细节上： 1. 当给出研究方向后，不仅要搜集相关领域的代码、资料和论文，也要在写作的时候学习他们的写作结构、写作风格和写作逻辑，以及整体思路设计、实验设计等 2. 当给出研究方向后要探究哪些方向是可行的，要对 idea 进行反复迭代
3. 要设置批判者，对各个环节挑刺，以提升最终研究的质量 4. 每次迭代文章后，都要留存日志，以说明本次迭代改进了哪些方面

然后我们来用一个新的研究课题进行研究，反复迭代推进这个项目，并利用它来迭代改进FARS Pipeline
主题： 将 mask diffusion Language model 与 test time training 结合起来 1. mask diffusion Language model 即 mdlm/dlm，是类似 llada 的模型：https://arxiv.org/abs/2502.09992 2. 去找最新的但是小一点的，类似3/4b 这样的，方便快速实验验证。同时要去找最新的模型，跟上行业进展 3. ttt 参考：https://arxiv.org/html/2501.00663v1，你还应该去找最新的相关领域论文，看看最新进展 4. 我的想法是将 ttt 应用到 dlm 上，因为 dlm 有反复迭代过程，看能否与 ttt 相结合，但也不用拘泥于我的 idea，任何合理的你觉得可行的有潜力好的 idea 都可以 5. 实验 setting 最好是 training-free，或者是只需要很少的训练代价就能实现，方便我们反复迭代，因为 gpu 资源有限
  关于实验，我配置了 ssh mcp 服务，你现在能连接到cs8000d，用上面的 gpu 跑实验，你可以用 hfd 从 huggingface 上下载所需的权重和数据，所有相关内容都要放在/home/ccwang/fars_pipeline中，不要去动别的文件夹中的内容和文件。gpu 最多只能用 4 张，只能用空闲着没人用的 gpu，避免干扰他人。

## Prompt #15（上下文续接 Summary #1）
> 系统自动注入的上下文 Summary，涵盖：初始 FARS 仓库分析、pipeline 构建、Ralph Loop 设置、研究方向选定等。

## Prompt #16（重启 Ralph Loop + 同一主任务 Prompt）
/ralph-loop:ralph-loop
（内容同 Prompt #14）

## Prompt #17
先把ralph loop 的问题修了

## Prompt #18
恢复 ralph loop的修改，我重新给 prompt

## Prompt #19
恢复 ralph loop的修改，我重新给 prompt

## Prompt #20（正式重启 Ralph Loop，带参数）
/ralph-loop:ralph-loop "（同 Prompt #14 内容）" --max-iterations 20

## Prompt #21（上下文续接 Summary #2）
> 系统自动注入的上下文 Summary，涵盖：FARS Pipeline v3 架构、dllm 框架、TTT-DLM 方案设计、supervisor/critic agent 创建等。

## Prompt #22（上下文续接 Summary #3）
> 系统自动注入的上下文 Summary，涵盖：ReMask-Retry 实验（PPL-Diversity Tradeoff 发现）、v3-v5 代码版本、实验结果汇总等。

## Prompt #23（上下文续接 Summary #4）
> 系统自动注入的上下文 Summary，涵盖：cross-eval（GPT-2 评估）、multi-model（8B LLaDA 测试）、temperature 消融、PPL 假象发现等。

## Prompt #24（上下文续接 Summary #5）
> 系统自动注入的上下文 Summary，涵盖：Phase 2 TCR on Dream-7B、v1/v2/v3 实验、温度为核心发现、parallel_vote 未完成等。

## Prompt #25
ralph-loop:cancel-ralph

## Prompt #26
将我在 loop 过程中发送给你的所有 prompt 汇总下

## Prompt #27
去找当前会话的所有历史记录，将原始 prompt 都给我，我自己总结

---

## 备注

中间被上下文压缩（compaction）丢弃的用户交互 prompt（在 Summary 中有引用但原文不在 JSONL 中）：

1. **"现在 ralph loop 运行到第几轮了"** — 询问迭代轮次
2. **"/agents"** — 查看 agent 状态
3. **"/status"** — 查看整体状态
4. **"充分利用 gpu 资源，改进 fars 系统，看哪些任务能并行 agent 处理，提高利用率"**
5. **"现在怎么没有 latex 文件以及写好的 pdf 文件"** + **"每轮的迭代日志在哪里"**
6. **系统改进建议（大段）：**
   > 1. 写作也要有多个 agent（写手+批判者）
   > 2. 研究项目 insight 或者 idea 可以更加发散点（多风格 Agent 讨论）
   > 3. 实验编排上要充分利用 gpu 资源，避免空闲
   > 4. 当进行反复迭代研究时，pipeline 要优化避免空转
   > 5. 我们能够接受小型的需要训练的实验
   > 6. 各个项目迭代时各个相关文件数据等要分门别类归纳好，别乱套
7. **"系统改进：在研究项目推进时，各个环境的讨论、结论、实验结果、分析等研究过程中完整的流程细节，也要写成文档保存下来，记得要用中文写"**
