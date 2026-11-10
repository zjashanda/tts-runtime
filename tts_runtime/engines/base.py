"""引擎抽象。

一个引擎只需要回答三件事：能不能用（status）、有什么音色（voices）、怎么合成
（synthesize）。统一编排（选引擎、命名、校验、事件）由 :mod:`tts_runtime.core`
负责，引擎内不要重复实现。
"""

from __future__ import annotations

import abc
from typing import List

from ..models import EngineStatus, Request, Result, Voice


class TTSEngine(abc.ABC):
    #: 稳定引擎名，出现在 CLI、JSON 与事件里。
    name = "base"

    @abc.abstractmethod
    def status(self) -> EngineStatus:
        """当前可用性。不可用时 ``reason`` 说明缺什么，``missing_env`` 只放变量名。"""

    def voices(self) -> List[Voice]:
        return []

    @abc.abstractmethod
    def synthesize(self, request: Request) -> Result:
        """执行一次合成。**不抛异常**，失败返回 ``ok=False`` 的 Result。"""

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<TTSEngine {0}>".format(self.name)
