#!/usr/bin/env python3
"""Validate the tiny remote parallel smoke demo workspace."""

from __future__ import annotations

import argparse
import json
import sys

from sibyl.demo import validate_remote_parallel_smoke


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace")
    args = parser.parse_args()

    result = validate_remote_parallel_smoke(args.workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
