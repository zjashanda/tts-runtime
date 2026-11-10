# 引擎

## lstts（云端 IndexTTS）

### 配置解析

| 项 | 顺序 |
|---|---|
| URL | `TTS_RUNTIME_LSTTS_URL` → `LSTTS_TTS_URL` → `LSTEST_TTS_URL` |
| token | `TTS_RUNTIME_LSTTS_TOKEN` → `LSTTS_TTS_TOKEN` → `LSTEST_TTS_TOKEN` |
| 超时 | `TTS_RUNTIME_TIMEOUT` → `LSTEST_TTS_TIMEOUT` → 默认 30s |
| 音色目录 | `TTS_RUNTIME_VOICE_DIR` → `LSTEST_VOICE_DIR` → `~/.config/ark/voices` |

两项缺任一 → `UNSUPPORTED`（退出 3），`missing_env` 只列变量名。

### 音色解析

1. 若 `voice` 是存在的文件（`.wav/.mp3/.flac/.m4a/.ogg`）→ 直接用。
2. 在音色目录下找 `<voice>.wav` 或同名文件。
3. 都找不到 → `UNSUPPORTED`「找不到音色」。

未指定 `voice` 时使用云端默认音色（不传 `spk_audio_prompt` 以外的假设由服务端决定）。

### HTTP

- 无情感：`POST {base_url}/v1/clone`
- 有情感：`POST {base_url}/v1/emotion`
- 头：`Authorization: Bearer <token>`、`Content-Type: multipart/form-data; boundary=...`、`Accept: application/zip`、`User-Agent: tts-runtime/0.1.0`
- 表单：`spk_audio_prompt`（音色文件）、`text`（文本文件）；情感时加 `emo_audio_prompt`。
- 要求：HTTP 200 且 `Content-Type` 含 `application/zip`。

### 响应校验（全部失败 → BACKEND，退出 4）

- 不是合法 zip。
- ZIP 内 `.wav` 数量不等于 1。
- 条目名为绝对路径、含 `..`、含 `:`、加密标志置位、符号链接。
- 解压后体积 > 200MB。

### 音频体检

写出后调用 `audio.evaluate`：不可读/过短/静音为 fatal（`validate=true` 时判失败，退出 2）；削波、过长只进 `notes`。`validate=false` 时只记录不判失败，`notes` 会写明。

### 限制

- 不支持 `speed`：传了 → USAGE（退出 1）。云端接口没有该参数，静默忽略会误导。
- 不做长文本切分：单次请求文本由调用方控制。

## melotts（本地 MeloTTS）

### 前置

```
$MELOTTS_HOME/scripts/synth.py
$MELOTTS_HOME/.venv/bin/python        # Windows: .venv/Scripts/python.exe
$MELOTTS_HOME/models/<LANG>/config.json
$MELOTTS_HOME/models/<LANG>/checkpoint.pth
```

`MELOTTS_PYTHON` 可覆盖解释器。缺任一项 → `UNSUPPORTED`，`reason` 列出缺什么。

### 调用

```
<python> scripts/synth.py --language ZH --speaker ZH --text <tmp.txt> --out-dir <tmpdir> [--speed S]
```

- `cwd=$MELOTTS_HOME`（脚本用相对路径找 `vendor/`、`models/`、`nltk_data/`）。
- 子进程环境只继承必要变量：`PATH/HOME/USERPROFILE/SYSTEMROOT/TEMP/TMP/TMPDIR/LANG/LC_ALL`，加 `NLTK_DATA`、`TOKENIZERS_PARALLELISM=false`、`PYTHONIOENCODING=utf-8`。**不把云端 token 泄漏给本地子进程。**
- 超时缺省 900s（首次加载模型很慢）。
- 取 `out-dir` 下第一个 `*.wav`；无论成败 `finally` 删除临时目录。
- 默认音色：`ZH` → `ZH`，`EN` → `EN-Default`。
- 语言只支持 `ZH`/`EN`；其它 → `UNSUPPORTED`。
- 不支持 `emotion`：传了 → USAGE。

### 产物

MeloTTS 约定 16000Hz / mono / 16-bit PCM。不符只加 `notes`，不判失败（仍可播放）；需要严格格式时由调用方 `inspect` 判定。

### 进程隔离的理由

torch + numpy + nltk + 模型权重数百 MB。放进本包就会重演旧 skill 的污染。子进程委托让本仓库保持零依赖、可公开。

## mock（离线）

- 音色：`tone-440`、`tone-880`。
- 时长：`max(0.3, min(6.0, len(text) * 0.06))` 秒。
- 16000Hz / mono / 16-bit PCM 正弦波，相位连续、无削波。
- 用途：CI、契约测试、演示。**auto 永远不会选它。**

## auto 选择

```
TTS_RUNTIME_ENGINE（非 auto/空）→ 用它
否则 lstts.available → lstts
否则 melotts.available → melotts
否则 UNSUPPORTED（消息列出各引擎不可用原因）
```

强制指定不可用引擎 → 直接 `UNSUPPORTED`，不改用别的引擎。
