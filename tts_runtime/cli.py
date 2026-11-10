"""命令行：``tts-runtime <subcommand>``。

退出码（与 SPEC 一致）：0 OK / 1 USAGE / 2 FAIL / 3 UNSUPPORTED / 4 BACKEND。
默认人类可读摘要；``--json`` 输出契约 JSON（UTF-8，缩进 2，不转义中文）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import __version__, core
from . import util
from .errors import TTSError, UsageError
from .events import EventSink

PROG = "tts-runtime"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="统一 TTS 接口：lstts 云 / melotts 本地 / mock 离线")
    parser.add_argument("--version", action="version", version="{0} {1}".format(PROG, __version__))
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    engines = sub.add_parser("engines", help="列出引擎与可用性")
    engines.add_argument("--json", action="store_true")

    voices = sub.add_parser("voices", help="列出音色")
    voices.add_argument("--engine", default=None, help="lstts|melotts|mock（缺省全部）")
    voices.add_argument("--json", action="store_true")

    synth = sub.add_parser("synth", help="合成一段文本")
    group = synth.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", default=None, help="要合成的文本")
    group.add_argument("--text-file", default=None, help="从文件读文本（utf-8-sig/gb18030/utf-16）")
    out = synth.add_mutually_exclusive_group(required=True)
    out.add_argument("--out", default=None, help="输出 wav 路径")
    out.add_argument("--out-dir", default=None, help="输出目录（自动命名）")
    synth.add_argument("--engine", default="auto", help="auto|lstts|melotts|mock")
    synth.add_argument("--voice", default=None)
    synth.add_argument("--emotion", default=None, help="情感参考音频（仅 lstts）")
    synth.add_argument("--language", default=None, help="ZH|EN（melotts 用）")
    synth.add_argument("--speed", type=float, default=None, help="语速（melotts 用）")
    synth.add_argument("--timeout", type=float, default=None, dest="timeout_s")
    synth.add_argument("--no-validate", action="store_true", help="不因音频校验失败而判失败")
    synth.add_argument("--json", action="store_true")
    synth.add_argument("--events", default=None, help="JSONL 事件流输出路径")

    batch = sub.add_parser("batch", help="按 job 批量合成")
    batch.add_argument("--job", required=True, help="ark.tts-job.v1 文件")
    batch.add_argument("--out-dir", required=True)
    batch.add_argument("--engine", default="auto")
    batch.add_argument("--workers", type=int, default=1)
    batch.add_argument("--json", action="store_true")
    batch.add_argument("--events", default=None)

    inspect = sub.add_parser("inspect", help="音频体检")
    inspect.add_argument("path")
    inspect.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="环境自检")
    doctor.add_argument("--json", action="store_true")

    return parser


def _exit_code_for(result: Any) -> int:
    if getattr(result, "ok", False):
        return util.EXIT_OK
    error = getattr(result, "error", None) or {}
    return util.EXIT_CODES and _code_to_exit(str(error.get("code") or "FAIL"))


def _code_to_exit(code: str) -> int:
    mapping = {
        "OK": util.EXIT_OK,
        "USAGE": util.EXIT_USAGE,
        "FAIL": util.EXIT_FAIL,
        "UNSUPPORTED": util.EXIT_UNSUPPORTED,
        "BACKEND": util.EXIT_BACKEND,
    }
    return mapping.get(str(code).upper(), util.EXIT_FAIL)


def _print_json(payload: Any) -> None:
    sys.stdout.write(util.json_dumps(payload) + "\n")


# ------------------------------------------------------------------ 子命令


def _cmd_engines(args: argparse.Namespace) -> int:
    statuses = core.available_engines()
    if args.json:
        _print_json({"schema": "ark.tts-engines.v1", "engines": [item.to_dict() for item in statuses]})
    else:
        for item in statuses:
            flag = "OK  " if item.available else "MISS"
            print("{0} {1:<8} {2}".format(flag, item.name, item.reason))
    return util.EXIT_OK if any(item.available for item in statuses) else util.EXIT_UNSUPPORTED


def _cmd_voices(args: argparse.Namespace) -> int:
    voices = core.list_voices(args.engine)
    if args.json:
        _print_json({"schema": "ark.tts-voices.v1", "voices": [item.to_dict() for item in voices]})
    else:
        if not voices:
            print("（没有可用音色：检查 TTS_RUNTIME_VOICE_DIR 或 MELOTTS_HOME）")
        for item in voices:
            print("{0:<10} {1:<8} {2}".format(item.name, item.engine, item.kind))
    return util.EXIT_OK


def _cmd_synth(args: argparse.Namespace) -> int:
    if args.text is not None:
        text = args.text
    else:
        path = Path(args.text_file).expanduser()
        if not path.is_file():
            raise UsageError("text-file 不存在: {0}".format(path))
        text = util.read_text(path)
    sink = EventSink(Path(args.events).expanduser() if args.events else None)
    result = core.synthesize(
        text,
        args.out,
        out_dir=args.out_dir,
        engine=args.engine,
        voice=args.voice,
        emotion=args.emotion,
        language=args.language,
        speed=args.speed,
        timeout_s=args.timeout_s,
        validate=not args.no_validate,
        events=sink,
    )
    payload = result.to_dict()
    sink.complete(engine=result.engine, ok=result.ok, audio_path=result.audio_path, error=result.error)
    if args.json:
        _print_json(payload)
    elif result.ok:
        audio = payload.get("audio") or {}
        print(
            "OK  {0} -> {1} ({2}s, {3}Hz/{4}ch){5}".format(
                result.engine,
                result.audio_path,
                audio.get("duration_seconds"),
                audio.get("sample_rate"),
                audio.get("channels"),
                ("  notes: " + "; ".join(result.notes)) if result.notes else "",
            )
        )
    else:
        print("FAIL {0}: {1}".format(result.engine, (result.error or {}).get("message")), file=sys.stderr)
    return _exit_code_for(result)


def _cmd_batch(args: argparse.Namespace) -> int:
    job = core.load_job(args.job)
    sink = EventSink(Path(args.events).expanduser() if args.events else None)
    batch = core.synthesize_batch(job, args.out_dir, engine=args.engine, workers=args.workers, events=sink)
    payload = batch.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(
            "{0} job={1} engine={2} total={3} ok={4} failed={5} -> {6}".format(
                "OK  " if batch.ok else "FAIL",
                batch.job,
                batch.engine,
                len(batch.items),
                batch.succeeded,
                batch.failed,
                batch.out_dir,
            )
        )
        for item in batch.items:
            if not item.ok:
                print(
                    "  - {0}: {1}".format(item.item_id, (item.error or {}).get("message")),
                    file=sys.stderr,
                )
    return util.EXIT_OK if batch.ok else util.EXIT_FAIL


def _cmd_inspect(args: argparse.Namespace) -> int:
    report = core.inspect_audio(args.path)
    if args.json:
        _print_json(report)
    else:
        audio = report.get("audio") or {}
        print(
            "{0} {1} {2}Hz/{3}ch/{4}s peak={5}dBFS mean={6}dB".format(
                "OK  " if report["ok"] else "FAIL",
                report["path"],
                audio.get("sample_rate"),
                audio.get("channels"),
                audio.get("duration_seconds"),
                audio.get("peak_dbfs"),
                audio.get("mean_db"),
            )
        )
        for line in report["fatal"] + report["notes"]:
            print("  - " + line)
    return util.EXIT_OK if report["ok"] else util.EXIT_FAIL


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = core.doctor()
    if args.json:
        _print_json(report)
    else:
        print("{0} {1}  at {2}".format(PROG, report["version"], report["at"]))
        work = report["work_dir"]
        print("work_dir {0} writable={1}".format(work["path"], work["writable"]))
        for item in report["engines"]:
            print("  {0:<8} available={1:<5} {2}".format(item["engine"], item["available"], item["reason"]))
    any_available = any(item["available"] for item in report["engines"])
    return util.EXIT_OK if any_available else util.EXIT_UNSUPPORTED


COMMANDS = {
    "engines": _cmd_engines,
    "voices": _cmd_voices,
    "synth": _cmd_synth,
    "batch": _cmd_batch,
    "inspect": _cmd_inspect,
    "doctor": _cmd_doctor,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not getattr(args, "command", None):
        parser.print_help()
        return util.EXIT_USAGE
    handler = COMMANDS[args.command]
    try:
        return int(handler(args))
    except TTSError as exc:
        print("{0}: {1}".format(exc.code, exc.message), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return util.EXIT_FAIL


_ = (Path, Dict, List)
