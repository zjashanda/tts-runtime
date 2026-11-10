"""统一编排：选引擎、定输出名、发事件、跑批量。

引擎只负责“怎么合成”，这里负责“合成前后的所有一致性”：参数校验、输出命名、
事件序列、批量并发与结果落盘。任何对外的稳定行为都从这里出去。
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import audio as audio_module
from . import config as config_module
from . import engines as engine_module
from . import util
from .errors import SynthesisError, UsageError
from .events import EventSink
from .models import JOB_SCHEMA, BatchResult, EngineStatus, Request, Result, Voice

MAX_WORKERS = 8


def resolve_output(output: Optional[Any], out_dir: Optional[Any], engine: str) -> Path:
    """``--out`` 与 ``--out-dir`` 互斥；目录自动命名，文件名补 ``.wav``。"""
    if output and out_dir:
        raise UsageError("--out 与 --out-dir 只能给一个")
    if out_dir:
        directory = Path(out_dir).expanduser()
        return directory / "tts-{0}-{1}.wav".format(util.format_stamp(), engine)
    if not output:
        raise UsageError("缺少输出：给 --out PATH 或 --out-dir DIR")
    target = Path(output).expanduser()
    if target.suffix.lower() != ".wav":
        target = target.with_suffix(".wav")
    return target


def synthesize(
    text: str,
    output: Optional[Any] = None,
    *,
    engine: str = "auto",
    voice: Optional[str] = None,
    emotion: Optional[Any] = None,
    language: Optional[str] = None,
    speed: Optional[float] = None,
    timeout_s: Optional[float] = None,
    validate: bool = True,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    out_dir: Optional[Any] = None,
    events: Optional[EventSink] = None,
    item_id: Optional[str] = None,
) -> Result:
    """合成一段文本。参数级问题抛异常；合成失败返回 ``ok=False`` 的 Result。"""
    if text is None or not str(text).strip():
        raise UsageError("文本为空")
    if language is not None:
        language = str(language).strip().upper() or None

    selected = engine_module.select_engine(engine)
    sink = events or EventSink()
    requested_engine = engine or "auto"
    if str(requested_engine).strip().lower() == "auto":
        requested_engine = selected.name

    target = resolve_output(output, out_dir, selected.name)
    request = Request(
        text=str(text),
        output=target,
        engine=selected.name,
        voice=voice,
        emotion=Path(emotion).expanduser() if emotion else None,
        language=language,
        speed=speed,
        timeout_s=timeout_s,
        validate=bool(validate),
        base_url=base_url,
        token=token,
        item_id=item_id,
    )
    sink.start(engine=selected.name, requested_engine=requested_engine, text_chars=len(request.text),
               output=str(target), voice=voice, language=language)
    result = selected.synthesize(request)
    sink.item(engine=selected.name, ok=result.ok, id=item_id,
              audio_path=result.audio_path, error=result.error)
    return result


def load_job(path: Any) -> Dict[str, Any]:
    """读取并校验 ``ark.tts-job.v1``。"""
    job_path = Path(path).expanduser()
    if not job_path.is_file():
        raise UsageError("job 文件不存在: {0}".format(job_path))
    try:
        payload = json.loads(util.read_text(job_path))
    except json.JSONDecodeError as exc:
        raise UsageError("job 不是合法 JSON: {0}".format(exc))
    if not isinstance(payload, dict):
        raise UsageError("job 必须是 JSON 对象")
    schema = payload.get("schema")
    if schema and schema != JOB_SCHEMA:
        raise UsageError("job schema 必须是 {0}，收到 {1!r}".format(JOB_SCHEMA, schema))
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise UsageError("job.items 必须是非空数组")
    seen: set = set()
    base = job_path.parent
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise UsageError("job.items[{0}] 必须是对象".format(index))
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise UsageError("job.items[{0}] 缺少 id".format(index))
        if item_id in seen:
            raise UsageError("job.items 的 id 重复: {0}".format(item_id))
        seen.add(item_id)
        has_text = bool(str(item.get("text") or "").strip())
        has_file = bool(item.get("text_file"))
        if has_text == has_file:
            raise UsageError("job.items[{0}] 必须在 text 与 text_file 之间二选一".format(index))
        if has_file:
            candidate = Path(str(item["text_file"])).expanduser()
            if not candidate.is_absolute():
                candidate = base / candidate
            if not candidate.is_file():
                raise UsageError("job.items[{0}] 的 text_file 不存在: {1}".format(index, candidate))
            item["text"] = util.read_text(candidate)
    payload["_base"] = str(base)
    return payload


def synthesize_batch(
    job: Dict[str, Any],
    out_dir: Any,
    *,
    engine: str = "auto",
    workers: int = 1,
    events: Optional[EventSink] = None,
    **kwargs: Any,
) -> BatchResult:
    """按 job 批量合成；即使有失败项也返回完整 BatchResult。"""
    sink = events or EventSink()
    directory = Path(out_dir).expanduser()
    util.ensure_dir(directory)
    items: List[Dict[str, Any]] = list(job.get("items") or [])
    requested = str(engine or "").strip().lower()
    explicit = requested if requested and requested != "auto" else None
    default_engine = explicit or job.get("engine") or "auto"
    default_language = job.get("language") or kwargs.pop("language", None)
    default_speed = job.get("speed", kwargs.pop("speed", None))
    job_name = str(job.get("name") or "batch")
    worker_count = max(1, min(MAX_WORKERS, int(workers or job.get("workers") or 1)))

    selected = engine_module.select_engine(default_engine)
    batch = BatchResult(job=job_name, engine=selected.name, out_dir=str(directory.resolve()), workers=worker_count)
    sink.start(engine=selected.name, job=job_name, total=len(items), workers=worker_count,
               out_dir=batch.out_dir)

    def run_one(index: int, item: Dict[str, Any]) -> Result:
        item_id = str(item.get("id"))
        target = directory / "{0:03d}-{1}.wav".format(index + 1, item_id)
        request = Request(
            text=str(item.get("text") or ""),
            output=target,
            engine=selected.name,
            voice=item.get("voice"),
            emotion=Path(item["emotion"]).expanduser() if item.get("emotion") else None,
            language=(item.get("language") or default_language),
            speed=item.get("speed", default_speed),
            timeout_s=item.get("timeout_s"),
            validate=bool(item.get("validate", True)),
            item_id=item_id,
        )
        result = selected.synthesize(request)
        sink.item(engine=selected.name, ok=result.ok, id=item_id, audio_path=result.audio_path,
                  error=result.error)
        return result

    if worker_count == 1:
        for index, item in enumerate(items):
            batch.items.append(run_one(index, item))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [pool.submit(run_one, index, item) for index, item in enumerate(items)]
            batch.items = [future.result() for future in futures]

    batch.finish()
    util.write_json_atomic(directory / "batch-result.json", batch.to_dict())
    sink.complete(engine=selected.name, job=job_name, ok=batch.ok, total=len(batch.items),
                  succeeded=batch.succeeded, failed=batch.failed)
    return batch


def list_voices(engine: Optional[str] = None) -> List[Voice]:
    if engine and str(engine).strip().lower() not in ("", "auto"):
        return engine_module.get_engine(str(engine)).voices()
    voices: List[Voice] = []
    for name in engine_module.ENGINE_NAMES:
        voices.extend(engine_module.get_engine(name).voices())
    return voices


def available_engines() -> List[EngineStatus]:
    return engine_module.statuses()


def inspect_audio(path: Any) -> Dict[str, Any]:
    target = Path(path).expanduser()
    info, fatal, notes = audio_module.evaluate(target)
    return {
        "path": str(target.resolve()),
        "ok": not fatal,
        "audio": info.to_dict() if info else None,
        "fatal": fatal,
        "notes": notes,
    }


def runtime_config() -> Dict[str, Any]:
    return config_module.load()


def doctor() -> Dict[str, Any]:
    """环境自检：引擎可用性、缺失变量名（不读值）、工作目录可写性。"""
    config = config_module.load()
    work_root = util.first_env(["TTS_RUNTIME_WORK"]) or str(Path(os.environ.get("TMPDIR") or "/tmp") / "tts-runtime")
    work_path = Path(work_root)
    writable = True
    try:
        util.ensure_dir(work_path)
        probe = work_path / ".tts-runtime-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        writable = False
    return {
        "schema": "ark.tts-doctor.v1",
        "at": util.format_display(),
        "version": _version(),
        "config": {key: config.get(key) for key in sorted(config)},
        "work_dir": {"path": str(work_path), "writable": writable},
        "engines": [status.to_dict() for status in available_engines()],
    }


def _version() -> str:
    from . import __version__

    return __version__


_ = (SynthesisError, Iterable)
