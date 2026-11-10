# 运维手册

## 日常检查

```bash
tts-runtime doctor                 # 人读：work_dir 可写 + 引擎可用性
tts-runtime doctor --json          # 机读：ark.tts-doctor.v1
tts-runtime engines --json         # 只要引擎状态
```

`doctor` 退出 0 表示**至少一个**引擎可用；全部不可用退出 3。注意 mock 永远可用，所以退出 3 只在极端情况下出现——判断生产可用性要看 `lstts`/`melotts` 的 `available`，不要只看退出码。

## 冒烟（部署后 30 秒）

```bash
tts-runtime synth --engine mock --text "smoke" --out /tmp/smoke.wav
tts-runtime inspect /tmp/smoke.wav            # 期望 OK，16000Hz/1ch
```

云端冒烟（不产生费用可控文本）：

```bash
tts-runtime synth --engine lstts --text "冒烟测试" --out /tmp/cloud.wav
```

## 批量

```bash
tts-runtime batch --job job.json --out-dir /srv/out/run-20261110 --workers 4 --json
```

- `workers` 上限 8；本地 melotts 建议不超过 CPU 核数的一半（首次加载模型吃内存）。
- 产物：`{index:03d}-{id}.wav`、`batch-result.json`。
- 退出 2 时先看 `batch-result.json` 里失败项的 `error.code`：

| code | 处理 |
|---|---|
| `USAGE` | job 本身有问题（id 重复、text 与 text_file 同时给） |
| `FAIL` | 合成失败或音频体检 fatal：看 `error.message` 与 `notes` |
| `UNSUPPORTED` | 该条语言/音色不支持，或引擎中途不可用 |
| `BACKEND` | 云端 5xx/超时/坏 zip：重试该条，检查服务端 |

## 常见故障

| 现象 | 退出码 | 排查 |
|---|---|---|
| `lstts 不可用` | 3 | `doctor --json` 看 `missing_env`；确认 `TTS_RUNTIME_LSTTS_URL`/`TOKEN` 已在**当前进程**环境（改完要重开进程） |
| `melotts 不可用` | 3 | `MELOTTS_HOME` 是否存在 `scripts/synth.py`、`.venv/bin/python`、`models/ZH/checkpoint.pth` |
| `HTTP 401` | 4 | token 过期或前缀错误；只换环境变量，不要写进配置 |
| `响应类型不是 application/zip` | 4 | URL 指错（指到了网页/JSON 接口） |
| `响应 zip 内 wav 数量必须是 1` | 4 | 服务端返回格式变了，或 base_url 指向别的服务 |
| `响应 zip 含非法路径` | 4 | 服务端返回可疑 zip；停止重试并上报 |
| `音频过短/静音` | 2 | 文本可能为空或音色文件损坏；`inspect` 看 `notes` |
| `找不到音色` | 3 | `voice` 名不在 `TTS_RUNTIME_VOICE_DIR`，也不是存在的文件 |
| 配置报 `USAGE` | 1 | 配置文件里出现了 url/token/secret 等键——**这是保护，不是 bug** |
| 本地合成超时 | 4 | 首次加载模型慢；提高 `TTS_RUNTIME_TIMEOUT` 或改用 `--timeout` |

## 日志与事件

```bash
tts-runtime batch --job job.json --out-dir out/ --events out/events.jsonl
```

事件顺序：`start` → 每条 `item_result` → `complete`。每行含 `at`（北京时间无时区）、`engine`、`ok` 等。不要把事件流当审计日志长期保存到公开位置（可能含文本长度与路径）。

## 变更流程

1. 改代码 → `sh tests/run-all.sh` 必须全绿。
2. `python3 tools/secret_scan.py --gate` 0 命中。
3. `git ls-files` 复核无 `.venv`/`vendor`/`models`/`*.pth`/`*.wav`（fixture 除外）。
4. 单一目的提交；打 tag；再部署。
5. 节点侧改环境变量后**重开进程**（环境变量是启动时快照）。

## 容量

- 本仓库应 < 2MB（不含 `.git`）。超过说明有生成资产混入，立即检查 `git ls-files`。
- 单个 wav 典型 10–500KB；批量产物放独立目录，不要放进仓库工作区。
