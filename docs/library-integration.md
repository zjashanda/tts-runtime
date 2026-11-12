# TTS 音频库集成

- 适用版本：`tts-runtime` 0.1.1
- 更新时间：2026-11-12 17:06:15
- 关联：NOAH-66；规格 `tts-library-proposal.md` v1.0.0；`asset-tools` 的 `tts-library` 子命令契约

## 一句话

`tts-runtime` 是**唯一的合成入口**，但只在编排方判定 **cache miss** 之后被调用：把一份已经归一化的合成规格变成 wav，并返回 `ark.tts-result.v1`。缓存键、命中判断、1006 落库、复用、发布与删除全部属于 `asset-tools` 的 `tts-library`，本仓库一概不做。

## 定位

- 命令面只有三条主路径：`synth`（单条）、`batch`（批量）、`inspect`（音频体检）；`doctor`/`engines`/`voices` 只用于判断本机能力。
- 引擎只有 `lstts`（云端 IndexTTS）、`melotts`（本地 MeloTTS）、`mock`（离线自检）。
- 本仓库**不计算** cache key，**不读取** 1006 索引，**不判断**是否命中，**不写** `/srv/storage/ark/artifacts/audio/tts-library`，**不发布**、**不删除**、**不改写**任何库资产。
- 本仓库**不接收** `asset_id`、`cache_key` 或库内路径作为合成参数；它只认识文本、音色、语言、引擎、引擎参数和输出路径。
- URL 与 token 只从环境变量读取，不落配置、job、命令行或日志；本仓库不保存任何库侧凭据。

边界一句话：`asset-tools` 决定「要不要合成、合成结果算不算命中」，`tts-runtime` 只回答「按这份规格怎么合成」。

## 输入：归一化合成规格

编排方在调用前必须把规格归一化。`tts-runtime` 只消费下表中的字段；未列出的字段不会进入合成，也不会被本仓库补默认值。

| 规格字段 | 对应 CLI | 说明 |
|---|---|---|
| `text` | `--text` / `--text-file` | 二者互斥且必填；长文本建议用 `--text-file`，编码支持 utf-8-sig/gb18030/utf-16 |
| `engine` | `--engine` | `auto`/`lstts`/`melotts`/`mock`；生产应显式写 `lstts` 或 `melotts`，不要依赖 `auto` |
| `voice` | `--voice` | 音色名、音色 wav 路径或 melotts speaker id |
| `language` | `--language` | `ZH`/`EN`，仅 melotts 使用；lstts 侧不参与请求 |
| `params.emotion` | `--emotion` | 情感参考音频路径，**仅 lstts** 接受 |
| `params.speed` | `--speed` | 语速，**仅 melotts** 接受 |
| `params.timeout_s` | `--timeout` | 单次调用超时秒数 |
| `params.validate` | `--no-validate` | CLI 是反向开关；缺省 `validate=true`，体检 fatal 即判失败 |
| `output` | `--out` / `--out-dir` | 二者互斥且必填；`--out` 未带 `.wav` 时自动补后缀 |

`rate`、`pitch`、`style` **不是本仓库的 CLI 参数**：它们可以进入上游 cache key，但本仓库不会消费。若这些参数需要真实改变音频，必须由编排方在调用前完成对应处理，或换用支持该参数的引擎；不能传进来假装生效。

## 唯一调用顺序

```text
1) asset-tools tts-library lookup     # 用完整规格算键并查 1006 索引
2) 命中  → asset-tools tts-library fetch  # 复制到 <task>/assets/tts/original/<asset_id>/
3) 未命中 → tts-runtime synth            # 只在任务目录内合成
4) tts-runtime inspect                   # 质检产物
5) asset-tools tts-library publish       # 暂存 → 锁 → 原子发布 → query-back
```

顺序不可交换：`synth` 之前没有 `lookup`，就违反了「先查库、miss 才合成」；`synth` 之后没有 `inspect`，就不得进入 `publish`。

## 合成命令（真实参数）

单条 cache miss 的推荐调用：

```bash
TASK_DIR=/home/zhsh/workspace/tasks/NOAH-66
ASSET_ID=tts-0123456789abcdef

mkdir -p "${TASK_DIR}/assets/tts/staging"
tts-runtime synth \
  --text "今天天气不错" \
  --voice 付小春 \
  --engine lstts \
  --out "${TASK_DIR}/assets/tts/staging/${ASSET_ID}.wav" \
  --json
```

