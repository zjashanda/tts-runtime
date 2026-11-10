"""非敏感运行时配置。

**URL 与 token 永远只从环境变量读取**，不进配置文件。为此加载时会对键名做
检查：一旦出现 ``url``/``token``/``secret``/``password`` 一类键（任意层级），
直接抛 :class:`UsageError`——静默忽略会让人以为配置生效了，比报错更危险。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import util
from .errors import UsageError

CONFIG_SCHEMA = "ark.tts-runtime-config.v1"

FORBIDDEN_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "apikey",
    "api_key",
    "access_key",
    "credential",
)
FORBIDDEN_KEY_EXACT = ("url", "base_url", "endpoint", "uri")

#: 允许出现在配置文件里的键（白名单，未知键只告警不报错）。
ALLOWED_KEYS = {
    "schema",
    "engine",
    "language",
    "speed",
    "timeout_s",
    "validate",
    "voice",
    "workers",
    "work_dir",
}

DEFAULTS: Dict[str, Any] = {
    "engine": "auto",
    "language": "ZH",
    "speed": None,
    "timeout_s": 30.0,
    "validate": True,
    "voice": None,
    "workers": 1,
}


def _is_forbidden(key: str) -> bool:
    lowered = str(key).strip().lower()
    if lowered in FORBIDDEN_KEY_EXACT:
        return True
    return any(part in lowered for part in FORBIDDEN_KEY_PARTS)


def _walk_forbidden(payload: Any, path: str = "") -> List[str]:
    hits: List[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = "{0}.{1}".format(path, key) if path else str(key)
            if _is_forbidden(key):
                hits.append(here)
            hits.extend(_walk_forbidden(value, here))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            hits.extend(_walk_forbidden(value, "{0}[{1}]".format(path, index)))
    return hits


def default_config_path() -> Optional[Path]:
    """``TTS_RUNTIME_CONFIG`` > ``~/.config/ark/tts-runtime.json``（存在才返回）。"""
    explicit = os.environ.get("TTS_RUNTIME_CONFIG")
    if explicit and explicit.strip():
        return Path(explicit.strip()).expanduser()
    candidate = Path.home() / ".config" / "ark" / "tts-runtime.json"
    return candidate if candidate.is_file() else None


def sanitize(payload: Any, *, source: str = "<config>") -> Dict[str, Any]:
    """校验并剔除非白名单键，返回可用配置。"""
    if not isinstance(payload, dict):
        raise UsageError("{0} 必须是 JSON 对象".format(source))
    forbidden = _walk_forbidden(payload)
    if forbidden:
        raise UsageError(
            "{0} 含凭据/端点键（{1}）：URL 与 token 只允许通过环境变量提供".format(
                source, ", ".join(sorted(forbidden))
            )
        )
    clean: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in ALLOWED_KEYS:
            clean[key] = value
    if "engine" in clean and str(clean["engine"]) not in ("auto", "lstts", "melotts", "mock"):
        raise UsageError("{0}: engine 非法: {1!r}".format(source, clean["engine"]))
    if "speed" in clean and clean["speed"] is not None:
        try:
            clean["speed"] = float(clean["speed"])
        except (TypeError, ValueError):
            raise UsageError("{0}: speed 必须是数字".format(source))
    if "workers" in clean and clean["workers"] is not None:
        try:
            clean["workers"] = max(1, min(8, int(clean["workers"])))
        except (TypeError, ValueError):
            raise UsageError("{0}: workers 必须是整数".format(source))
    return clean


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载配置：默认值 ← 配置文件 ← 相关环境变量。"""
    config: Dict[str, Any] = dict(DEFAULTS)
    target = Path(path).expanduser() if path else default_config_path()
    if target is not None:
        if not Path(target).is_file():
            if path is not None:
                raise UsageError("配置文件不存在: {0}".format(target))
        else:
            try:
                payload = json.loads(util.read_text(Path(target)))
            except json.JSONDecodeError as exc:
                raise UsageError("配置文件不是合法 JSON: {0} ({1})".format(target, exc))
            config.update(sanitize(payload, source=str(target)))

    engine = os.environ.get("TTS_RUNTIME_ENGINE")
    if engine and engine.strip():
        value = engine.strip()
        if value not in ("auto", "lstts", "melotts", "mock"):
            raise UsageError("TTS_RUNTIME_ENGINE 非法: {0!r}".format(value))
        config["engine"] = value
    language = os.environ.get("TTS_RUNTIME_LANGUAGE")
    if language and language.strip():
        config["language"] = language.strip().upper()
    timeout = os.environ.get("TTS_RUNTIME_TIMEOUT") or os.environ.get("LSTEST_TTS_TIMEOUT")
    if timeout and timeout.strip():
        try:
            config["timeout_s"] = float(timeout.strip())
        except ValueError:
            raise UsageError("TTS_RUNTIME_TIMEOUT 必须是数字")
    work_dir = os.environ.get("TTS_RUNTIME_WORK")
    if work_dir and work_dir.strip():
        config["work_dir"] = work_dir.strip()
    return config


def describe(config: Dict[str, Any]) -> Iterable[str]:
    for key in sorted(config):
        yield "{0}={1}".format(key, config[key])
