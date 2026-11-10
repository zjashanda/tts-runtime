# CHANGELOG

## 0.1.1 — 2026-11-11

统一时间契约修正：所有用户可见/机器可读输出只保留一种时间格式 `YYYY-MM-DD HH:MM:SS`（北京时间，无时区后缀）。

### 变更

- 新增 `util.format_time()` 作为唯一时间出口；`util.format_display` 保留为等价别名。
- 删除 `util.format_rfc3339()` 与 `FMT_RFC3339`：不再输出 T 分隔、时区偏移或亚秒位。
- `util.parse_time()` 更名为 `util.parse_raw_time()`，只用于 `raw_*` 外部原始时间的归一化。
- `schemas/tts-result.v1.json` 的 `started_at` / `finished_at` 改用 `pattern` 约束，不再依赖描述文字。
- 新增 `tools/time_lint.py` / `tools/time-lint.sh`，并把 time lint 接入 `tests/run-all.sh` 门禁。
- README、`docs/architecture.md`、`docs/contracts.md` 的时间示例改为契约格式，并补时间契约章节。

## 0.1.0 — 2026-11-10

首个公开版本，把 `lstts`（云端 IndexTTS）与 `melotts`（本地 MeloTTS）收敛到同一个运行时。

### 新增

- 稳定 Python API：`synthesize`、`synthesize_batch`、`load_job`、`list_voices`、`available_engines`、`inspect_audio`、`doctor`、`EventSink`。
- CLI 子命令：`engines`、`voices`、`synth`、`batch`、`inspect`、`doctor`；统一 `--json` 与 `--events`。
- 三引擎：`lstts`（标准库 urllib 实现 `/v1/clone`、`/v1/emotion`）、`melotts`（子进程委托外部 `MELOTTS_HOME`）、`mock`（离线确定性音频）。
- `auto` 选择顺序与「永不静默回落 mock」规则。
- JSON Schema 契约：`ark.tts-request.v1`、`ark.tts-result.v1`、`ark.tts-job.v1`、`ark.tts-voice.v1`。
- 音频体检：WAV 头解析（PCM/EXTENSIBLE、8/16/24/32 bit）、静音/过短/削波/过长判定。
- 云端 ZIP 防护：唯一 wav、路径穿越、符号链接、加密标志、体积上限。
- 配置白名单：配置文件出现 URL/token/secret/password 等键直接拒绝。
- 统一退出码 0/1/2/3/4；错误信息统一 `redact()`。
- `tools/secret_scan.py` 与 `tests/run-all.sh` 发布门禁。

### 变更（相对旧 skill）

- 删除 `melotts` 中随仓库分发的 `.venv`、`vendor/MeloTTS`、`models/`、`nltk_data/`、`outputs/`（合计数百 MB）。
- `lstts` 的 `oss2`/`openpyxl`/`xlrd` 云音色库与 Excel 结果表不再属于运行时；批量改为 JSON job + JSON 结果。
- 旧环境变量名全部保留为兼容别名，但只从环境读取，不再从 skill 内 `references/*.json` 读 token。

### 已知限制

- `lstts` 不支持 `speed`（传了报 USAGE）；`melotts` 不支持 `emotion`（传了报 USAGE）。
- `melotts` 只支持 `ZH`/`EN`，且需要外部安装自备模型；本仓库不带权重。
- 云音色库（OSS 选音色）与 Excel 报表未移植，需要时由上层工具组合。