- `--out` 与 `--out-dir` 只能给一个；`--out` 的父目录必须已存在（`lstts`/`melotts` 会补建，`mock` 不保证），所以先 `mkdir -p` 是稳妥做法。
- 输出路径必须是**任务目录内的绝对路径**。本仓库不知道任务根，技术上无法阻止越界路径，因此「只写任务目录」是调用方必须遵守的边界，不是本仓库能替你兜底的限制。
- 不得把 `--out` 指向 1006 库根、库内资产目录或系统临时目录；staging 目录只是发布前暂存，发布动作属于 `asset-tools`。
- 需要事件流时加 `--events "${TASK_DIR}/logs/tts-events.jsonl"`，该文件同样只能落在任务目录。
- 提案 §5 的示例路径 `<task>/work/tts/` 与本文件的 `<task>/assets/tts/staging/` 都是任务目录内路径；按编排方约定二选一，禁止混用库根。

批量合成仍走真实参数，job 文件与输出目录都必须在任务目录内：

```bash
tts-runtime batch \
  --job "${TASK_DIR}/assets/tts/staging/batch.json" \
  --out-dir "${TASK_DIR}/assets/tts/staging/batch-out" \
  --engine lstts \
  --workers 4 \
  --json
```

合成完成后先体检，再交给发布：

```bash
tts-runtime inspect "${TASK_DIR}/assets/tts/staging/${ASSET_ID}.wav" --json
```

`inspect` 只读文件、输出体检 JSON，不修改音频，也不访问任何库路径。

## 输出契约 `ark.tts-result.v1`

成功时返回 `schema=ark.tts-result.v1`、`ok=true`、实际使用的 `engine`、`voice`、`language`、`audio_path`、`audio` 对象、`started_at`/`finished_at`、`elapsed_s` 与 `notes[]`。失败时 `ok=false`、`audio=null`，`error.code ∈ USAGE/FAIL/UNSUPPORTED/BACKEND`。

发布侧可从结果采集以下字段，它们只描述**这次合成实际发生了什么**，不是缓存键：

| 来源字段 | 含义 |
|---|---|
| `engine` | 实际使用的引擎（`lstts`/`melotts`/`mock`） |
| `voice` / `language` | 实际使用的音色与语言 |
| `audio.container` / `audio.codec` | 容器与编码（如 `wav` / `pcm_s16le`） |
| `audio.sample_rate` / `audio.channels` | 采样率与声道数 |
| `audio.sample_width` / `audio.frames` | 每个采样的字节数（16-bit = 2）与帧数 |
| `audio.duration_seconds` | 时长（秒） |
| `started_at` / `finished_at` | 北京时间 `YYYY-MM-DD HH:MM:SS`，无时区后缀 |
| `notes` | 非致命提示（格式不符、削波、`validate=false` 等） |

`audio.sha256` **不来自** `ark.tts-result.v1`：结果契约没有该字段。发布前由 `asset-tools`（或 `inspect` 之外的独立哈希步骤）对文件实测；`tts-runtime` 只保证写出的是可读 wav。

## 调用方必须显式补齐的规格

以下字段**无法**从 `ark.tts-result.v1` 推导，必须由调用方在 spec 中显式给出。缺任何一项都按「未命中」处理，禁止用默认值猜测：

- `model`
- `model_version`
- `rate`
- `pitch`
- `style`
- `emotion`
- `speed`（仅 melotts；lstts 必须为 `null`，传了会退出 1）
- `normalization_profile`

原因很直接：结果契约只有 `engine`/`voice`/`language` 与音频元数据；`model_version` 没有显式字段，`rate`/`pitch`/`style` 也不是本仓库的合成参数。用默认值补齐会让两个任务对同一段文本算出同一个键，却得到不同的声音——这正是缓存键必须完整、`tts-runtime` 不能替调用方补参数的原因。

## `lstts` 引擎的已知限制

以下事实来自 `docs/engines.md` 与 `tts_runtime/engines/` 的实现，不是推测：

- **不支持 `speed`**：传了直接 `USAGE`（退出 1）。云端接口没有该参数，静默忽略会误导调用方；需要变速时由 `audio-runtime` 在任务副本上做派生处理，或改走 melotts。
- **`emotion` 仅 `lstts` 支持**：`melotts` 传了 `emotion` 也是 `USAGE`（退出 1）。
- **模型版本无显式字段**：`ark.tts-result.v1` 只记录 `engine`，不记录 `model`/`model_version`。调用方必须在 spec 中人工填写；缺失时无法组成完整缓存键，该结果只能作为本地产物，不能登记为可复用资产。
- **不做长文本切分**：单次请求文本长度由调用方控制。
- **音色解析有回退顺序**：存在的音色文件 → `TTS_RUNTIME_VOICE_DIR` 下同名文件 → 找不到就 `UNSUPPORTED`（退出 3），不会改用别的音色。

