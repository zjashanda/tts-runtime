"""云引擎：lstts / IndexTTS。

复用既有 HTTP 契约（见 ``docs/engines.md``）：

* ``POST {base}/v1/clone``     —— 无情感参考音频
* ``POST {base}/v1/emotion``   —— 带情感参考音频
* ``Authorization: Bearer <token>``，``multipart/form-data``
* 字段：``spk_audio_prompt``（音色 wav）、``text``（文本）、可选 ``emo_audio_prompt``
* 响应必须是 ``application/zip``，且 zip 内**恰好一个** ``.wav``

实现只用标准库 ``urllib``；URL 与 token **只从环境变量读**（显式参数可注入，
用于调用方自管凭据的场景）。任何异常信息都过 :func:`tts_runtime.util.redact`。
"""

from __future__ import annotations

import io
import secrets
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import audio, util
from ..errors import BackendError, EngineUnavailable, SynthesisError, UsageError
from ..models import EngineStatus, Request, Result, Voice

URL_ENV = ("TTS_RUNTIME_LSTTS_URL", "LSTTS_TTS_URL", "LSTEST_TTS_URL")
TOKEN_ENV = ("TTS_RUNTIME_LSTTS_TOKEN", "LSTTS_TTS_TOKEN", "LSTEST_TTS_TOKEN")
TIMEOUT_ENV = ("TTS_RUNTIME_TIMEOUT", "LSTEST_TTS_TIMEOUT")
VOICE_DIR_ENV = ("TTS_RUNTIME_VOICE_DIR", "LSTEST_VOICE_DIR")

VOICE_EXTENSIONS = (".wav", ".mp3", ".flac", ".m4a", ".ogg")
ENDPOINT_CLONE = "/v1/clone"
ENDPOINT_EMOTION = "/v1/emotion"

MAX_AUDIO_BYTES = 200 * util.MIB
USER_AGENT = "tts-runtime/0.1.0"


def _voice_dir() -> Optional[Path]:
    value = util.first_env(VOICE_DIR_ENV)
    return Path(value).expanduser() if value else None


def resolve_voice(voice: Optional[str]) -> Path:
    """音色解析：显式路径 → ``voice_dir/<name>[.wav]`` → 内置目录。"""
    if not voice or not str(voice).strip():
        raise EngineUnavailable("lstts 需要音色参考音频：设置 voice（名字或 wav 路径）", engine="lstts")
    candidate = Path(str(voice)).expanduser()
    if candidate.suffix.lower() in VOICE_EXTENSIONS and candidate.is_file():
        return candidate
    if candidate.is_file():
        return candidate

    directories: List[Path] = []
    env_dir = _voice_dir()
    if env_dir is not None:
        directories.append(env_dir)
    directories.append(Path.home() / ".config" / "ark" / "voices")
    for directory in directories:
        for suffix in VOICE_EXTENSIONS:
            target = directory / (str(voice) + suffix)
            if target.is_file():
                return target
    known = sorted({item.stem for directory in directories if directory.is_dir() for item in directory.glob("*.wav")})
    hint = "，可用音色: " + ", ".join(known) if known else ""
    raise EngineUnavailable(
        "找不到音色 {0!r}：请给 wav 绝对路径，或用 TTS_RUNTIME_VOICE_DIR 指定音色目录{1}".format(voice, hint),
        engine="lstts",
    )


def _multipart(fields: List[Tuple[str, str, bytes, str]]) -> Tuple[bytes, str]:
    """构造 multipart body。``fields`` 元素：``(name, filename, content, content_type)``。"""
    boundary = "----ttsruntime" + secrets.token_hex(16)
    buffer = io.BytesIO()
    for name, filename, content, content_type in fields:
        buffer.write(("--" + boundary + "\r\n").encode("ascii"))
        buffer.write(
            'Content-Disposition: form-data; name="{0}"; filename="{1}"\r\n'.format(name, filename).encode("utf-8")
        )
        buffer.write(("Content-Type: " + content_type + "\r\n\r\n").encode("ascii"))
        buffer.write(content)
        buffer.write(b"\r\n")
    buffer.write(("--" + boundary + "--\r\n").encode("ascii"))
    return buffer.getvalue(), "multipart/form-data; boundary=" + boundary


