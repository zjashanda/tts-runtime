#!/bin/sh
# tools/time-lint.sh —— 时间契约 lint 薄封装，见 tools/time_lint.py
set -u
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/time_lint.py" "$@"
