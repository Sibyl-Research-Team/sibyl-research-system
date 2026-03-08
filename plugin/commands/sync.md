---
description: "手动同步研究项目数据到飞书"
argument-hint: "<project>"
---

# /sibyl-research:sync

手动同步到飞书。

**所有用户可见的输出必须使用中文。**

工作目录: 项目根目录（通过 $SIBYL_ROOT 或 cd 到 clone 位置）

参数: `$ARGUMENTS`（项目名称）

执行步骤：

1. 确定 workspace 路径：`workspaces/$ARGUMENTS`
2. 调用 `/sibyl-lark-sync` skill，传入 workspace 路径
3. 报告同步结果（成功/失败项、飞书链接）