def _safe_audio_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    """返回唯一的 wav 成员；任何路径穿越/加密/符号链接都拒绝。"""
    members = [info for info in archive.infolist() if not info.is_dir()]
    wavs = [info for info in members if info.filename.lower().endswith(".wav")]
    if len(wavs) != 1:
        raise BackendError(
            "响应 zip 内 wav 数量必须是 1，实际 {0}".format(len(wavs)), engine="lstts"
        )
    info = wavs[0]
    name = info.filename
    parts = [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]
    if name.startswith("/") or name.startswith("\\") or any(part == ".." for part in parts) or ":" in name:
        raise BackendError("响应 zip 含非法路径: {0}".format(util.redact(name)), engine="lstts")
    if info.flag_bits & 0x1:
        raise BackendError("响应 zip 含加密成员", engine="lstts")
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        raise BackendError("响应 zip 含符号链接", engine="lstts")
    if info.file_size > MAX_AUDIO_BYTES:
        raise BackendError("响应音频过大: {0}".format(util.human_bytes(info.file_size)), engine="lstts")
    return info


class LsttsEngine:
    name = "lstts"

    # ---------------------------------------------------------------- 配置

    @staticmethod
    def _base_url(explicit: Optional[str] = None) -> Optional[str]:
        value = explicit or util.first_env(URL_ENV)
        return value.rstrip("/") if value else None

    @staticmethod
    def _token(explicit: Optional[str] = None) -> Optional[str]:
        return explicit or util.first_env(TOKEN_ENV)

    @staticmethod
    def _timeout(explicit: Optional[float] = None) -> float:
        if explicit is not None:
            return max(1.0, float(explicit))
        raw = util.first_env(TIMEOUT_ENV)
        try:
            return max(1.0, float(raw)) if raw else 30.0
        except ValueError:
            return 30.0

    def status(self) -> EngineStatus:
        base_url = self._base_url()
        token = self._token()
        missing: List[str] = []
        if not base_url:
            missing.append(URL_ENV[0])
        if not token:
            missing.append(TOKEN_ENV[0])
        available = not missing
        if available:
            reason = "已配置（{0}）".format(util.redact(base_url or ""))
        else:
            reason = "缺少环境变量: " + ", ".join(missing) + "（只读变量名，值不进日志）"
        return EngineStatus(
            name=self.name,
            available=available,
            reason=reason,
            missing_env=missing,
            detail={
                "endpoints": [ENDPOINT_CLONE, ENDPOINT_EMOTION],
                "voice_dir": str(_voice_dir()) if _voice_dir() else None,
            },
        )

    def voices(self) -> List[Voice]:
        directory = _voice_dir()
        if directory is None or not directory.is_dir():
            return []
        result: List[Voice] = []
        for path in sorted(directory.glob("*.wav")):
            result.append(Voice(name=path.stem, engine=self.name, kind="reference", path=str(path), languages=["ZH"]))
        return result

    # ---------------------------------------------------------------- 合成

    def synthesize(self, request: Request) -> Result:
        started = util.now_beijing()
        base_url = self._base_url(request.base_url)
        token = self._token(request.token)
        missing: List[str] = []
        if not base_url:
            missing.append(URL_ENV[0])
        if not token:
            missing.append(TOKEN_ENV[0])
        if missing:
            return Result.failure(
                self.name,
                "UNSUPPORTED",
                "lstts 未配置，缺少环境变量: " + ", ".join(missing),
                started_at=started,
                item_id=request.item_id,
            )
        if request.speed is not None:
            return Result.failure(
                self.name, "USAGE", "lstts 不支持 speed 参数（请用 melotts）", started_at=started, item_id=request.item_id
            )
        if request.output is None:
            return Result.failure(self.name, "USAGE", "缺少输出路径", started_at=started, item_id=request.item_id)

        try:
            voice_path = resolve_voice(request.voice)
        except EngineUnavailable as exc:
            return Result.failure(self.name, exc.code, exc.message, started_at=started, item_id=request.item_id)
        if request.emotion is not None:
            emotion_path = Path(request.emotion).expanduser()
            if not emotion_path.is_file():
                return Result.failure(
                    self.name, "USAGE", "情感参考音频不存在: {0}".format(emotion_path),
                    started_at=started, item_id=request.item_id,
                )

        endpoint = ENDPOINT_EMOTION if request.emotion is not None else ENDPOINT_CLONE
        fields: List[Tuple[str, str, bytes, str]] = [
            ("spk_audio_prompt", voice_path.name, voice_path.read_bytes(), "audio/wav"),
            ("text", "text.txt", request.text.encode("utf-8"), "text/plain; charset=utf-8"),
        ]
        if request.emotion is not None:
            emotion_path = Path(request.emotion).expanduser()
            fields.append(("emo_audio_prompt", emotion_path.name, emotion_path.read_bytes(), "audio/wav"))

        try:
            payload, content_type = _multipart(fields)
            url = base_url + endpoint
            http_request = urllib.request.Request(url, data=payload, method="POST")
            http_request.add_header("Content-Type", content_type)
            http_request.add_header("Authorization", "Bearer " + str(token))
            http_request.add_header("Accept", "application/zip")
            http_request.add_header("User-Agent", USER_AGENT)
            with urllib.request.urlopen(http_request, timeout=self._timeout(request.timeout_s)) as response:
                status_code = getattr(response, "status", 200)
                response_type = response.headers.get("Content-Type", "")
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read()[:400].decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            return Result.failure(
                self.name,
                "BACKEND",
                "HTTP {0} from {1}{2}".format(exc.code, endpoint, (": " + detail) if detail else ""),
                started_at=started,
                item_id=request.item_id,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return Result.failure(
                self.name, "BACKEND", "请求失败: {0}".format(exc), started_at=started, item_id=request.item_id
            )

        if status_code != 200:
            return Result.failure(
                self.name, "BACKEND", "HTTP {0} from {1}".format(status_code, endpoint),
                started_at=started, item_id=request.item_id,
            )
        if not response_type.lower().startswith("application/zip"):
            return Result.failure(
                self.name,
                "BACKEND",
                "响应类型不是 application/zip: {0}".format(util.redact(response_type)),
                started_at=started,
                item_id=request.item_id,
            )

        output = Path(request.output)
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                member = _safe_audio_member(archive)
                data = archive.read(member)
        except zipfile.BadZipFile:
            return Result.failure(
                self.name, "BACKEND", "响应不是合法 zip", started_at=started, item_id=request.item_id
            )
        except BackendError as exc:
            return Result.failure(self.name, exc.code, exc.message, started_at=started, item_id=request.item_id)

        try:
            util.ensure_dir(output.parent if str(output.parent) else Path("."))
            output.write_bytes(data)
        except OSError as exc:
            return Result.failure(
                self.name, "FAIL", "写音频失败: {0}".format(exc), started_at=started, item_id=request.item_id
            )

        result = Result(
            engine=self.name,
            ok=True,
            started_at=started,
            voice=voice_path.stem,
            language=request.language,
            text_chars=len(request.text),
            audio_path=str(output.resolve()),
            item_id=request.item_id,
        )
        info, fatal, notes = audio.evaluate(output)
        result.audio = info
        result.notes = notes
        if fatal:
            if request.validate:
                result.ok = False
                result.error = {"code": "FAIL", "message": "; ".join(fatal), "engine": self.name}
            else:
                result.notes = fatal + notes
                result.notes.append("validate=false：仅记录，不判失败")
        return result.finish()


_ = (SynthesisError, UsageError)
