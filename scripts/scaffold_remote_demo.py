#!/usr/bin/env python3
"""Scaffold the tiny remote parallel smoke demo workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sibyl.demo import RemoteParallelSmokeDemo, scaffold_remote_parallel_smoke


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", default="remote-parallel-smoke")
    parser.add_argument("--workspaces-dir", default="workspaces")
    parser.add_argument("--ssh-server", default="default")
    parser.add_argument("--remote-base", default="/home/ccwang/sibyl_system")
    parser.add_argument("--remote-conda-path", default="/home/ccwang/miniforge3/bin/conda")
    parser.add_argument("--gpt2-source-path", default="/home/ccwang/sibyl_system/models/gpt2")
    parser.add_argument(
        "--qwen-source-path",
        default="/home/ccwang/sibyl_system/models/Qwen2.5-1.5B-Instruct",
    )
    args = parser.parse_args()

    spec = RemoteParallelSmokeDemo(
        project_name=args.project_name,
        workspaces_dir=Path(args.workspaces_dir),
        ssh_server=args.ssh_server,
        remote_base=args.remote_base,
        remote_conda_path=args.remote_conda_path,
        gpt2_source_path=args.gpt2_source_path,
        qwen_source_path=args.qwen_source_path,
    )
    print(json.dumps(scaffold_remote_parallel_smoke(spec), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
