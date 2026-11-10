# -*- coding: utf-8 -*-
"""melotts 本地引擎：委托子进程、缺失判定、产物回收。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import ark_testlib as lib
from tts_runtime.engines.melotts import MelottsEngine
from tts_runtime.models import Request

FAKE_SYNTH = r'''
import argparse, json, os, struct, wave

parser = argparse.ArgumentParser()
parser.add_argument("--language")
parser.add_argument("--speaker")
parser.add_argument("--text")
parser.add_argument("--out-dir")
parser.add_argument("--speed", type=float, default=1.0)
args = parser.parse_args()

lines = [line for line in open(args.text, encoding="utf-8").read().splitlines() if line.strip()]
for index, _ in enumerate(lines, 1):
    target = os.path.join(args.out_dir, "%03d.wav" % index)
    with wave.open(target, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"".join(struct.pack("<h", 8000 if i % 2 == 0 else -8000) for i in range(3200)))

with open(os.path.join(os.getcwd(), "invocation.json"), "w", encoding="utf-8") as handle:
    json.dump({"language": args.language, "speaker": args.speaker, "speed": args.speed}, handle)
'''


def build_home(root: Path, *, model: bool = True, script: bool = True) -> Path:
    home = root / "melotts"
    (home / "scripts").mkdir(parents=True)
    if script:
        (home / "scripts" / "synth.py").write_text(FAKE_SYNTH, encoding="utf-8")
    if model:
        model_dir = home / "models" / "ZH"
        model_dir.mkdir(parents=True)
        (model_dir / "config.json").write_text(
            json.dumps({"data": {"spk2id": {"ZH": 0, "test-speaker": 1}}}), encoding="utf-8"
        )
        (model_dir / "checkpoint.pth").write_bytes(b"fake-checkpoint")
    bin_dir = home / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    if not python.exists():
        os.symlink(sys.executable, str(python))
    return home


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = build_home(self.root)
        self.out = self.root / "out" / "zh.wav"

    def tearDown(self):
        self._tmp.cleanup()

    def request(self, **kwargs):
        payload = dict(text="第一行\n第二行", output=self.out, engine="melotts", language="ZH")
        payload.update(kwargs)
        return Request(**payload)

    def synthesize(self, home=None, **kwargs):
        value = str(home) if home is not None else str(self.home)
        with lib.temp_env(MELOTTS_HOME=value, MELOTTS_PYTHON=None,
                          TTS_RUNTIME_WORK=str(self.root / "work")):
            return MelottsEngine().synthesize(self.request(**kwargs))


class SuccessTest(Base):
    def test_synthesizes_via_child_process(self):
        result = self.synthesize(voice="test-speaker", speed=1.08)
        self.assertTrue(result.ok, result.error)
        self.assertTrue(self.out.is_file())
        self.assertEqual(result.audio.sample_rate, 16000)
        self.assertEqual(result.audio.channels, 1)
        self.assertEqual(result.voice, "test-speaker")
        self.assertEqual(result.notes, [])
        invocation = json.loads((self.home / "invocation.json").read_text(encoding="utf-8"))
        self.assertEqual(invocation["language"], "ZH")
        self.assertEqual(invocation["speaker"], "test-speaker")
        self.assertAlmostEqual(invocation["speed"], 1.08, places=2)

    def test_default_voice_per_language(self):
        result = self.synthesize()
        self.assertTrue(result.ok, result.error)
        invocation = json.loads((self.home / "invocation.json").read_text(encoding="utf-8"))
        self.assertEqual(invocation["speaker"], "ZH")

    def test_temp_workdir_is_cleaned(self):
        self.synthesize()
        work = self.root / "work"
        leftovers = [path for path in work.iterdir() if path.is_dir()]
        self.assertEqual(leftovers, [])


class FailureTest(Base):
    def test_missing_home_is_unsupported(self):
        with lib.temp_env(MELOTTS_HOME=None, MELOTTS_PYTHON=None):
            result = MelottsEngine().synthesize(self.request())
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "UNSUPPORTED")
        self.assertIn("MELOTTS_HOME", result.error["message"])

    def test_missing_checkpoint_is_unsupported(self):
        home = build_home(self.root / "broken", model=False)
        result = self.synthesize(home=home)
        self.assertEqual(result.error["code"], "UNSUPPORTED")
        self.assertIn("checkpoint.pth", result.error["message"])

    def test_missing_script_is_unsupported(self):
        home = build_home(self.root / "noscript", script=False)
        result = self.synthesize(home=home)
        self.assertEqual(result.error["code"], "UNSUPPORTED")
        self.assertIn("synth.py", result.error["message"])

    def test_unsupported_language(self):
        result = self.synthesize(language="FR")
        self.assertEqual(result.error["code"], "UNSUPPORTED")
        self.assertIn("ZH/EN", result.error["message"])

    def test_emotion_is_usage(self):
        emotion = lib.make_wav(self.root / "emo.wav")
        result = self.synthesize(emotion=emotion)
        self.assertEqual(result.error["code"], "USAGE")
        self.assertIn("emotion", result.error["message"])

    def test_child_failure_is_fail(self):
        (self.home / "scripts" / "synth.py").write_text("import sys\nsys.stderr.write('boom')\nsys.exit(3)\n",
                                                         encoding="utf-8")
        result = self.synthesize()
        self.assertEqual(result.error["code"], "FAIL")
        self.assertIn("退出码 3", result.error["message"])
        self.assertIn("boom", result.error["message"])

    def test_child_without_output_is_fail(self):
        (self.home / "scripts" / "synth.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        result = self.synthesize()
        self.assertEqual(result.error["code"], "FAIL")
        self.assertIn("未产出 wav", result.error["message"])


class StatusAndVoicesTest(Base):
    def test_status_available(self):
        with lib.temp_env(MELOTTS_HOME=str(self.home), MELOTTS_PYTHON=None):
            status = MelottsEngine().status()
        self.assertTrue(status.available, status.reason)
        self.assertEqual(status.missing_env, [])
        self.assertEqual(status.detail["languages"], ["ZH", "EN"])

    def test_status_missing(self):
        with lib.temp_env(MELOTTS_HOME=None, MELOTTS_PYTHON=None):
            status = MelottsEngine().status()
        self.assertFalse(status.available)
        self.assertEqual(status.missing_env, ["MELOTTS_HOME"])

    def test_voices_include_config_speakers(self):
        with lib.temp_env(MELOTTS_HOME=str(self.home), MELOTTS_PYTHON=None):
            voices = MelottsEngine().voices()
        names = [item.name for item in voices]
        self.assertIn("ZH", names)
        self.assertIn("test-speaker", names)
        self.assertIn("EN-Default", names)

    def test_voices_without_home_still_lists_defaults(self):
        with lib.temp_env(MELOTTS_HOME=None, MELOTTS_PYTHON=None):
            names = [item.name for item in MelottsEngine().voices()]
        self.assertEqual(names, ["ZH", "EN-Default"])


if __name__ == "__main__":
    unittest.main()
