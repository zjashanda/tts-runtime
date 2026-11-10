# 迁移指南：lstts / melotts → tts-runtime

旧仓库**不删除、不改 main**。本文件只描述如何把调用方切到新入口，旧仓库保留为只读对照。

## 1. 命令对照

### lstts（云端 IndexTTS）

| 旧 | 新 |
|---|---|
| `python scripts/synthesize.py --job job.json` | `tts-runtime batch --job job.json --out-dir out/` |
| `python scripts/synthesize.py --job job.json --preview` | `tts-runtime batch --job job.json --out-dir out/ --json`（先看 items/engine 再实跑） |
| `python -c "from lstts_core import synthesize_one; ..."` | `from tts_runtime import synthesize; synthesize(text, out, engine="lstts")` |
| `LSTTS_TTS_TOKEN` / `LSTEST_TTS_TOKEN` | 继续可用；推荐 `TTS_RUNTIME_LSTTS_TOKEN` |
| `LSTEST_TTS_URL` | 继续可用；推荐 `TTS_RUNTIME_LSTTS_URL` |
| `LSTEST_VOICE_DIR` / `~/.lstest/voices` | 继续可用；推荐 `TTS_RUNTIME_VOICE_DIR` |
| skill 内 `references/index_tts.json` 存 base_url/token | **取消**：配置文件出现 URL/token 键会被拒绝，只从环境变量读 |

旧 job 字段到新 job 的映射：

| 旧 job | 新 job（`ark.tts-job.v1`） |
|---|---|
| `text` / `text_file`（顶层，整批共用） | `items[].text` / `items[].text_file` |
| `speaker` | `items[].voice` |
| `emotion` | `items[].emotion` |
| `output` | CLI `--out-dir` |
| `max_text_tokens` | 取消：调用方自行切分后再入 items |
| `validate_audio` | `items[].validate` |
| `cloud` / OSS 选音色 | 取消：先用上层工具选出音色路径，再写进 `items[].voice` |

旧行为差异（有意为之）：

- 旧版输出 `合成结果.xlsx`；新版输出 `batch-result.json` + `{index:03d}-{id}.wav`。需要 Excel 的由上层脚本转换。
- 旧版按音色分子目录；新版平铺，`id` 唯一即可区分。
- 旧版 `xlsx` 输入、`split_long` 自动切分不再内置。

### melotts（本地 MeloTTS）

| 旧 | 新 |
|---|---|
| `./tts --language ZH --text texts.txt --out-dir out/` | `MELOTTS_HOME=<旧目录> tts-runtime synth --engine melotts --language ZH --text-file texts.txt --out-dir out/`（单条）或 `batch`（多条） |
| `./tts --speaker all` | 对每个 speaker 生成一条 item，`items[].voice` 指定 |
| `--concurrency 8` | `batch --workers 8` |
| `--speed 1.08` | `--speed 1.08` / `items[].speed` |
| `--limit` / `--threads-per-worker` / `--stagger-load-sec` | 取消：由上层调度控制 |
| 旧目录里的 `.venv`、`vendor/`、`models/`、`nltk_data/` | **留在外部**，用 `MELOTTS_HOME` 指过去；不要复制进任何新仓库 |

`MELOTTS_HOME` 必须包含：

```
$MELOTTS_HOME/scripts/synth.py
$MELOTTS_HOME/.venv/bin/python        # 或 Windows: .venv/Scripts/python.exe
$MELOTTS_HOME/models/ZH/config.json
$MELOTTS_HOME/models/ZH/checkpoint.pth
```

也可以 `MELOTTS_PYTHON=/path/to/python` 指定其它解释器。

## 2. 环境变量收敛

只保留一组「新名优先、旧名兼容」的解析顺序（见 `config/env-keys.json`）。迁移期建议：

1. 在节点上把 `LSTEST_*` 逐个改名为 `TTS_RUNTIME_*`（脚本会自动回退到旧名，可分批）。
2. 确认 `tts-runtime doctor --json` 里 `lstts.available=true`。
3. 再把旧名从节点环境里删掉。

## 3. 退出码对照

| 场景 | 旧 | 新 |
|---|---|---|
| 成功 | 0 | 0 |
| 参数/契约错误 | 1 | 1 |
| 合成失败 | 2 | 2 |
| Ctrl-C | 130 | 2（并打印 interrupted） |
| 引擎未配置/未安装 | 旧版多为 1 或异常 | 3 |
| HTTP/超时/坏响应 | 旧版 2 | 4 |

调用方若依赖 130，请改为判断信号而非退出码。

## 4. 清理清单（迁移后）

- 新仓库 `git ls-files` 中不得出现：`.venv/`、`vendor/`、`models/`、`nltk_data/`、`outputs/`、`*.pth`、`*.so`、`*.wav`（`tests/fixtures` 除外）。
- 旧 skill 目录保留原地，但不要再作为依赖安装源。
- 旧的 `references/index_tts.json` 里如有 token，迁移完成后清空并轮换。
