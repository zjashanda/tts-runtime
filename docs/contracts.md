# 契约

所有对外结构都是 JSON，带 `schema` 字段。Schema 文件在 `schemas/`，`additionalProperties: true` 允许上层扩展，但下表字段是稳定契约。

## 时间字段（全局）

所有时间字段共用一种格式：`YYYY-MM-DD HH:MM:SS`，北京时间、无时区后缀、无亚秒位。schema 用 `pattern` 约束（不使用 date-time 格式）；事件流的 `at`、日志、回执与文档示例同此格式。外部原始时间只允许出现在显式的 `raw_*` 字段里，读取后经 `tts_runtime.util.parse_raw_time()` 归一化，禁止原样回显到契约字段。`tools/time_lint.py --gate` 在发布门禁中强制这一点。

## `ark.tts-request.v1`（请求）

Python 侧由 `tts_runtime.models.Request` 构造，CLI 侧由参数映射。

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 必填，非空 |
| `output` | string | 输出 wav 路径 |
| `engine` | string | `auto`/`lstts`/`melotts`/`mock` |
| `voice` | string? | 音色名或参考音频路径 |
| `emotion` | string? | 情感参考音频（仅 lstts） |
| `language` | string? | `ZH`/`EN`（melotts） |
| `speed` | number? | 语速（melotts） |
| `timeout_s` | number? | 单次超时 |
| `validate` | boolean | 是否因音频体检失败而判失败 |

## `ark.tts-result.v1`（单条结果）

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | const | `ark.tts-result.v1` |
| `engine` | enum | `lstts`/`melotts`/`mock` |
| `ok` | boolean | 是否成功 |
| `started_at` / `finished_at` | string | 北京时间，无时区后缀，`YYYY-MM-DD HH:MM:SS`（schema `pattern` 约束） |
| `elapsed_s` | number | 耗时秒 |
| `voice` / `language` | string? | 实际使用值 |
| `text_chars` | number | 文本字符数 |
| `audio_path` | string? | 产物路径 |
| `audio` | object? | 见 `AudioInfo` |
| `notes` | string[] | 非致命提示（格式不符、削波、`validate=false` 等） |
| `error` | object? | `{code, message}`，`code ∈ OK/USAGE/FAIL/UNSUPPORTED/BACKEND` |
| `item_id` | string? | 批量时回填 |

`AudioInfo`：`container`、`codec`、`sample_rate`、`channels`、`sample_width`、`frames`、`duration_seconds`、`peak_dbfs`、`mean_db`、`clip_ratio`。

## `ark.tts-job.v1`（批量任务）

```json
{
  "schema": "ark.tts-job.v1",
  "name": "batch-name",
  "engine": "auto",
  "language": "ZH",
  "speed": null,
  "workers": 1,
  "items": [
    {"id": "unique-id", "text": "...", "voice": null, "emotion": null,
     "language": null, "speed": null, "validate": true}
  ]
}
```

约束（违反 → USAGE，退出 1）：

- `items` 非空数组；`id` 非空且唯一。
- 每条 item 在 `text` 与 `text_file` 之间**恰好**二选一。
- `text_file` 相对路径按 job 文件所在目录解析；文件必须存在。

## `ark.tts-batch.v1`（批量结果）

`{schema, job, engine, out_dir, workers, started_at, finished_at, elapsed_s, ok, succeeded, failed, items[]}`；`items[]` 是 `ark.tts-result.v1` 数组。落盘文件名 `batch-result.json`。

## `ark.tts-voice.v1`（音色）

`{name, engine, kind: "builtin"|"reference", path, languages[]}`。

## `ark.tts-doctor.v1`（自检）

`{schema, at, version, config, work_dir: {path, writable}, engines: [EngineStatus]}`。`EngineStatus = {engine, available, reason, missing_env[], detail}`。`missing_env` 只含**变量名**，永不含值。

## `ark.env-keys.v1`（环境变量清单）

`{schema, note, placeholder: "<env>", keys: {NAME: "<env>"}}`。值一律 `<env>`；`tests/test_contracts.py` 会强制这一点。

## 退出码

| 码 | 名称 | 触发 |
|---|---|---|
| 0 | OK | 成功（批量要求全部成功） |
| 1 | USAGE | 参数、job 格式、配置里出现凭据键、空文本 |
| 2 | FAIL | 合成失败、音频体检 fatal、批量有失败项 |
| 3 | UNSUPPORTED | 引擎未配置/未安装、语言不支持、未知引擎 |
| 4 | BACKEND | HTTP 非 200、超时、响应类型/zip/路径不合法 |

## 稳定性承诺

- 字段只增不改；删除字段需升 major 并同步 `schemas/`。
- 退出码语义不变。
- 事件名 `start`/`progress`/`item_result`/`complete` 不变。
