# tts-runtime

统一 TTS 运行时。把原先散落在 `lstts`（云端 IndexTTS）与 `melotts`（本地 MeloTTS）两套 skill 里的能力收进一个稳定接口：同一套 CLI、同一套 JSON 契约、同一套退出码。

**一条命令，三种引擎：**

| 引擎 | 类型 | 依赖 | 用途 |
|---|---|---|---|
| `lstts` | 云端 HTTP（`/v1/clone`、`/v1/emotion`） | 仅标准库 | 生产合成，音色克隆 + 情感参考 |
| `melotts` | 本地子进程 | 外部 `MELOTTS_HOME`（自带 venv/模型，不入库） | 离线/内网合成，中英文 |
| `mock` | 纯本地 | 无 | 契约自检、CI、冒烟测试 |

本仓库**不含**任何虚拟环境、模型权重、音色样本、token 或生成音频。旧 skill 里 `.venv` + `vendor/MeloTTS` 合计约 435MB 的污染在这里被彻底切断：本地引擎通过 `MELOTTS_HOME` 委托外部安装。

## 安装

```bash
# 零依赖，Python >= 3.9
git clone https://github.com/zjashanda/tts-runtime.git
cd tts-runtime
python3 -m pip install .          # 可选：装成 tts-runtime 命令
# 或者不安装，直接用薄封装
./bin/tts-runtime engines
```

Windows（Git Bash / PowerShell）：

```powershell
$env:ARK_TTS_RUNTIME_PYTHON = "C:\Path\To\python.exe"
.\bin\tts-runtime.ps1 engines
```

## 快速开始

```bash
# 1) 看引擎可用性（不会读取或打印任何凭据值）
tts-runtime doctor
tts-runtime engines

# 2) 离线冒烟：mock 引擎，不联网
tts-runtime synth --engine mock --text "你好，世界" --out /tmp/hello.wav

# 3) 云端合成：URL 与 token 只从环境变量读
export TTS_RUNTIME_LSTTS_URL="https://<your-indextts-host>"
export TTS_RUNTIME_LSTTS_TOKEN="<your-token>"
tts-runtime synth --engine lstts --text "今天天气不错" --voice 付小春 --out /tmp/out.wav

# 4) 本地合成：指向已有 MeloTTS 安装
export MELOTTS_HOME="/opt/melotts"
tts-runtime synth --engine melotts --text "本地合成" --language ZH --out /tmp/local.wav

# 5) 批量
tts-runtime batch --job tests/fixtures/job.example.json --out-dir /tmp/batch --workers 4

# 6) 音频体检
tts-runtime inspect /tmp/hello.wav
```

## 环境变量

**所有 URL、token、密钥只从环境变量读取，配置文件里出现这些键会被直接拒绝（退出码 1）。**

| 变量 | 作用 | 优先级 |
|---|---|---|
| `TTS_RUNTIME_LSTTS_URL` | 云端 IndexTTS 基地址 | > `LSTTS_TTS_URL` > `LSTEST_TTS_URL` |
| `TTS_RUNTIME_LSTTS_TOKEN` | 云端 Bearer token | > `LSTTS_TTS_TOKEN` > `LSTEST_TTS_TOKEN` |
| `TTS_RUNTIME_VOICE_DIR` | 音色参考音频目录 | > `LSTEST_VOICE_DIR` |
| `TTS_RUNTIME_TIMEOUT` | 单次请求超时秒数 | > `LSTEST_TTS_TIMEOUT` |
| `MELOTTS_HOME` | 外部 MeloTTS 安装目录（含 `scripts/synth.py`、`.venv`、`models/`） | — |
| `MELOTTS_PYTHON` | 显式指定解释器（缺省用 `$MELOTTS_HOME/.venv/bin/python`） | — |
| `TTS_RUNTIME_ENGINE` | 强制引擎：`lstts`/`melotts`/`mock`；`auto` 表示自动 | — |
| `TTS_RUNTIME_LANGUAGE` | 缺省语言（`ZH`/`EN`） | — |
| `TTS_RUNTIME_CONFIG` | 配置文件路径（缺省 `~/.config/ark/tts-runtime.json`） | — |
| `TTS_RUNTIME_WORK` | 临时工作目录 | — |

完整清单见 `config/env-keys.json`（只登记变量名，值一律 `<env>`）。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 用法 / 契约错误（参数、job 格式、配置里出现凭据键） |
| 2 | 业务失败（合成失败、音频校验不过、批量中有失败项） |
| 3 | 平台不支持（引擎未配置/未安装、语言不支持） |
| 4 | 后端不可用（HTTP 错误、超时、响应不合法） |

`auto` 的选择顺序：`TTS_RUNTIME_ENGINE` → `lstts`（已配置）→ `melotts`（已安装）→ 退出 3。**永不静默回落到 mock**：假装成功比明确报错危险得多。

## Python API

```python
from tts_runtime import synthesize, synthesize_batch, load_job, inspect_audio, doctor

result = synthesize("你好", "/tmp/a.wav", engine="mock")
print(result.ok, result.engine, result.audio.duration_seconds)

batch = synthesize_batch(load_job("job.json"), "/tmp/batch", engine="lstts", workers=4)
print(batch.succeeded, batch.failed)

report = inspect_audio("/tmp/a.wav")
print(report["ok"], report["notes"])
```

稳定导出：`synthesize`、`synthesize_batch`、`list_voices`、`available_engines`、`inspect_audio`、`load_job`、`doctor`、`EventSink`。

## 批量 job（`ark.tts-job.v1`）

```json
{
  "schema": "ark.tts-job.v1",
  "name": "example-batch",
  "engine": "mock",
  "workers": 2,
  "items": [
    {"id": "greeting", "text": "你好"},
    {"id": "from-file", "text_file": "texts/notice.txt"}
  ]
}
```

- `id` 必须唯一；每条 item 在 `text` 与 `text_file` 之间二选一。
- `text_file` 相对路径按 job 文件所在目录解析；编码自动识别 utf-8-sig / gb18030 / utf-16。
- 输出 `{index:03d}-{id}.wav` 与 `batch-result.json`；有失败项时仍写完整结果，退出码 2。

## 事件流

`--events PATH` 输出 JSONL：`start` → `item_result`（批量每条一次）→ `complete`。所有时间戳为北京时间、无时区后缀（`YYYY-MM-DDThh:mm:ss.sss`）。

## 仓库结构

```
tts_runtime/          核心包（引擎、音频、配置、CLI）
bin/                  POSIX + PowerShell 薄封装
schemas/              JSON Schema 契约（request/result/job/voice）
config/               环境变量清单（值一律 <env>）与示例配置
docs/                 架构、契约、引擎、安全、回滚、运维
tests/                unittest + 假 HTTP 服务 + 契约守卫
tools/                secret_scan 敏感信息扫描
```

## 安全

- 不打印、不落盘、不提交任何 token / URL / 密钥；日志与错误信息统一走 `redact()`。
- 云端响应 ZIP 做路径穿越、符号链接、加密标志、体积与数量校验。
- 提交前 `python3 tools/secret_scan.py --gate` 必须 0 命中。
- 详见 `docs/security.md`。

## 迁移

从旧 `lstts` / `melotts` skill 迁移见 `MIGRATION.md`；旧仓库不删除，只做只读对照。

## 许可

MIT，见 `LICENSE`。
