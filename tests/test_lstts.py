# -*- coding: utf-8 -*-
"""lstts 云引擎：HTTP 契约、zip 安全、错误码映射。"""

import contextlib
import tempfile
import unittest
import zipfile
import io
from pathlib import Path

import ark_testlib as lib
from tts_runtime.engines.lstts import LsttsEngine, resolve_voice
from tts_runtime.models import Request

TOKEN = "fake-token-for-tests-0001"  # ark-scan:allow 测试用假 token，非真实凭据


@contextlib.contextmanager
def lstts_env(url=None, token=TOKEN, voice_dir=None):
    with lib.temp_env(
        TTS_RUNTIME_LSTTS_URL=url,
        TTS_RUNTIME_LSTTS_TOKEN=token,
        LSTTS_TTS_URL=None,
        LSTTS_TTS_TOKEN=None,
        LSTEST_TTS_URL=None,
        LSTEST_TTS_TOKEN=None,
        TTS_RUNTIME_VOICE_DIR=voice_dir,
        LSTEST_VOICE_DIR=None,
    ):
        yield


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.voice_dir = self.root / "voices"
        self.voice_dir.mkdir()
        self.voice = lib.make_wav(self.voice_dir / "付小春.wav", seconds=0.4)
        self.wav = lib.make_wav(self.root / "server.wav", seconds=0.6)
        self.wav_bytes = self.wav.read_bytes()
        self.out = self.root / "out" / "result.wav"

    def tearDown(self):
        self._tmp.cleanup()

    def request(self, **kwargs):
        payload = dict(text="你好世界", output=self.out, engine="lstts", voice="付小春")
        payload.update(kwargs)
        return Request(**payload)

    def synthesize(self, responder, **kwargs):
        with lib.FakeServer(responder) as server:
            with lstts_env(url=server.url, voice_dir=str(self.voice_dir)):
                result = LsttsEngine().synthesize(self.request(**kwargs))
            return result, list(server.requests)


class SuccessTest(Base):
    def test_clone_endpoint_writes_audio(self):
        responder = lambda path, body, headers: (200, "application/zip", lib.zip_bytes({"audio.wav": self.wav_bytes}))
        result, requests = self.synthesize(responder)

        self.assertTrue(result.ok, result.error)
        self.assertTrue(self.out.is_file())
        self.assertEqual(result.audio.sample_rate, 16000)
        self.assertEqual(result.voice, "付小春")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["path"], "/v1/clone")
        self.assertEqual(requests[0]["headers"]["authorization"], "Bearer " + TOKEN)
        self.assertTrue(requests[0]["headers"]["content-type"].startswith("multipart/form-data; boundary="))
        self.assertEqual(requests[0]["headers"]["accept"], "application/zip")
        body = requests[0]["body"]
        self.assertIn(b'name="spk_audio_prompt"', body)
        self.assertIn(b'name="text"', body)
        self.assertIn("你好世界".encode("utf-8"), body)

    def test_emotion_endpoint_adds_reference(self):
        emotion = lib.make_wav(self.root / "emo.wav", seconds=0.4)
        responder = lambda path, body, headers: (200, "application/zip", lib.zip_bytes({"x.wav": self.wav_bytes}))
        result, requests = self.synthesize(responder, emotion=emotion)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(requests[0]["path"], "/v1/emotion")
        self.assertIn(b'name="emo_audio_prompt"', requests[0]["body"])

    def test_zip_with_directory_prefix_is_allowed(self):
        responder = lambda path, body, headers: (200, "application/zip", lib.zip_bytes({"out/audio.wav": self.wav_bytes}))
        result, _ = self.synthesize(responder)
        self.assertTrue(result.ok, result.error)


