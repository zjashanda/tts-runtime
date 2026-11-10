"""离线确定性引擎：不联网、不装模型、产物合法。

用途：单元测试、CI、演示、``--dry-run``。它**不会**被 ``auto`` 自动选中——
静默回落到一个只会发声的假引擎，比报错更糟。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .. import audio, util
from ..errors import SynthesisError
from ..models import EngineStatus, Request, Result, Voice

MOCK_VOICES = ("tone-440", "tone-880")


class MockEngine:
    name = "mock"

    def status(self) -> EngineStatus:
        return EngineStatus(
            name=self.name,
            available=True,
            reason="offline deterministic engine",
            detail={"sample_rate": 16000, "channels": 1, "codec": "pcm_s16le"},
        )

    def voices(self) -> List[Voice]:
        return [Voice(name=item, engine=self.name, kind="synthetic", languages=["ZH", "EN"]) for item in MOCK_VOICES]

    def synthesize(self, request: Request) -> Result:
        started = util.now_beijing()
        output = request.output
        if output is None:
            return Result.failure(self.name, "USAGE", "mock 引擎缺少输出路径", started_at=started)
        voice = request.voice or MOCK_VOICES[0]
        frequency = 880.0 if "880" in str(voice) else 440.0
        seconds = max(0.3, min(6.0, len(request.text) * 0.06))
        result = Result(
            engine=self.name,
            ok=True,
            started_at=started,
            voice=voice,
            language=request.language,
            text_chars=len(request.text),
            item_id=request.item_id,
        )
        try:
            info = audio.write_tone(Path(output), seconds=seconds, frequency=frequency)
        except OSError as exc:
            return Result.failure(self.name, "FAIL", "写音频失败: {0}".format(exc), started_at=started)
        result.audio_path = str(Path(output).resolve())
        result.audio = info
        return result.finish()

    def __repr__(self) -> str:  # pragma: no cover
        return "<TTSEngine mock>"


_ = SynthesisError  # 保持导入面稳定（引擎实现共用同一错误族）
