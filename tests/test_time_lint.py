# -*- coding: utf-8 -*-
"""时间契约：lint 规则有效性 + 真实输出（JSON / 事件流 / schema）的格式校验。"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import ark_testlib as lib
from tts_runtime import core, util
from tts_runtime.events import EventSink

_LINT_PATH = Path(lib.REPO_ROOT) / "tools" / "time_lint.py"


def _load_lint():
    spec = importlib.util.spec_from_file_location("time_lint", str(_LINT_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_lint()


class TimeLintRuleTest(unittest.TestCase):
    def test_detects_each_violation(self):
        samples = {
            "2026-11-10" + "T" + "21:46:03": "iso-t-separator",
            "at 21:46:03" + "Z": "iso-z-suffix",
            "at 21:46:03" + "+08:00": "iso-offset",
            "2026-11-10 21:46:03" + ".225": "subsecond",
            '"format": ' + '"date-time"': "schema-date-time",
            'FMT = "%Y-%m-%d' + 'T%H:%M:%S"': "strftime-t",
        }
        for sample, expected in samples.items():
            rules = [v.rule for v in lint.scan_text(sample)]
            self.assertIn(expected, rules, sample)

    def test_contract_sample_is_clean(self):
        self.assertEqual(lint.scan_text("2026-11-10 21:46:03"), [])

    def test_allow_marker_is_line_scoped(self):
        text = "# " + lint.ALLOW_MARK + " 2026-11-10" + "T" + "21:46:03\n2026-11-10" + "T" + "21:46:04\n"
        hits = lint.scan_text(text)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].line, 2)

    def test_self_test_passes(self):
        self.assertTrue(lint.self_test())

    def test_repository_has_zero_violations(self):
        found = lint.scan(Path(lib.REPO_ROOT))
        self.assertEqual([v.to_dict() for v in found], [])

    def test_gate_exit_code(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "bad.md").write_text("2026-11-10" + "T" + "21:46:03\n", encoding="utf-8")
            self.assertEqual(lint.main(["--root", str(root), "--gate", "--quiet"]), 1)
            (root / "bad.md").write_text("2026-11-10 21:46:03\n", encoding="utf-8")
            self.assertEqual(lint.main(["--root", str(root), "--gate", "--quiet"]), 0)


class ContractOutputTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_result_timestamps_match_contract(self):
        result = core.synthesize("你好世界", output=self.root / "a.wav", engine="mock")
        payload = result.to_dict()
        self.assertTrue(util.is_contract_time(payload["started_at"]))
        self.assertTrue(util.is_contract_time(payload["finished_at"]))
        self.assertIn("started_at", json.dumps(payload, ensure_ascii=False))

    def test_batch_result_timestamps_match_contract(self):
        job = {
            "schema": "ark.tts-job.v1",
            "engine": "mock",
            "items": [{"id": "one", "text": "第一段"}, {"id": "two", "text": "第二段"}],
        }
        batch = core.synthesize_batch(job, self.root / "out", workers=2)
        payload = batch.to_dict()
        self.assertTrue(util.is_contract_time(payload["started_at"]))
        self.assertTrue(util.is_contract_time(payload["finished_at"]))

    def test_event_stream_at_is_contract(self):
        events = self.root / "events.jsonl"
        sink = EventSink(events)
        core.synthesize("事件流", output=self.root / "e.wav", engine="mock", events=sink)
        lines = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 2)
        for record in lines:
            self.assertTrue(util.is_contract_time(record["at"]), record)

    def test_result_schema_pattern_rejects_rfc3339(self):
        schema = json.loads((Path(lib.REPO_ROOT) / "schemas" / "tts-result.v1.json").read_text(encoding="utf-8"))
        pattern = schema["properties"]["started_at"]["pattern"]
        self.assertEqual(pattern, util.TIME_CONTRACT_PATTERN)
        for key in ("started_at", "finished_at"):
            self.assertNotIn("format", schema["properties"][key])


if __name__ == "__main__":
    unittest.main()