class FailureTest(Base):
    def test_missing_config_is_unsupported(self):
        with lstts_env(url=None, token=None):
            result = LsttsEngine().synthesize(self.request())
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "UNSUPPORTED")
        self.assertIn("TTS_RUNTIME_LSTTS_URL", result.error["message"])
        self.assertIn("TTS_RUNTIME_LSTTS_TOKEN", result.error["message"])

    def test_http_error_is_backend(self):
        responder = lambda path, body, headers: (500, "text/plain", b"boom")
        result, _ = self.synthesize(responder)
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "BACKEND")
        self.assertIn("HTTP 500", result.error["message"])

    def test_non_zip_content_type_is_backend(self):
        responder = lambda path, body, headers: (200, "text/html", b"<html></html>")
        result, _ = self.synthesize(responder)
        self.assertEqual(result.error["code"], "BACKEND")
        self.assertIn("application/zip", result.error["message"])

    def test_broken_zip_is_backend(self):
        responder = lambda path, body, headers: (200, "application/zip", b"not-a-zip")
        result, _ = self.synthesize(responder)
        self.assertEqual(result.error["code"], "BACKEND")
        self.assertIn("zip", result.error["message"])

    def test_two_wavs_are_rejected(self):
        payload = lib.zip_bytes({"a.wav": self.wav_bytes, "b.wav": self.wav_bytes})
        responder = lambda path, body, headers: (200, "application/zip", payload)
        result, _ = self.synthesize(responder)
        self.assertEqual(result.error["code"], "BACKEND")
        self.assertIn("wav 数量", result.error["message"])

    def test_zip_slip_is_rejected(self):
        payload = lib.zip_bytes({"../evil.wav": self.wav_bytes})
        responder = lambda path, body, headers: (200, "application/zip", payload)
        result, _ = self.synthesize(responder)
        self.assertEqual(result.error["code"], "BACKEND")
        self.assertIn("非法路径", result.error["message"])

    def test_absolute_member_is_rejected(self):
        payload = lib.zip_bytes({"/abs/evil.wav": self.wav_bytes})
        responder = lambda path, body, headers: (200, "application/zip", payload)
        result, _ = self.synthesize(responder)
        self.assertEqual(result.error["code"], "BACKEND")

    def test_speed_is_usage(self):
        with lstts_env(url="http://127.0.0.1:9", voice_dir=str(self.voice_dir)):
            result = LsttsEngine().synthesize(self.request(speed=1.2))
        self.assertEqual(result.error["code"], "USAGE")
        self.assertIn("speed", result.error["message"])

    def test_unknown_voice_is_unsupported(self):
        with lstts_env(url="http://127.0.0.1:9", voice_dir=str(self.voice_dir)):
            result = LsttsEngine().synthesize(self.request(voice="不存在的音色"))
        self.assertEqual(result.error["code"], "UNSUPPORTED")
        self.assertIn("找不到音色", result.error["message"])

    def test_missing_emotion_file_is_usage(self):
        with lstts_env(url="http://127.0.0.1:9", voice_dir=str(self.voice_dir)):
            result = LsttsEngine().synthesize(self.request(emotion=self.root / "nope.wav"))
        self.assertEqual(result.error["code"], "USAGE")

    def test_connection_refused_is_backend(self):
        with lib.FakeServer(lambda p, b, h: (200, "application/zip", b"")) as server:
            url = server.url
        with lstts_env(url=url, voice_dir=str(self.voice_dir)):
            result = LsttsEngine().synthesize(self.request(timeout_s=2))
        self.assertEqual(result.error["code"], "BACKEND")


class VoiceAndStatusTest(Base):
    def test_resolve_voice_by_name_and_path(self):
        with lstts_env(url="http://x", voice_dir=str(self.voice_dir)):
            self.assertEqual(resolve_voice("付小春"), self.voice)
            self.assertEqual(resolve_voice(str(self.voice)), self.voice)

    def test_voices_lists_wav_stems(self):
        with lstts_env(url="http://x", voice_dir=str(self.voice_dir)):
            voices = LsttsEngine().voices()
        self.assertEqual([item.name for item in voices], ["付小春"])
        self.assertEqual(voices[0].kind, "reference")

    def test_status_reports_missing_names_only(self):
        with lstts_env(url=None, token=None):
            status = LsttsEngine().status()
        self.assertFalse(status.available)
        self.assertEqual(status.missing_env, ["TTS_RUNTIME_LSTTS_URL", "TTS_RUNTIME_LSTTS_TOKEN"])
        self.assertNotIn(TOKEN, status.reason)

    def test_status_available_does_not_leak_token(self):
        with lstts_env(url="http://127.0.0.1:1234"):
            status = LsttsEngine().status()
        self.assertTrue(status.available)
        self.assertNotIn(TOKEN, status.reason)


class SafeMemberTest(unittest.TestCase):
    def test_encrypted_member_is_rejected(self):
        from tts_runtime.engines import lstts as module
        from tts_runtime.errors import BackendError

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("a.wav", b"data")
        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
            info = archive.infolist()[0]
            info.flag_bits |= 0x1
            with self.assertRaises(BackendError):
                module._safe_audio_member(archive)


if __name__ == "__main__":
    unittest.main()