`melotts` 的产物约定 16000Hz / mono / 16-bit PCM，不符只进 `notes`；需要严格格式时由调用方 `inspect` 判定，后续派生处理同样交给 `audio-runtime`。

## 退出码与处置

| 退出码 | 含义 | 编排方应做什么 | 不得做什么 |
|---|---|---|---|
| 0 | 合成成功 | 进入 `inspect`，再 `publish` | 不得跳过体检直接发布 |
| 1 | `USAGE`：参数、job 格式、配置含凭据键、空文本、lstts 传 speed、melotts 传 emotion | 修正规格后重试；这是确定性错误，重试同样的参数不会成功 | 不得把本次调用算作 cache miss 的「临时失败」去反复重试 |
| 2 | `FAIL`：合成失败或音频体检 fatal（不可读/过短/静音） | 保留失败证据；按上层策略终止该条任务，或换参数重新生成 | 不得发布失败产物；不得把静音/过短文件当正式资产 |
| 3 | `UNSUPPORTED`：引擎未配置/未安装、语言不支持、找不到音色 | 补齐环境变量或安装引擎后重试；也可以显式改走另一个可用引擎 | 不得偷偷回落到 `mock`；不得把「没有引擎」写成「库里没有」 |
| 4 | `BACKEND`：HTTP 非 200、超时、响应类型/zip/路径不合法 | 记录后端不可用；恢复后重试，或把发布请求写 outbox 由 `asset-tools` 重放 | 不得把后端故障当成合成成功；不得伪造结果 |

`auto` 只会在 `lstts` 与 `melotts` 之间选择，**永远不会回落到 `mock`**；强制指定不可用引擎会直接退出 3，不会改用别的引擎。

## 失败与降级

- 合成失败（`ok=false`，退出 1/2/3/4）：不发布，任务继续用本地结果或直接失败，由上层决定；本仓库不写 outbox。
- 质检失败（不可读/静音/过短）：默认不发布；只有带 `--allow-quality-candidate` 的 `publish` 才能降级为 `candidate` 并留证据，该开关属于 `asset-tools`。
- 发布失败（锁冲突、1006 不可达、query-back 不一致）：由 `asset-tools` 写 outbox（`pending`）；任务可以使用本地结果，但**不得声称公共库已更新**。
- 库里已有同键资产时，正确做法是 `fetch` 复用而不是重新合成；`tts-runtime` 不做这个判断，也无法拒绝一次本不该发生的 `synth`。

## 与派生处理的分工

本仓库只产出「一次合成的原始 wav」。任何**派生后处理**——重采样、裁剪、增益、降噪、响度归一化、转成播放格式——都属于 `audio-runtime`，必须在任务目录内的**副本**上完成，并记录 `derived_from_asset_id`、上游 `audio.sha256`、有序处理链与输出 sha256。本仓库不提供后处理命令，也不把派生结果写回 1006 库。

## 明确不做

- 不新增 `lstts` 命令、`lstts` skill 或独立入口：`lstts` 只是引擎名。
- 不改本仓 schema（`ark.tts-request.v1`/`ark.tts-result.v1`/`ark.tts-job.v1`/`ark.tts-voice.v1`）。
- 不存凭据、不代管 1006 上传凭据；`node-storage` 凭据仍由环境变量提供。
- 不做缓存键计算、命中判断、索引重建、GC 或配额。
- 不做库内资产的校验、修复、迁移或删除。

## 相关文档

- `asset-tools`：`docs/tts-library.md`（缓存键、`tts-library lookup/fetch/publish/verify/index`、ACL 与 outbox 的唯一权威）
- `ark-node`：Agent 模板「TTS 音频库优先」（先查库、miss 才合成的硬规则）
- `lstest`：测试域只消费任务副本，不回填公共库
- `audio-runtime`：`docs/tts-library-derived.md`（派生处理只作用于任务副本）
- 本仓：`docs/contracts.md`（结果契约）、`docs/engines.md`（引擎限制）、`docs/security.md`（凭据边界）
