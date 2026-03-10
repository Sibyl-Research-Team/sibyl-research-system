#!/usr/bin/env bash
set -euo pipefail

REMOTE_BASE=/home/ccwang/sibyl_system
PROJECT_NAME=demo-smoke

mkdir -p "$REMOTE_BASE/shared/checkpoints" "$REMOTE_BASE/shared/datasets" "$REMOTE_BASE/projects/$PROJECT_NAME"
ln -sfn /home/ccwang/sibyl_system/models/gpt2 /home/ccwang/sibyl_system/shared/checkpoints/gpt2_local
ln -sfn /home/ccwang/sibyl_system/models/Qwen2.5-1.5B-Instruct /home/ccwang/sibyl_system/shared/checkpoints/qwen2_5_1_5b_instruct_local

python3 - <<'PY'
import json
from pathlib import Path

registry_path = Path('/home/ccwang/sibyl_system') / "shared" / "registry.json"
registry_path.parent.mkdir(parents=True, exist_ok=True)
if registry_path.exists():
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
else:
    data = {}

patch = json.loads('{"checkpoints": {"gpt2_local": {"type": "checkpoint", "name": "gpt2", "path": "shared/checkpoints/gpt2_local", "target": "/home/ccwang/sibyl_system/models/gpt2", "source": "preexisting_remote_weight", "demo": "demo-smoke"}, "qwen2_5_1_5b_instruct_local": {"type": "checkpoint", "name": "Qwen2.5-1.5B-Instruct", "path": "shared/checkpoints/qwen2_5_1_5b_instruct_local", "target": "/home/ccwang/sibyl_system/models/Qwen2.5-1.5B-Instruct", "source": "preexisting_remote_weight", "demo": "demo-smoke"}}}')
for section, items in patch.items():
    bucket = data.setdefault(section, {})
    bucket.update(items)

registry_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "Remote smoke demo bootstrap complete for $PROJECT_NAME"
echo "Shared checkpoints:"
echo "  - shared/checkpoints/gpt2_local -> /home/ccwang/sibyl_system/models/gpt2"
echo "  - shared/checkpoints/qwen2_5_1_5b_instruct_local -> /home/ccwang/sibyl_system/models/Qwen2.5-1.5B-Instruct"
