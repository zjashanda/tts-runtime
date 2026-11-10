"""命令行端到端：退出码、JSON 契约、事件流。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import ark_testlib as lib

from tts_runtime import audio, cli


def clean_env():
    values = {key: None for key in lib.CLEAN_ENV_KEYS}
    values["TTS_RUNTIME_CONFIG"] = str(Path(tempfile.gettempdir()) / "tts-runtime-missing-config.json")
    return lib.temp_env(**values)


class CliBasicsTest(unittest.TestCase):
    def test_no_subcommand_prints_help_and_fails_usage(self) -> None:
        with clean_env(), lib.captured() as (out, _err):
            code = cli.main([])
        self.assertEqual(code, 1)
        self.assertIn("usage", out.getvalue().lower())

    def test_version_flag(self) -> None:
        with lib.captured() as (out, _err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("tts-runtime", out.getvalue())

    def test_engines_lists_mock(self) -> None:
        with clean_env(), lib.captured() as (out, _err):
            code = cli.main(["engines"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("mock", text)
        self.assertIn("lstts", text)

    def test_engines_json_contract(self) -> None:
        with clean_env(), lib.captured() as (out, _err):
            code = cli.main(["engines", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "ark.tts-engines.v1")
        names = [item["engine"] for item in payload["engines"]]
        self.assertEqual(names, ["lstts", "melotts", "mock"])
        mock = payload["engines"][-1]
        self.assertTrue(mock["available"])

    def test_voices_json_contract(self) -> None:
        with clean_env(), lib.captured() as (out, _err):
            code = cli.main(["voices", "--engine", "mock", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "ark.tts-voices.v1")
        self.assertEqual([item["name"] for item in payload["voices"]], ["tone-440", "tone-880"])

    def test_voices_without_engine_never_crashes(self) -> None:
        with clean_env(), lib.captured() as (out, _err):
            code = cli.main(["voices"])
        self.assertEqual(code, 0)
        self.assertIn("tone-440", out.getvalue())

    def test_unknown_engine_exits_unsupported(self) -> None:
        with clean_env(), lib.captured() as (_out, err):
            code = cli.main(["voices", "--engine", "nope"])
        self.assertEqual(code, 3)
        self.assertIn("UNSUPPORTED", err.getvalue())


class CliSynthTest(unittest.TestCase):
    def test_synth_mock_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            target = Path(raw_dir) / "hello.wav"
            with clean_env(), lib.captured() as (out, _err):
                code = cli.main(["synth", "--engine", "mock", "--text", "你好世界", "--out", str(target)])
            self.assertEqual(code, 0)
            self.assertTrue(target.is_file())
            self.assertIn("OK", out.getvalue())
            audio.inspect_audio(target)

    def test_synth_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            target = Path(raw_dir) / "hello.wav"
            with clean_env(), lib.captured() as (out, _err):
                code = cli.main(
                    ["synth", "--engine", "mock", "--text", "你好", "--out", str(target), "--json"]
                )
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["schema"], "ark.tts-result.v1")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["engine"], "mock")
            self.assertEqual(payload["audio"]["sample_rate"], 16000)

    def test_synth_out_dir_autoname(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with clean_env(), lib.captured() as (_out, _err):
                code = cli.main(
                    ["synth", "--engine", "mock", "--text", "目录输出", "--out-dir", raw_dir]
                )
            self.assertEqual(code, 0)
            produced = sorted(Path(raw_dir).glob("tts-*-mock.wav"))
            self.assertEqual(len(produced), 1)

    def test_synth_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            text_file = root / "text.txt"
            text_file.write_text("从文件读入的文本\n", encoding="utf-8")
            target = root / "out.wav"
            with clean_env(), lib.captured() as (_out, _err):
                code = cli.main(
                    ["synth", "--engine", "mock", "--text-file", str(text_file), "--out", str(target)]
                )
            self.assertEqual(code, 0)
            self.assertTrue(target.is_file())

    def test_synth_missing_text_file_is_usage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with clean_env(), lib.captured() as (_out, err):
                code = cli.main(
                    [
                        "synth",
                        "--engine",
                        "mock",
                        "--text-file",
                        str(Path(raw_dir) / "nope.txt"),
                        "--out",
                        str(Path(raw_dir) / "out.wav"),
                    ]
                )
            self.assertEqual(code, 1)
            self.assertIn("USAGE", err.getvalue())

    def test_synth_empty_text_is_usage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with clean_env(), lib.captured() as (_out, err):
                code = cli.main(
                    ["synth", "--engine", "mock", "--text", "  ", "--out", str(Path(raw_dir) / "o.wav")]
                )
            self.assertEqual(code, 1)
            self.assertIn("文本为空", err.getvalue())

    def test_synth_auto_without_backend_exits_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with clean_env(), lib.captured() as (_out, err):
                code = cli.main(["synth", "--text", "你好", "--out", str(Path(raw_dir) / "o.wav")])
            self.assertEqual(code, 3)
            self.assertIn("UNSUPPORTED", err.getvalue())

    def test_synth_events_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            events = root / "events.jsonl"
            with clean_env(), lib.captured() as (_out, _err):
                code = cli.main(
                    [
                        "synth",
                        "--engine",
                        "mock",
                        "--text",
                        "事件流",
                        "--out",
                        str(root / "o.wav"),
                        "--events",
                        str(events),
                    ]
                )
            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual([row["event"] for row in rows], ["start", "item_result", "complete"])
            self.assertTrue(all("at" in row for row in rows))

    def test_mutually_exclusive_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with clean_env(), lib.captured() as (_out, _err):
                with self.assertRaises(SystemExit) as ctx:
                    cli.main(
                        [
                            "synth",
                            "--engine",
                            "mock",
                            "--text",
                            "x",
                            "--out",
                            str(Path(raw_dir) / "a.wav"),
                            "--out-dir",
                            raw_dir,
                        ]
                    )
            self.assertEqual(ctx.exception.code, 2)


class CliBatchTest(unittest.TestCase):
    def test_batch_mock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            job = {
                "schema": "ark.tts-job.v1",
                "name": "cli-batch",
                "engine": "mock",
                "items": [
                    {"id": "a", "text": "第一条"},
                    {"id": "b", "text": "第二条"},
                ],
            }
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            out_dir = root / "out"
            with clean_env(), lib.captured() as (out, _err):
                code = cli.main(["batch", "--job", str(job_path), "--out-dir", str(out_dir), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["schema"], "ark.tts-batch.v1")
            self.assertEqual(payload["engine"], "mock")
            self.assertEqual(len(payload["items"]), 2)
            self.assertTrue((out_dir / "001-a.wav").is_file())
            self.assertTrue((out_dir / "002-b.wav").is_file())
            self.assertTrue((out_dir / "batch-result.json").is_file())

    def test_batch_bad_job_is_usage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            job_path = root / "job.json"
            job_path.write_text(
                json.dumps({"schema": "ark.tts-job.v0", "items": [{"id": "a", "text": "x"}]}),
                encoding="utf-8",
            )
            with clean_env(), lib.captured() as (_out, err):
                code = cli.main(["batch", "--job", str(job_path), "--out-dir", str(root / "out")])
            self.assertEqual(code, 1)
            self.assertIn("USAGE", err.getvalue())


class CliInspectDoctorTest(unittest.TestCase):
    def test_inspect_good_wav(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            target = lib.make_wav(Path(raw_dir) / "ok.wav")
            with clean_env(), lib.captured() as (out, _err):
                code = cli.main(["inspect", str(target), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["audio"]["channels"], 1)

    def test_inspect_missing_file_exits_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with clean_env(), lib.captured() as (_out, _err):
                code = cli.main(["inspect", str(Path(raw_dir) / "nope.wav")])
            self.assertEqual(code, 2)

    def test_doctor_json(self) -> None:
        with clean_env(), lib.captured() as (out, _err):
            code = cli.main(["doctor", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "ark.tts-doctor.v1")
        self.assertIn("work_dir", payload)
        self.assertEqual([item["engine"] for item in payload["engines"]], ["lstts", "melotts", "mock"])
        self.assertNotIn("token", json.dumps(payload["config"]))

    def test_doctor_human_output(self) -> None:
        with clean_env(), lib.captured() as (out, _err):
            code = cli.main(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("writable=True", out.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
