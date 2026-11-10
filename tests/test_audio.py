# -*- coding: utf-8 -*-
"""audio：WAV 解析、fatal/notes 判定、确定性写盘。"""

import struct
import tempfile
import unittest
from pathlib import Path

import ark_testlib as lib
from tts_runtime import audio


class InspectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_header_and_levels(self):
        target = lib.make_wav(self.root / "ok.wav", seconds=1.0, amplitude=8000)
        info = audio.inspect_audio(target)
        self.assertEqual(info.container, "wav")
        self.assertEqual(info.codec, "pcm_s16le")
        self.assertEqual(info.sample_rate, 16000)
        self.assertEqual(info.channels, 1)
        self.assertEqual(info.sample_width, 2)
        self.assertEqual(info.frames, 16000)
        self.assertAlmostEqual(info.duration_seconds, 1.0, places=3)
        self.assertLess(info.peak_dbfs, 0)
        self.assertGreater(info.mean_db, -60)
        self.assertEqual(info.clip_ratio, 0.0)

    def test_stereo_frame_count(self):
        target = lib.make_wav(self.root / "stereo.wav", seconds=0.5, channels=2)
        info = audio.inspect_audio(target)
        self.assertEqual(info.channels, 2)
        self.assertAlmostEqual(info.duration_seconds, 0.5, places=3)

    def test_extensible_pcm_is_accepted(self):
        # 手工造一个 WAVE_FORMAT_EXTENSIBLE（PCM 子格式）文件头
        samples = struct.pack("<" + "h" * 800, *([-8000, 8000] * 400))
        fmt = struct.pack("<HHIIHH", audio.WAVE_FORMAT_EXTENSIBLE, 1, 16000, 32000, 2, 16)
        fmt += struct.pack("<H", 22) + struct.pack("<H", 16) + struct.pack("<I", 4)
        fmt += b"\x01\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        body = b"fmt " + struct.pack("<I", len(fmt)) + fmt
        body += b"data" + struct.pack("<I", len(samples)) + samples
        riff = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body
        target = self.root / "ext.wav"
        target.write_bytes(riff)
        info = audio.inspect_audio(target)
        self.assertEqual(info.sample_rate, 16000)
        self.assertEqual(info.frames, 800)

    def test_rejects_non_riff(self):
        target = self.root / "fake.wav"
        target.write_bytes(b"ID3\x03\x00")
        with self.assertRaises(ValueError):
            audio.inspect_audio(target)

    def test_rejects_missing_file(self):
        with self.assertRaises(ValueError):
            audio.inspect_audio(self.root / "nope.wav")


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_audio_has_no_flags(self):
        target = lib.make_wav(self.root / "ok.wav", seconds=0.6)
        info, fatal, notes = audio.evaluate(target)
        self.assertIsNotNone(info)
        self.assertEqual(fatal, [])
        self.assertEqual(notes, [])

    def test_silence_is_fatal(self):
        target = lib.silent_wav(self.root / "silent.wav", seconds=0.6)
        info, fatal, notes = audio.evaluate(target)
        self.assertTrue(any(item.startswith(audio.FLAG_SILENT) for item in fatal))

    def test_too_short_is_fatal(self):
        target = lib.make_wav(self.root / "short.wav", seconds=0.01)
        info, fatal, notes = audio.evaluate(target)
        self.assertTrue(any(item.startswith(audio.FLAG_TOO_SHORT) for item in fatal))

    def test_unreadable_is_fatal_not_exception(self):
        target = self.root / "bad.wav"
        target.write_bytes(b"not a wav")
        info, fatal, notes = audio.evaluate(target)
        self.assertIsNone(info)
        self.assertTrue(any(item.startswith(audio.FLAG_UNREADABLE) for item in fatal))

    def test_full_scale_is_flagged_as_clipping_note(self):
        target = lib.make_wav(self.root / "clip.wav", seconds=0.4, amplitude=32767)
        info, fatal, notes = audio.evaluate(target)
        self.assertEqual(fatal, [])
        self.assertTrue(any(item.startswith(audio.FLAG_CLIPPED) for item in notes))


class WriteToneTest(unittest.TestCase):
    def test_tone_is_valid_16k_mono(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "tone.wav"
            info = audio.write_tone(target, seconds=0.25, frequency=440)
            self.assertTrue(target.is_file())
            self.assertEqual(info.sample_rate, 16000)
            self.assertEqual(info.channels, 1)
            self.assertAlmostEqual(info.duration_seconds, 0.25, places=3)
            self.assertGreater(info.peak_dbfs, -20)


if __name__ == "__main__":
    unittest.main()
