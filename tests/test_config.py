# -*- coding: utf-8 -*-
"""config：默认值、凭据键拒绝、环境覆盖、白名单过滤。"""

import json
import tempfile
import unittest
from pathlib import Path

import ark_testlib as lib
from tts_runtime import config
from tts_runtime.errors import UsageError


class SanitizeTest(unittest.TestCase):
    def test_allows_known_keys(self):
        clean = config.sanitize({"schema": config.CONFIG_SCHEMA, "engine": "mock", "speed": "1.2", "workers": 99})
        self.assertEqual(clean["engine"], "mock")
        self.assertEqual(clean["speed"], 1.2)
        self.assertEqual(clean["workers"], 8)

    def test_drops_unknown_keys_silently(self):
        clean = config.sanitize({"engine": "mock", "whatever": 1})
        self.assertEqual(clean, {"engine": "mock"})

    def test_rejects_url_keys(self):
        for key in ("url", "base_url", "endpoint", "uri"):
            with self.assertRaises(UsageError):
                config.sanitize({key: "http://127.0.0.1"})

    def test_rejects_secret_keys_anywhere(self):
        payloads = [
            {"token": "x"},
            {"lstts": {"access_key_secret": "x"}},
            {"list": [{"password": "x"}]},
            {"api_key": "x"},
            {"credential": "x"},
        ]
        for payload in payloads:
            with self.assertRaises(UsageError):
                config.sanitize(payload)

    def test_rejects_invalid_engine(self):
        with self.assertRaises(UsageError):
            config.sanitize({"engine": "gpt-tts"})

    def test_rejects_non_object(self):
        with self.assertRaises(UsageError):
            config.sanitize([])

    def test_bad_speed_and_workers(self):
        with self.assertRaises(UsageError):
            config.sanitize({"speed": "fast"})
        with self.assertRaises(UsageError):
            config.sanitize({"workers": "many"})


class LoadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, payload) -> Path:
        target = self.root / "cfg.json"
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return target

    def test_defaults_without_file(self):
        with lib.temp_env(TTS_RUNTIME_CONFIG=str(self.root / "absent.json"), TTS_RUNTIME_ENGINE=None,
                          TTS_RUNTIME_WORK=None, TTS_RUNTIME_TIMEOUT=None, LSTEST_TTS_TIMEOUT=None,
                          TTS_RUNTIME_LANGUAGE=None):
            cfg = config.load()
        self.assertEqual(cfg["engine"], "auto")
        self.assertEqual(cfg["language"], "ZH")
        self.assertTrue(cfg["validate"])
        self.assertNotIn("work_dir", cfg)

    def test_file_overrides_defaults(self):
        target = self._write({"schema": config.CONFIG_SCHEMA, "engine": "mock", "timeout_s": 5})
        cfg = config.load(target)
        self.assertEqual(cfg["engine"], "mock")
        self.assertEqual(cfg["timeout_s"], 5)

    def test_env_overrides_file(self):
        target = self._write({"engine": "mock"})
        with lib.temp_env(TTS_RUNTIME_ENGINE="lstts", TTS_RUNTIME_WORK="/tmp/tts-work",
                          TTS_RUNTIME_TIMEOUT="12", TTS_RUNTIME_LANGUAGE="en"):
            cfg = config.load(target)
        self.assertEqual(cfg["engine"], "lstts")
        self.assertEqual(cfg["work_dir"], "/tmp/tts-work")
        self.assertEqual(cfg["timeout_s"], 12.0)
        self.assertEqual(cfg["language"], "EN")

    def test_missing_explicit_file_raises(self):
        with self.assertRaises(UsageError):
            config.load(self.root / "absent.json")

    def test_broken_json_raises(self):
        target = self.root / "broken.json"
        target.write_text("{ nope", encoding="utf-8")
        with self.assertRaises(UsageError):
            config.load(target)

    def test_file_with_token_is_rejected(self):
        target = self._write({"engine": "lstts", "token": "<env>"})
        with self.assertRaises(UsageError) as caught:
            config.load(target)
        self.assertIn("环境变量", str(caught.exception))

    def test_bad_env_engine_raises(self):
        with lib.temp_env(TTS_RUNTIME_ENGINE="nope"):
            with self.assertRaises(UsageError):
                config.load()

    def test_bad_env_timeout_raises(self):
        with lib.temp_env(TTS_RUNTIME_TIMEOUT="abc"):
            with self.assertRaises(UsageError):
                config.load()

    def test_describe_lists_sorted_keys(self):
        lines = list(config.describe({"b": 1, "a": 2}))
        self.assertEqual(lines, ["a=2", "b=1"])


if __name__ == "__main__":
    unittest.main()
