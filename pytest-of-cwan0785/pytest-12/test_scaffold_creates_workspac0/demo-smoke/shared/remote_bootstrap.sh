#!/usr/bin/env bash
set -euo pipefail

REMOTE_BASE=/remote/base
PROJECT_NAME=demo-smoke

mkdir -p "$REMOTE_BASE/shared/checkpoints" "$REMOTE_BASE/shared/datasets" "$REMOTE_BASE/projects/$PROJECT_NAME"
ln -sfn /models/gpt2 /remote/base/shared/checkpoints/gpt2_local
ln -sfn /models/qwen /remote/base/shared/checkpoints/qwen2_5_1_5b_instruct_local

python3 - <<'PY'
import json
from pathlib import Path

registry_path = Path('/remote/base') / "shared" / "registry.json"
registry_path.parent.mkdir(parents=True, exist_ok=True)
if registry_path.exists():
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
else:
    data = {}

patch = json.loads('{"checkpoints": {"gpt2_local": {"type": "checkpoint", "name": "gpt2", "path": "shared/checkpoints/gpt2_local", "target": "/models/gpt2", "source": "preexisting_remote_weight", "demo": "demo-smoke"}, "qwen2_5_1_5b_instruct_local": {"type": "checkpoint", "name": "Qwen2.5-1.5B-Instruct", "path": "shared/checkpoints/qwen2_5_1_5b_instruct_local", "target": "/models/qwen", "source": "preexisting_remote_weight", "demo": "demo-smoke"}}}')
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
echo "  - shared/checkpoints/gpt2_local -> /models/gpt2"
echo "  - shared/checkpoints/qwen2_5_1_5b_instruct_local -> /models/qwen"
