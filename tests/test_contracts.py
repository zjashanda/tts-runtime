"""仓库自身的契约守卫：schema、环境变量清单、忽略规则、无污染、无凭据。"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import ark_testlib as lib

from tts_runtime import __version__
from tts_runtime import models
from tts_runtime.config import sanitize

ROOT = lib.REPO_ROOT

SCHEMA_FILES = {
    "tts-request.v1.json": models.REQUEST_SCHEMA,
    "tts-result.v1.json": models.RESULT_SCHEMA,
    "tts-job.v1.json": models.JOB_SCHEMA,
    "tts-voice.v1.json": models.VOICE_SCHEMA,
}

FORBIDDEN_DIRS = {".venv", "venv", "env", "vendor", "models", "nltk_data", "outputs", "__pycache__"}
FORBIDDEN_SUFFIXES = {".pth", ".so", ".dll", ".dylib", ".pyc", ".pt", ".bin"}
FORBIDDEN_NAMES = {".git-credentials", "id_rsa", "id_ed25519", "auth.json"}
FORBIDDEN_NAME_SUFFIXES = {".pem", ".pfx", ".p12"}

REQUIRED_FILES = (
    "README.md",
    "SKILL.md",
    "CHANGELOG.md",
    "MIGRATION.md",
    "VERSION",
    "LICENSE",
    "pyproject.toml",
    ".gitignore",
    ".gitattributes",
    "bin/tts-runtime",
    "bin/tts-runtime.ps1",
    "config/env-keys.json",
    "config/runtime.example.json",
    "docs/architecture.md",
    "docs/contracts.md",
    "docs/engines.md",
    "docs/security.md",
    "docs/rollback.md",
    "docs/runbook.md",
    "tests/run-all.sh",
    "tools/secret_scan.py",
)


IGNORED_PARTS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".egg-info", "build", "dist"}


def repo_files():
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in IGNORED_PARTS for part in rel.parts):
            continue
        if path.is_file():
            yield rel


class SchemaTest(unittest.TestCase):
    def test_every_schema_is_valid_json_with_schema_id(self) -> None:
        for name, expected_id in SCHEMA_FILES.items():
            path = ROOT / "schemas" / name
            self.assertTrue(path.is_file(), name)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("$schema"), "http://json-schema.org/draft-07/schema#")
            self.assertTrue(str(payload.get("$id", "")).endswith(name), name)
            self.assertEqual(payload.get("title"), expected_id)
            self.assertEqual(payload.get("type"), "object")
            self.assertIn("properties", payload)

    def test_result_schema_documents_exit_codes(self) -> None:
        payload = json.loads((ROOT / "schemas" / "tts-result.v1.json").read_text(encoding="utf-8"))
        props = payload["properties"]
        for key in ("engine", "ok", "audio_path", "audio", "notes", "error"):
            self.assertIn(key, props)
        self.assertEqual(sorted(props["engine"]["enum"]), ["lstts", "melotts", "mock"])

    def test_job_schema_requires_items(self) -> None:
        payload = json.loads((ROOT / "schemas" / "tts-job.v1.json").read_text(encoding="utf-8"))
        self.assertIn("items", payload.get("required", []))


class EnvKeysTest(unittest.TestCase):
    def test_env_keys_never_carry_values(self) -> None:
        payload = json.loads((ROOT / "config" / "env-keys.json").read_text(encoding="utf-8"))
        self.assertEqual(payload.get("schema"), "ark.env-keys.v1")
        keys = payload.get("keys")
        self.assertIsInstance(keys, dict)
        self.assertGreaterEqual(len(keys), 10)
        for name, value in keys.items():
            self.assertRegex(name, r"^[A-Z][A-Z0-9_]+$")
            self.assertEqual(value, "<env>", name)

    def test_env_keys_cover_both_namespaces(self) -> None:
        payload = json.loads((ROOT / "config" / "env-keys.json").read_text(encoding="utf-8"))
        keys = payload["keys"]
        for name in ("TTS_RUNTIME_LSTTS_URL", "TTS_RUNTIME_LSTTS_TOKEN", "MELOTTS_HOME"):
            self.assertIn(name, keys)
        for name in ("LSTTS_TTS_TOKEN", "LSTEST_TTS_URL", "LSTEST_VOICE_DIR"):
            self.assertIn(name, keys)
        token_names = [name for name in keys if "TOKEN" in name]
        self.assertEqual(len(token_names), 3)

    def test_example_config_is_accepted_and_has_no_endpoint(self) -> None:
        raw = json.loads((ROOT / "config" / "runtime.example.json").read_text(encoding="utf-8"))
        clean = sanitize(raw, source="config/runtime.example.json")
        self.assertEqual(clean["engine"], "auto")
        text = json.dumps(raw).lower()
        for banned in ("token", "secret", "password", "http://", "https://", "base_url", "endpoint"):
            self.assertNotIn(banned, text)


class VersionTest(unittest.TestCase):
    def test_version_sources_agree(self) -> None:
        version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(version_file, __version__)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "{0}"'.format(__version__), pyproject)
        self.assertIn('name = "tts-runtime"', pyproject)

    def test_changelog_mentions_current_version(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(__version__, changelog)


class HygieneTest(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for rel in REQUIRED_FILES:
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_gitignore_blocks_virtualenv_and_models(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".venv/", "venv/", "vendor/", "models/", "nltk_data/", "outputs/", "*.pth", "*.so"):
            self.assertIn(pattern, text)
        self.assertIn("!tests/fixtures/*.wav", text)

    def test_tree_contains_no_virtualenv_vendor_or_models(self) -> None:
        for rel in repo_files():
            for part in rel.parts:
                self.assertNotIn(part, FORBIDDEN_DIRS, str(rel))
            suffix = rel.suffix.lower()
            self.assertNotIn(suffix, FORBIDDEN_SUFFIXES, str(rel))
            self.assertNotIn(rel.name, FORBIDDEN_NAMES, str(rel))
            self.assertNotIn(suffix, FORBIDDEN_NAME_SUFFIXES, str(rel))

    def test_only_fixture_audio_is_tracked(self) -> None:
        for rel in repo_files():
            if rel.suffix.lower() == ".wav":
                self.assertTrue(str(rel).startswith("tests/fixtures"), str(rel))

    def test_no_hardcoded_endpoint_or_token(self) -> None:
        token_pattern = re.compile(r"(ghp_|github_pat_|sk-[A-Za-z0-9]{16,}|LTAI[0-9A-Za-z]{12,})")
        for rel in repo_files():
            if rel.suffix.lower() in {".wav", ".png", ".jpg"}:
                continue
            if rel.parts[0] in {".git"}:
                continue
            try:
                text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:  # pragma: no cover - 读不了就跳过
                continue
            if rel.as_posix() not in ("tests/test_contracts.py", "tools/secret_scan.py", "docs/security.md"):
                self.assertIsNone(token_pattern.search(text), str(rel))
            if rel.parts[0] == "tests" or rel.as_posix() in (
                "tools/secret_scan.py",
                "docs/security.md",
                "MIGRATION.md",
            ):
                continue
            self.assertNotRegex(
                text,
                r"https?://(?!127\.0\.0\.1|localhost|json-schema|ark\.example|github\.com/zjashanda/tts-runtime)[a-z0-9.-]+",
                str(rel),
            )


class FixtureJobTest(unittest.TestCase):
    def test_example_job_is_valid(self) -> None:
        from tts_runtime.core import load_job

        job = load_job(ROOT / "tests" / "fixtures" / "job.example.json")
        self.assertEqual(job["schema"], models.JOB_SCHEMA)
        self.assertTrue(job["items"])
        for item in job["items"]:
            self.assertTrue(item["text"].strip())

    def test_scripts_are_executable_or_documented(self) -> None:
        script = ROOT / "bin" / "tts-runtime"
        self.assertTrue(script.is_file())
        self.assertIn("tts_runtime", script.read_text(encoding="utf-8"))
        wrapper = ROOT / "bin" / "tts-runtime.ps1"
        self.assertIn("tts_runtime", wrapper.read_text(encoding="utf-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
