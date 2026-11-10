"""统一 TTS 接口（canonical）。

对外只暴露这几件事：

* :func:`synthesize` —— 一段文本 → 一个 wav（云 lstts / 本地 melotts / 离线 mock）
* :func:`synthesize_batch` —— 一份 job → 一批 wav
* :func:`list_voices` / :func:`available_engines` —— 有哪些音色、哪个引擎能用
* :func:`inspect_audio` —— 音频体检（采样率/声道/时长/峰值）

URL 与 token **只从环境变量读取**；本包内不出现任何凭据值。
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

from .core import (  # noqa: E402  (版本号必须先定义，供 core 引用)
    available_engines,
    doctor,
    inspect_audio,
    list_voices,
    load_job,
    synthesize,
    synthesize_batch,
)
from .errors import (  # noqa: E402
    BackendError,
    EngineUnavailable,
    SynthesisError,
    TTSError,
    UsageError,
)
from .events import EventSink  # noqa: E402
from .models import AudioInfo, BatchResult, EngineStatus, Request, Result, Voice  # noqa: E402

__all__ = [
    "__version__",
    "AudioInfo",
    "BackendError",
    "BatchResult",
    "EngineStatus",
    "EngineUnavailable",
    "EventSink",
    "Request",
    "Result",
    "SynthesisError",
    "TTSError",
    "UsageError",
    "Voice",
    "available_engines",
    "doctor",
    "inspect_audio",
    "list_voices",
    "load_job",
    "synthesize",
    "synthesize_batch",
]
