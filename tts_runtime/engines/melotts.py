"""本地引擎：melotts / MeloTTS。

**本仓不内置模型推理**。torch、MeloTTS vendor、checkpoint 合计数百 MB，进公开
仓库既污染体积也带授权与供应链风险。这里以子进程委托既有安装：

    <MELOTTS_PYTHON> <MELOTTS_HOME>/scripts/synth.py \
        --language ZH --speaker <id> --text <tmp.txt> --out-dir <tmpdir> [--speed X]

每个非空行产出一个 ``{index:03d}.wav``；产物回收后由本仓统一做 WAV 校验
（16000Hz / mono / 16-bit PCM 是 melotts 的既有产物契约）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from .. import audio, util
from ..models import EngineStatus, Request, Result, Voice

HOME_ENV = "MELOTTS_HOME"
PYTHON_ENV = "MELOTTS_PYTHON"
LANGS = ("ZH", "EN")
DEFAULT_VOICE = {"ZH": "ZH", "EN": "EN-Default"}
SCRIPT_REL = Path("scripts") / "synth.py"


def _home() -> Optional[Path]:
    value = util.first_env([HOME_ENV])
    return Path(value).expanduser() if value else None


def _python(home: Optional[Path]) -> Optional[Path]:
    explicit = util.first_env([PYTHON_ENV])
    if explicit:
        return Path(explicit).expanduser()
    if home is None:
        return None
    candidates = [
        home / ".venv" / "bin" / "python",
        home / ".venv" / "Scripts" / "python.exe",
        home / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _missing(home: Optional[Path], python: Optional[Path], language: str) -> List[str]:
    problems: List[str] = []
    if home is None:
        problems.append("环境变量 {0} 未设置（指向 MeloTTS 安装根目录）".format(HOME_ENV))
        return problems
    if not (home / SCRIPT_REL).is_file():
        problems.append("缺少 {0}".format(home / SCRIPT_REL))
    if python is None or not python.is_file():
        problems.append("缺少解释器（{0} 或 {1}/.venv/bin/python）".format(PYTHON_ENV, home))
    model_dir = home / "models" / language
    for name in ("config.json", "checkpoint.pth"):
        if not (model_dir / name).is_file():
            problems.append("缺少模型文件 {0}".format(model_dir / name))
    return problems


def _child_env(home: Path) -> Dict[str, str]:
    """只传必要变量：模型查找、线程限制，以及跑 Python 必须的 PATH/HOME。"""
    keep = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
    child = {key: os.environ[key] for key in keep if os.environ.get(key)}
    child["NLTK_DATA"] = str(home / "nltk_data")
    child["TOKENIZERS_PARALLELISM"] = "false"
    child["PYTHONIOENCODING"] = "utf-8"
    return child


class MelottsEngine:
    name = "melotts"

    def status(self) -> EngineStatus:
        home = _home()
        python = _python(home)
        problems = _missing(home, python, "ZH")
        available = not problems
        return EngineStatus(
            name=self.name,
            available=available,
            reason="已安装（{0}）".format(home) if available else "; ".join(problems),
            missing_env=[] if available else [HOME_ENV],
            detail={
                "home": str(home) if home else None,
                "python": str(python) if python else None,
                "languages": list(LANGS),
            },
        )

    def voices(self) -> List[Voice]:
        home = _home()
        voices: List[Voice] = []
        for language in LANGS:
            voices.append(
                Voice(name=DEFAULT_VOICE[language], engine=self.name, kind="speaker", languages=[language])
            )
        if home is not None:
            config = home / "models" / "ZH" / "config.json"
            if config.is_file():
                try:
                    import json

                    payload = json.loads(config.read_text(encoding="utf-8"))
                    speakers = list((payload.get("data") or {}).get("spk2id") or {})
                    for speaker in speakers:
                        voices.append(Voice(name=str(speaker), engine=self.name, kind="speaker", languages=["ZH"]))
                except (OSError, ValueError):
                    pass
        return voices

    def synthesize(self, request: Request) -> Result:
        started = util.now_beijing()
        language = (request.language or "ZH").upper()
        home = _home()
        python = _python(home)

        if language not in LANGS:
            return Result.failure(
                self.name, "UNSUPPORTED", "melotts 只支持 {0}，收到 {1}".format("/".join(LANGS), language),
                started_at=started, item_id=request.item_id,
            )
        problems = _missing(home, python, language)
        if problems:
            return Result.failure(
                self.name, "UNSUPPORTED", "MeloTTS 不可用: " + "; ".join(problems),
                started_at=started, item_id=request.item_id,
            )
        if request.output is None:
            return Result.failure(self.name, "USAGE", "缺少输出路径", started_at=started, item_id=request.item_id)
        if request.emotion is not None:
            return Result.failure(
                self.name, "USAGE", "melotts 不支持 emotion 参考音频（请用 lstts）",
                started_at=started, item_id=request.item_id,
            )

        assert home is not None and python is not None  # _missing 已保证
        work_root = util.first_env(["TTS_RUNTIME_WORK"])
        base_tmp = Path(work_root) if work_root else Path(tempfile.gettempdir()) / "tts-runtime"
        util.ensure_dir(base_tmp)
        work_dir = Path(tempfile.mkdtemp(prefix="melotts-", dir=str(base_tmp)))
        output = Path(request.output)

        try:
            text_path = work_dir / "text.txt"
            text_path.write_text(request.text, encoding="utf-8")
            command = [
                str(python),
                str(home / SCRIPT_REL),
                "--language",
                language,
                "--speaker",
                str(request.voice or DEFAULT_VOICE[language]),
                "--text",
                str(text_path),
                "--out-dir",
                str(work_dir),
            ]
            if request.speed is not None:
                command.extend(["--speed", str(request.speed)])

            timeout = request.timeout_s if request.timeout_s is not None else 900.0
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(home),
                    env=_child_env(home),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return Result.failure(
                    self.name, "BACKEND", "MeloTTS 超时（{0:.0f}s）".format(timeout),
                    started_at=started, item_id=request.item_id,
                )
            except OSError as exc:
                return Result.failure(
                    self.name, "UNSUPPORTED", "无法启动 MeloTTS: {0}".format(exc),
                    started_at=started, item_id=request.item_id,
                )

            produced = sorted(work_dir.glob("*.wav"))
            if completed.returncode != 0 or not produced:
                tail = util.tail_lines(completed.stderr.decode("utf-8", errors="replace"), 20)
                message = "MeloTTS 退出码 {0}".format(completed.returncode)
                if tail:
                    message += "；stderr: " + " | ".join(tail)
                if completed.returncode != 0:
                    return Result.failure(self.name, "FAIL", message, started_at=started, item_id=request.item_id)
                return Result.failure(
                    self.name, "FAIL", "MeloTTS 未产出 wav（{0}）".format(message),
                    started_at=started, item_id=request.item_id,
                )

            util.ensure_dir(output.parent if str(output.parent) else Path("."))
            shutil.move(str(produced[0]), str(output))
        finally:
            shutil.rmtree(str(work_dir), ignore_errors=True)

        result = Result(
            engine=self.name,
            ok=True,
            started_at=started,
            voice=str(request.voice or DEFAULT_VOICE[language]),
            language=language,
            text_chars=len(request.text),
            audio_path=str(output.resolve()),
            item_id=request.item_id,
        )
        info, fatal, notes = audio.evaluate(output)
        result.audio = info
        result.notes = notes
        if info is not None and (info.sample_rate != 16000 or info.channels != 1):
            result.notes.append(
                "产物非 melotts 约定格式：{0}Hz/{1}ch".format(info.sample_rate, info.channels)
            )
        if fatal:
            if request.validate:
                result.ok = False
                result.error = {"code": "FAIL", "message": "; ".join(fatal), "engine": self.name}
            else:
                result.notes = fatal + notes
                result.notes.append("validate=false：仅记录，不判失败")
        return result.finish()


_ = sys
