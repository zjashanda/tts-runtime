"""引擎注册表与 auto 选择策略。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ark_testlib as lib

from tts_runtime import audio, core
from tts_runtime.engines import ENGINE_NAMES, get_engine, select_engine, statuses
from tts_runtime.errors import EngineUnavailable


def clean_env():
    values = {key: None for key in lib.CLEAN_ENV_KEYS}
    values["TTS_RUNTIME_CONFIG"] = str(Path(tempfile.gettempdir()) / "tts-runtime-missing-config.json")
    return lib.temp_env(**values)


class RegistryTest(unittest.TestCase):
    def test_statuses_follow_documented_order(self) -> None:
        self.assertEqual(tuple(item.name for item in statuses()), ENGINE_NAMES)
        self.assertEqual(ENGINE_NAMES, ("lstts", "melotts", "mock"))

    def test_mock_is_always_available(self) -> None:
        with clean_env():
            mock = get_engine("mock")
            self.assertTrue(mock.status().available)
            self.assertEqual(mock.status().missing_env, [])

    def test_unknown_engine_is_unsupported(self) -> None:
        with self.assertRaises(EngineUnavailable) as ctx:
            get_engine("nope")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertIn("mock", ctx.exception.message)

    def test_engine_name_is_case_insensitive(self) -> None:
        self.assertIs(get_engine("MOCK"), get_engine("mock"))


class SelectEngineTest(unittest.TestCase):
    def test_explicit_mock(self) -> None:
        with clean_env():
            self.assertEqual(select_engine("mock").name, "mock")

    def test_explicit_lstts_without_config_is_unsupported(self) -> None:
        with clean_env():
            with self.assertRaises(EngineUnavailable) as ctx:
                select_engine("lstts")
            self.assertIn("TTS_RUNTIME_LSTTS_URL", ctx.exception.message)

    def test_explicit_melotts_without_home_is_unsupported(self) -> None:
        with clean_env():
            with self.assertRaises(EngineUnavailable) as ctx:
                select_engine("melotts")
            self.assertIn("MELOTTS_HOME", ctx.exception.message)

    def test_auto_without_backends_never_falls_back_to_mock(self) -> None:
        with clean_env():
            with self.assertRaises(EngineUnavailable) as ctx:
                select_engine("auto")
            message = ctx.exception.message
            self.assertIn("没有可用引擎", message)
            self.assertIn("lstts", message)
            self.assertIn("melotts", message)

    def test_forced_engine_env_is_honoured(self) -> None:
        values = {key: None for key in lib.CLEAN_ENV_KEYS}
        values["TTS_RUNTIME_CONFIG"] = str(Path(tempfile.gettempdir()) / "tts-runtime-missing-config.json")
        values["TTS_RUNTIME_ENGINE"] = "mock"
        with lib.temp_env(**values):
            self.assertEqual(select_engine("auto").name, "mock")

    def test_forced_unavailable_engine_fails_loudly(self) -> None:
        values = {key: None for key in lib.CLEAN_ENV_KEYS}
        values["TTS_RUNTIME_CONFIG"] = str(Path(tempfile.gettempdir()) / "tts-runtime-missing-config.json")
        values["TTS_RUNTIME_ENGINE"] = "lstts"
        with lib.temp_env(**values):
            with self.assertRaises(EngineUnavailable):
                select_engine("auto")


class MockSynthesisTest(unittest.TestCase):
    def test_mock_writes_playable_wav(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            with clean_env():
                result = core.synthesize("你好，世界", root / "a.wav", engine="mock")
            self.assertTrue(result.ok, result.error)
            target = Path(result.audio_path or "")
            self.assertTrue(target.is_file())
            info = audio.inspect_audio(target)
            self.assertEqual(info.sample_rate, 16000)
            self.assertEqual(info.channels, 1)
            self.assertEqual(info.sample_width, 2)
            self.assertGreater(info.duration_seconds, 0)
            self.assertEqual(result.engine, "mock")
            self.assertEqual(result.text_chars, len("你好，世界"))
            self.assertEqual(result.notes, [])

    def test_mock_duration_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            with clean_env():
                short = core.synthesize("短", root / "short.wav", engine="mock")
                long = core.synthesize("长" * 500, root / "long.wav", engine="mock")
            self.assertAlmostEqual(short.audio.duration_seconds, 0.3, places=2)
            self.assertLessEqual(long.audio.duration_seconds, 6.0)

    def test_mock_voices_are_stable(self) -> None:
        with clean_env():
            names = [voice.name for voice in core.list_voices("mock")]
        self.assertEqual(names, ["tone-440", "tone-880"])

    def test_auto_reports_missing_backends_in_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with clean_env():
                with self.assertRaises(EngineUnavailable):
                    core.synthesize("你好", Path(raw_dir) / "x.wav", engine="auto")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
