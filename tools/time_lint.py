#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间契约 lint —— 统一北京时间无时区格式 ``YYYY-MM-DD HH:MM:SS``。

规则来源（全工作区统一口径）：
    所有用户可见/机器可读的日志、JSON、回执与文档示例，时间一律写成
    ``YYYY-MM-DD HH:MM:SS``（北京时间，无时区后缀）。不得出现 ISO ``T`` 分隔、
    ``Z`` 后缀、``+08:00`` 之类偏移、亚秒位变体，也不得在 schema 里使用
    date-time 格式（那等价于 RFC3339），应改用 pattern。

    外部系统给的原始时间只允许放在显式的 ``raw_*`` 字段里，且必须经
    ``tts_runtime.util.parse_raw_time`` 归一化后再输出。

用法：
    python3 tools/time_lint.py                # 扫描并打印违规，退出 0
    python3 tools/time_lint.py --gate         # 有违规退出 1（CI 用）
    python3 tools/time_lint.py --self-test    # 自检规则本身有效
    python3 tools/time_lint.py --json         # 机器可读输出

单行豁免：在该行任意位置写 ``time-lint:allow``，仅对该行生效。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent

ALLOW_MARK = "time-lint:allow"

TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".sh", ".ps1", ".cmd", ".txt",
    ".toml", ".yml", ".yaml", ".cfg", ".ini", ".jsonl",
}

SKIP_DIRS = {
    ".git", "__pycache__", ".mypy_cache", ".pytest_cache",
    "build", "dist", "node_modules", ".venv", "venv", "env",
    "vendor", "models", "nltk_data", "outputs", ".egg-info",
}


class Rule(NamedTuple):
    name: str
    pattern: "re.Pattern[str]"
    hint: str


RULES: Sequence[Rule] = (
    Rule(
        "iso-t-separator",
        re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),
        "时间里的 T 分隔符：改成空格",
    ),
    Rule(
        "iso-z-suffix",
        re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\b"),
        "Z 后缀：去掉，改北京时间无后缀",
    ),
    Rule(
        "iso-offset",
        re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?[+-]\d{2}:?\d{2}\b"),
        "时区偏移：去掉，改北京时间无后缀",
    ),
    Rule(
        "subsecond",
        re.compile(r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+"),
        "亚秒位：契约只到秒",
    ),
    Rule(
        "schema-date-time",
        re.compile(r'"format"\s*:\s*"date-time"'),
        'JSON Schema 的 date-time 即 RFC3339：改用 pattern',
    ),
    Rule(
        "strftime-t",
        re.compile(r"%Y-%m-%dT|%H:%M:%S%z|%H:%M:%S\.%f"),  # time-lint:allow 规则定义本身
        "strftime 模板输出了非契约格式",
    ),
)


class Violation(NamedTuple):
    path: str
    line: int
    rule: str
    text: str
    hint: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule,
            "text": self.text,
            "hint": self.hint,
        }


def iter_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def scan_text(text: str, path: str = "<text>") -> List[Violation]:
    found: List[Violation] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARK in line:
            continue
        for rule in RULES:
            if rule.pattern.search(line):
                found.append(
                    Violation(path=path, line=number, rule=rule.name, text=line.strip()[:200], hint=rule.hint)
                )
    return found


def scan(root: Optional[Path] = None) -> List[Violation]:
    base = Path(root or ROOT)
    found: List[Violation] = []
    for path in iter_files(base):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(base)).replace("\\", "/")
        found.extend(scan_text(text, rel))
    return found


# 自检样本用拼接构造，避免 lint 扫到本文件时误判为违规，也避免误加豁免标记
# 导致自检失效。
SELF_TEST_CASES = (
    ("2026-11-10" + "T" + "21:46:03", "iso-t-separator"),
    ("2026-11-10" + "T" + "13:46:03" + "Z", "iso-t-separator"),
    ("at 21:46:03" + "Z", "iso-z-suffix"),
    ("at 21:46:03" + "+08:00", "iso-offset"),
    ("at 21:46:03.225", None),
    ("2026-11-10 21:46:03" + ".225", "subsecond"),
    ('"format": ' + '"date-time"', "schema-date-time"),
    ('FORMAT = "%Y-%m-%d' + 'T%H:%M:%S"', "strftime-t"),
    ("2026-11-10 21:46:03", None),
    ('"pattern": "^\\\\d{4}-\\\\d{2}-\\\\d{2} \\\\d{2}:\\\\d{2}:\\\\d{2}$"', None),
    ("# " + ALLOW_MARK + " 2026-11-10" + "T" + "21:46:03", None),
)


def self_test() -> bool:
    ok = True
    for sample, expected in SELF_TEST_CASES:
        hits = [v.rule for v in scan_text(sample)]
        if expected is None:
            if hits:
                print("self-test FAIL: {0!r} 不应命中，实际 {1}".format(sample, hits))
                ok = False
        elif expected not in hits:
            print("self-test FAIL: {0!r} 应命中 {1}，实际 {2}".format(sample, expected, hits))
            ok = False
    if ok:
        print("time-lint self-test: PASS ({0} 个样本)".format(len(SELF_TEST_CASES)))
    return ok


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="时间契约 lint（北京时间无时区 YYYY-MM-DD HH:MM:SS）")
    parser.add_argument("--root", default=str(ROOT), help="扫描根目录（默认仓库根）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--quiet", action="store_true", help="只输出结论")
    parser.add_argument("--self-test", action="store_true", help="自检检测规则")
    parser.add_argument("--gate", action="store_true", help="有违规时退出 1")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test and not self_test():
        return 1
    if args.self_test and not args.gate:
        return 0

    violations = scan(Path(args.root))
    if args.json:
        print(json.dumps({"ok": not violations, "count": len(violations),
                          "violations": [v.to_dict() for v in violations]}, ensure_ascii=False, indent=2))
    elif violations:
        for item in violations:
            print("{0}:{1}: [{2}] {3}".format(item.path, item.line, item.rule, item.text))
        print("time-lint: {0} 处违规".format(len(violations)), file=sys.stderr)
    elif not args.quiet:
        print("time-lint: 0 违规（契约 YYYY-MM-DD HH:MM:SS）")
    if violations and args.gate:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
