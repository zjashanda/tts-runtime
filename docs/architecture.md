# 架构

## 一句话

`core` 负责所有一致性（参数校验、选引擎、输出命名、事件、批量、结果落盘），`engines/*` 只负责「怎么合成」。

```
CLI / Python API
      │
      ▼
   core.py ──────────────┬── config.py（白名单配置，拒绝凭据键）
      │                  ├── events.py（JSONL 事件）
      │                  ├── audio.py（WAV 解析与体检）
      │                  └── util.py（时间/编码/redact/原子写）
      ▼
 engines/__init__.py（注册表 + auto 选择）
      │
      ├── lstts.py    云端 IndexTTS：urllib + multipart + ZIP 校验
      ├── melotts.py  本地 MeloTTS：subprocess 委托 MELOTTS_HOME
      └── mock.py     离线确定性正弦波
```

## 分层理由

1. **引擎薄、编排厚。** 输出命名、退出码、事件序列、批量并发如果散落在三个引擎里，必然漂移。全部上移到 `core`，引擎只实现 `synthesize(request) -> Result`。
2. **依赖为零。** 运行时只用标准库（`urllib`、`zipfile`、`wave`、`multiprocessing` 之外的 `subprocess`）。旧 `lstts` 需要 `oss2`/`openpyxl`/`xlrd`，那是「选音色/出报表」的职责，不属于合成。
3. **本地引擎进程隔离。** MeloTTS 需要 torch、numpy、nltk、模型权重。把这些装进本包会重演旧 skill 的 435MB 污染。改为子进程调用外部安装，`MELOTTS_HOME` 指向它；本包只负责参数、超时、产物回收和格式校验。
4. **auto 永不回落 mock。** 静默用假音频「成功」是最危险的失败模式：上层会把它当成真语音发布。缺引擎就退出 3，让调用方决定。

## 关键流程

### 单条 synth

1. `core.synthesize` 校验文本非空 → `select_engine`（不可用即抛 `EngineUnavailable`）。
2. `resolve_output`：`--out`/`--out-dir` 互斥，目录缺省命名 `tts-<stamp>-<engine>.wav`。
3. 发 `start` 事件 → 引擎合成 → 发 `item_result` → CLI 发 `complete`。
4. 引擎返回 `Result`（含 `audio` 元数据、`notes`、`error`）。参数问题抛异常（USAGE），合成问题返回 `ok=false`（FAIL/BACKEND）。

### 批量 batch

1. `load_job` 校验 schema、items 非空、id 唯一、`text`/`text_file` 二选一，相对路径按 job 目录解析并读入文本。
2. `synthesize_batch` 选定引擎一次（不逐条重选），`ThreadPoolExecutor`（上限 8）跑 `{index:03d}-{id}.wav`。
3. 无论成败都写 `batch-result.json`；有失败项退出 2。

### 音频体检

`inspect_audio` 手写 RIFF 解析（PCM 与 EXTENSIBLE，8/16/24/32 bit），计算 `peak_dbfs`、`mean_db`、`clip_ratio`。判定：不可读、过短（<0.05s）、静音（mean ≤ -60dB）、削波（peak > 0dBFS 或满量程样本 >2%）、过长（>90s）。

## 时间与编码

- 时间统一北京时间、无时区后缀：`YYYY-MM-DDThh:mm:ss.sss`。
- 文本读取自动识别 `utf-8-sig` → `gb18030` → `utf-16`。
- JSON 输出 UTF-8、缩进 2、不转义中文；写文件用临时文件 + `os.replace` 原子替换。

## 明确不做

- 不做文本切分/长文分段（上层按需切分后入 items）。
- 不做 OSS 云音色库检索与 Excel 报表。
- 不做 GUI、不做服务端常驻进程；这是一次性 CLI/库。
