---
description: "跨项目进化分析，提取可复用模式"
---

# /sibyl-research:evolve

跨项目进化分析。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

## 步骤 1: 分析模式并生成 overlay

执行以下命令：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.evolution import EvolutionEngine; e = EvolutionEngine(); insights = e.analyze_patterns(); written = e.run_cross_project_evolution(); print(f'发现 {len(insights)} 个模式, {len(written)} 个 overlay 更新')"
```

## 步骤 2: 如果进化过程修改了系统文件（CRITICAL）

如果本次进化修改了 `sibyl/`、`sibyl/prompts/`、`plugin/`、`.claude/` 下的任何系统文件（不包括 `.sibyl/evolution/lessons/` 下的 overlay 文件，以及由 `SIBYL_STATE_DIR` / `SIBYL_EVOLUTION_DIR` 重定向的运行时 overlay 文件），**必须**执行以下安全流程：

1. **编写测试**: 为修改的系统代码在 `tests/` 中添加对应测试用例
2. **运行测试**:
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -m pytest tests/ -v
   ```
3. **验证通过**: 确保所有测试通过。如有失败，修复后重新运行
4. **Git 提交**:
   ```bash
   git add <修改的文件> && git commit -m "feat: self-evolution - <改进描述>"
   git push
   ```

**禁止**在测试未通过的情况下提交系统文件修改。Git 历史是系统进化的审计轨迹。
