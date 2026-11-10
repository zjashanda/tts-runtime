"""引擎注册表与选择策略。

``auto`` 的选择顺序：显式 ``TTS_RUNTIME_ENGINE`` → ``lstts``（已配置）→
``melotts``（已安装）→ 报 ``UNSUPPORTED``。**永不静默回落到 mock**：一个假装
成功的合成结果比一条清楚的错误危险得多。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from ..errors import EngineUnavailable
from ..models import EngineStatus
from .base import TTSEngine
from .lstts import LsttsEngine
from .melotts import MelottsEngine
from .mock import MockEngine

ENGINE_NAMES = ("lstts", "melotts", "mock")
AUTO_ORDER = ("lstts", "melotts")

_REGISTRY: Dict[str, TTSEngine] = {
    "lstts": LsttsEngine(),
    "melotts": MelottsEngine(),
    "mock": MockEngine(),
}


def get_engine(name: str) -> TTSEngine:
    key = str(name or "").strip().lower()
    if key not in _REGISTRY:
        raise EngineUnavailable("未知引擎 {0!r}，可用: {1}".format(name, ", ".join(ENGINE_NAMES)))
    return _REGISTRY[key]


def statuses() -> List[EngineStatus]:
    return [_REGISTRY[name].status() for name in ENGINE_NAMES]


def _resolve_auto() -> str:
    forced = (os.environ.get("TTS_RUNTIME_ENGINE") or "").strip().lower()
    if forced and forced not in ("", "auto"):
        return forced
    for name in AUTO_ORDER:
        if _REGISTRY[name].status().available:
            return name
    detail = "; ".join("{0}={1}".format(item.name, item.reason) for item in statuses() if item.name != "mock")
    raise EngineUnavailable("没有可用引擎（auto）：" + detail)


def select_engine(name: Optional[str] = "auto") -> TTSEngine:
    """按名字（或 ``auto``）选出可用引擎；不可用直接抛 :class:`EngineUnavailable`。"""
    key = (name or "auto").strip().lower()
    if key == "auto":
        key = _resolve_auto()
    engine = get_engine(key)
    status = engine.status()
    if not status.available:
        raise EngineUnavailable("{0} 不可用：{1}".format(key, status.reason), engine=key)
    return engine


__all__ = ["ENGINE_NAMES", "TTSEngine", "get_engine", "select_engine", "statuses"]
