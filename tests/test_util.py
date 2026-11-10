# -*- coding: utf-8 -*-
"""util：时间契约、退出码、脱敏、编码兼容、原子写。"""

import json
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import ark_testlib as lib
from tts_runtime import util


class TimeContractTest(unittest.TestCase):
    def test_display_has_no_offset(self):
        text = util.format_display(datetime(2026, 11, 10, 21, 46, 3))
        self.assertEqual(text, "2026-11-10 21:46:03")
        self.assertNotIn("+", text)
        self.assertNotIn("T", text)

    def test_rfc3339_is_beijing(self):
        self.assertEqual(util.format_rfc3339(datetime(2026, 1, 2, 3, 4, 5)), "2026-01-02T03:04:05+0800")

    def test_stamp_is_filename_safe(self):
        stamp = util.format_stamp(datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(stamp, "20260102-030405")
        self.assertNotIn(":", stamp)

    def test_naive_datetime_assumed_beijing(self):
        utc = datetime(2026, 1, 2, 3, 4, 5, tzinfo=util.BEIJING)
        self.assertEqual(util.format_display(utc), "2026-01-02 03:04:05")

    def test_parse_time_roundtrip(self):
        for text in ("2026-11-10 21:46:03", "2026-11-10T21:46:03+0800", "2026-11-10T13:46:03Z"):
            parsed = util.parse_time(text)
            self.assertEqual(parsed.utcoffset(), timedelta(hours=8))
        self.assertEqual(util.format_display(util.parse_time("2026-11-10T13:46:03Z")), "2026-11-10 21:46:03")

    def test_parse_time_rejects_garbage(self):
        with self.assertRaises(ValueError):
            util.parse_time("昨天下午")
        with self.assertRaises(ValueError):
            util.parse_time("")


class ExitCodeTest(unittest.TestCase):
    def test_codes_are_stable(self):
        self.assertEqual(util.EXIT_OK, 0)
        self.assertEqual(util.EXIT_USAGE, 1)
        self.assertEqual(util.EXIT_FAIL, 2)
        self.assertEqual(util.EXIT_UNSUPPORTED, 3)
        self.assertEqual(util.EXIT_BACKEND, 4)
        self.assertEqual(set(util.EXIT_CODES), {0, 1, 2, 3, 4})


class RedactTest(unittest.TestCase):
    def test_env_value_is_masked(self):
        secret = "sk-this-is-a-fake-token-value"  # ark-scan:allow 测试用假值
        with lib.temp_env(TTS_RUNTIME_LSTTS_TOKEN=secret):
            masked = util.redact("Authorization: Bearer " + secret)
        self.assertNotIn(secret, masked)
        self.assertIn("***", masked)

    def test_short_values_are_ignored(self):
        with lib.temp_env(TTS_RUNTIME_LSTTS_TOKEN="abc"):
            self.assertEqual(util.redact("abc"), "abc")

    def test_bearer_fallback(self):
        masked = util.redact("header Bearer abcdefghijklmnopqrstuvwxyz")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", masked)

    def test_none_becomes_empty(self):
        self.assertEqual(util.redact(None), "")


class EnvHelperTest(unittest.TestCase):
    def test_first_env_prefers_first_present(self):
        with lib.temp_env(TTS_RUNTIME_LSTTS_URL=None, LSTTS_TTS_URL="", LSTEST_TTS_URL="http://x"):
            self.assertEqual(util.first_env(["TTS_RUNTIME_LSTTS_URL", "LSTTS_TTS_URL", "LSTEST_TTS_URL"]), "http://x")

    def test_env_present_returns_names_only(self):
        with lib.temp_env(TTS_RUNTIME_LSTTS_URL="http://127.0.0.1:1"):
            names = util.env_present(["TTS_RUNTIME_LSTTS_URL", "TTS_RUNTIME_LSTTS_TOKEN"])
        self.assertEqual(names, ["TTS_RUNTIME_LSTTS_URL"])

    def test_split_env_list(self):
        self.assertEqual(util.split_env_list("a, b;c  d"), ["a", "b", "c", "d"])
        self.assertEqual(util.split_env_list(None), [])


class FileHelperTest(unittest.TestCase):
    def test_human_bytes(self):
        self.assertEqual(util.human_bytes(0), "0B")
        self.assertEqual(util.human_bytes(1536), "1.5KB")
        self.assertEqual(util.human_bytes(3 * 1024 * 1024), "3.0MB")

    def test_read_text_encodings(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, encoding in (("a.txt", "utf-8-sig"), ("b.txt", "gb18030"), ("c.txt", "utf-16")):
                target = root / name
                target.write_bytes("你好，世界".encode(encoding))
                self.assertEqual(util.read_text(target), "你好，世界")

    def test_write_json_atomic_keeps_chinese(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "out.json"
            util.write_json_atomic(target, {"文本": "你好"})
            raw = target.read_text(encoding="utf-8")
            self.assertIn("你好", raw)
            self.assertEqual(json.loads(raw), {"文本": "你好"})
            self.assertFalse(any(p.name.endswith(".tmp") for p in target.parent.iterdir()))

    def test_tail_lines_trims(self):
        lines = util.tail_lines("a\n\nb\nc\n", 2)
        self.assertEqual(lines, ["b", "c"])


class SecretNamesTest(unittest.TestCase):
    def test_secret_env_names_are_names_only(self):
        for name in util.SECRET_ENV_NAMES:
            self.assertEqual(name, name.upper())
            self.assertNotIn(" ", name)
        self.assertIn("LSTTS_TTS_TOKEN", util.SECRET_ENV_NAMES)
        self.assertNotIn("MELOTTS_HOME", util.SECRET_ENV_NAMES)

    def test_no_secret_value_present_in_environment(self):
        # 只检查"值不进代码"这一条：本模块里不应出现实际凭据
        source = (Path(lib.REPO_ROOT) / "tts_runtime" / "util.py").read_text(encoding="utf-8")
        self.assertNotIn("sk-", source)


if __name__ == "__main__":
    unittest.main()
