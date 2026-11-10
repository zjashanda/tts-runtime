"""错误类型 → 退出码的单一映射。

约定（与 SPEC 一致）
--------------------
``UsageError``       → 1 USAGE        参数/契约/配置错误
``SynthesisError``   → 2 FAIL         业务失败（后端返回了但不可用、音频校验不过）
``EngineUnavailable``→ 3 UNSUPPORTED  引擎不可用（未配置、未安装、语言不支持）
``BackendError``     → 4 BACKEND      网络/HTTP/协议层不可用

所有 ``message`` 在构造时就会脱敏：异常信息最终会进日志、JSON 与 issue 评论。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import util


class TTSError(Exception):
    """所有本仓错误的基类。``code`` 是稳定字符串，``exit_code`` 是进程退出码。"""

    code = "FAIL"
    exit_code = util.EXIT_FAIL

    def __init__(self, message: str, *, engine: Optional[str] = None, detail: Optional[Dict[str, Any]] = None):
        super().__init__(util.redact(message))
        self.message = util.redact(message)
        self.engine = engine
        self.detail = detail or {}

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.engine:
            payload["engine"] = self.engine
        if self.detail:
            payload["detail"] = {key: util.redact(value) for key, value in self.detail.items()}
        return payload

    def __str__(self) -> str:  # pragma: no cover - 直观输出
        return "{0}: {1}".format(self.code, self.message)


class UsageError(TTSError):
    code = "USAGE"
    exit_code = util.EXIT_USAGE


class SynthesisError(TTSError):
    code = "FAIL"
    exit_code = util.EXIT_FAIL


class EngineUnavailable(TTSError):
    code = "UNSUPPORTED"
    exit_code = util.EXIT_UNSUPPORTED


class BackendError(TTSError):
    code = "BACKEND"
    exit_code = util.EXIT_BACKEND


ERRORS = {
    "USAGE": UsageError,
    "FAIL": SynthesisError,
    "UNSUPPORTED": EngineUnavailable,
    "BACKEND": BackendError,
}


def from_code(code: str, message: str, **kwargs: Any) -> TTSError:
    """按稳定错误码构造异常（用于把 Result 里的 error 再抛出来）。"""
    cls = ERRORS.get(str(code or "").upper(), SynthesisError)
    return cls(message, **kwargs)
