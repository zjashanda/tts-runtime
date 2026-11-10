"""测试公共设施：路径、临时目录、假 wav、假 HTTP 服务。"""

from __future__ import annotations

import contextlib
import io
import json
import os
import struct
import sys
import threading
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def make_wav(path: Path, *, seconds: float = 0.5, sample_rate: int = 16000,
             channels: int = 1, amplitude: int = 8000) -> Path:
    """写一个合法的 16-bit PCM wav。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    total = max(1, int(seconds * sample_rate))
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total):
            sample = amplitude if index % 2 == 0 else -amplitude
            for _ in range(channels):
                frames.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(frames))
    return target


def silent_wav(path: Path, *, seconds: float = 0.5, sample_rate: int = 16000) -> Path:
    return make_wav(path, seconds=seconds, sample_rate=sample_rate, amplitude=0)


def zip_bytes(members: Dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeTTS/1.0"

    def do_POST(self) -> None:  # noqa: N802 - http.server 约定
        config = self.server.config  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        config["requests"].append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )
        status, content_type, payload = config["responder"](self.path, body, self.headers)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 静默
        return


class FakeServer:
    """可编程的本地 HTTP 服务：``responder(path, body, headers) -> (status, ctype, bytes)``。"""

    def __init__(self, responder: Callable[[str, bytes, Any], Tuple[int, str, bytes]]):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.config = {"responder": responder, "requests": []}  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return "http://{0}:{1}".format(host, port)

    @property
    def requests(self) -> List[Dict[str, Any]]:
        return self.httpd.config["requests"]  # type: ignore[attr-defined]

    def __enter__(self) -> "FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@contextlib.contextmanager
def temp_env(**values: Optional[str]):
    """临时设置/清除环境变量，退出时精确还原。"""
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def captured():
    """同时捕获 stdout 与 stderr。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


CLEAN_ENV_KEYS = (
    "TTS_RUNTIME_LSTTS_URL",
    "TTS_RUNTIME_LSTTS_TOKEN",
    "TTS_RUNTIME_VOICE_DIR",
    "TTS_RUNTIME_ENGINE",
    "TTS_RUNTIME_CONFIG",
    "TTS_RUNTIME_TIMEOUT",
    "TTS_RUNTIME_LANGUAGE",
    "LSTTS_TTS_URL",
    "LSTTS_TTS_TOKEN",
    "LSTEST_TTS_URL",
    "LSTEST_TTS_TOKEN",
    "LSTEST_TTS_TIMEOUT",
    "LSTEST_VOICE_DIR",
    "MELOTTS_HOME",
    "MELOTTS_PYTHON",
)
