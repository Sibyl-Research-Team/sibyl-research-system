---
description: "跨项目进化分析，提取可复用模式"
---

# /sibyl-research:evolve

跨项目进化分析。

**所有用户可见的输出必须使用中文。**

执行以下命令：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.evolution import EvolutionEngine; e = EvolutionEngine(); insights = e.analyze_patterns(); written = e.run_cross_project_evolution(); print(f'发现 {len(insights)} 个模式, {len(written)} 个 overlay 更新')"
```
