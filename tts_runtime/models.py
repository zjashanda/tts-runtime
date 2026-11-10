"""数据模型：请求、结果、音频信息、音色、引擎状态。

全部是 dataclass，``to_dict()`` 产出与 ``schemas/*.v1.json`` 对齐的字典。
时间字段对外一律北京时间、无时区后缀（见 :mod:`tts_runtime.util`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import util

REQUEST_SCHEMA = "ark.tts-request.v1"
RESULT_SCHEMA = "ark.tts-result.v1"
BATCH_SCHEMA = "ark.tts-batch.v1"
VOICE_SCHEMA = "ark.tts-voice.v1"
JOB_SCHEMA = "ark.tts-job.v1"
ENGINES = ("lstts", "melotts", "mock")


@dataclass
class AudioInfo:
    container: str
    codec: str
    sample_rate: int
    channels: int
    sample_width: int
    frames: int
    duration_seconds: float
    peak_dbfs: Optional[float] = None
    mean_db: Optional[float] = None
    clip_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "container": self.container,
            "codec": self.codec,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_width": self.sample_width,
            "frames": self.frames,
            "duration_seconds": self.duration_seconds,
            "peak_dbfs": self.peak_dbfs,
            "mean_db": self.mean_db,
            "clip_ratio": self.clip_ratio,
        }

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> Optional["AudioInfo"]:
        if not payload:
            return None
        return cls(
            container=str(payload.get("container") or "wav"),
            codec=str(payload.get("codec") or "pcm_s16le"),
            sample_rate=int(payload.get("sample_rate") or 0),
            channels=int(payload.get("channels") or 1),
            sample_width=int(payload.get("sample_width") or 2),
            frames=int(payload.get("frames") or 0),
            duration_seconds=float(payload.get("duration_seconds") or 0.0),
            peak_dbfs=payload.get("peak_dbfs"),
            mean_db=payload.get("mean_db"),
            clip_ratio=float(payload.get("clip_ratio") or 0.0),
        )


@dataclass
class Request:
    text: str
    output: Optional[Path] = None
    engine: str = "auto"
    voice: Optional[str] = None
    emotion: Optional[Path] = None
    language: Optional[str] = None
    speed: Optional[float] = None
    timeout_s: Optional[float] = None
    validate: bool = True
    base_url: Optional[str] = None
    token: Optional[str] = None
    item_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema": REQUEST_SCHEMA,
            "text": self.text,
            "engine": self.engine,
            "validate": self.validate,
        }
        if self.output is not None:
            payload["output"] = str(self.output)
        if self.voice:
            payload["voice"] = self.voice
        if self.emotion is not None:
            payload["emotion"] = str(self.emotion)
        if self.language:
            payload["language"] = self.language.upper()
        if self.speed is not None:
            payload["speed"] = self.speed
        if self.timeout_s is not None:
            payload["timeout_s"] = self.timeout_s
        if self.item_id:
            payload["id"] = self.item_id
        return payload


@dataclass
class Voice:
    name: str
    engine: str
    kind: str = "builtin"
    path: Optional[str] = None
    languages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema": VOICE_SCHEMA,
            "name": self.name,
            "engine": self.engine,
            "kind": self.kind,
            "languages": list(self.languages),
        }
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass
class EngineStatus:
    name: str
    available: bool
    reason: str = ""
    missing_env: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "engine": self.name,
            "available": self.available,
            "reason": self.reason,
            "missing_env": list(self.missing_env),
        }
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass
class Result:
    engine: str
    ok: bool
    started_at: datetime = field(default_factory=util.now_beijing)
    finished_at: Optional[datetime] = None
    voice: Optional[str] = None
    language: Optional[str] = None
    text_chars: int = 0
    audio_path: Optional[str] = None
    audio: Optional[AudioInfo] = None
    notes: List[str] = field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    item_id: Optional[str] = None

    def finish(self, when: Optional[datetime] = None) -> "Result":
        self.finished_at = when or util.now_beijing()
        return self

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at or util.now_beijing()
        return round((end - self.started_at).total_seconds(), 3)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema": RESULT_SCHEMA,
            "ok": bool(self.ok),
            "engine": self.engine,
            "voice": self.voice,
            "language": self.language,
            "text_chars": int(self.text_chars),
            "audio_path": self.audio_path,
            "audio": self.audio.to_dict() if self.audio else None,
            "started_at": util.format_display(self.started_at),
            "finished_at": util.format_display(self.finished_at) if self.finished_at else None,
            "elapsed_s": self.elapsed_s,
            "notes": list(self.notes),
            "error": self.error,
        }
        if self.item_id:
            payload["id"] = self.item_id
        return payload

    @staticmethod
    def failure(engine: str, code: str, message: str, *, item_id: Optional[str] = None,
                started_at: Optional[datetime] = None, notes: Optional[List[str]] = None) -> "Result":
        result = Result(
            engine=engine,
            ok=False,
            started_at=started_at or util.now_beijing(),
            item_id=item_id,
            notes=list(notes or []),
            error={"code": code, "message": util.redact(message), "engine": engine},
        )
        return result.finish()


@dataclass
class BatchResult:
    job: str
    engine: str
    out_dir: str
    items: List[Result] = field(default_factory=list)
    started_at: datetime = field(default_factory=util.now_beijing)
    finished_at: Optional[datetime] = None
    workers: int = 1

    @property
    def succeeded(self) -> int:
        return sum(1 for item in self.items if item.ok)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if not item.ok)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and bool(self.items)

    def finish(self) -> "BatchResult":
        self.finished_at = util.now_beijing()
        return self

    def to_dict(self) -> Dict[str, Any]:
        end = self.finished_at or util.now_beijing()
        return {
            "schema": BATCH_SCHEMA,
            "ok": self.ok,
            "job": self.job,
            "engine": self.engine,
            "out_dir": self.out_dir,
            "workers": self.workers,
            "items": [item.to_dict() for item in self.items],
            "total": len(self.items),
            "succeeded": self.succeeded,
            "failed": self.failed,
            "started_at": util.format_display(self.started_at),
            "finished_at": util.format_display(end),
            "elapsed_s": round((end - self.started_at).total_seconds(), 3),
        }
