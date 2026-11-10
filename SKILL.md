---
name: tts-runtime
description: 统一 TTS 合成入口（lstts 云端 IndexTTS / melotts 本地 MeloTTS / mock 离线自检）。当需要把文本合成 wav、批量合成、体检音频，或判断本机有哪些 TTS 引擎可用时使用。URL 与 token 只从环境变量读取。
---

# tts-runtime skill

本 skill 只描述**怎么调用**；实现与契约在仓库里（`SPEC` 已内化为 `docs/`）。

## 何时用

- 要把一段文本合成语音（云端音色克隆 / 情感参考，或本地离线合成）。
- 要批量把多行文本合成到目录，并拿到结构化结果。
- 要判断当前机器能不能合成、缺哪些环境变量。
- 要检查一个 wav 是否可播、是否静音/过短/削波。

## 三条命令

```bash
tts-runtime doctor                 # 环境自检：引擎可用性 + 缺失变量名（不打印值）
tts-runtime synth --text "..." --out a.wav [--engine lstts|melotts|mock|auto]
tts-runtime batch --job job.json --out-dir out/ [--workers 4]
```

辅助：

```bash
tts-runtime engines [--json]                      # 引擎与原因
tts-runtime voices [--engine X] [--json]          # 音色清单
tts-runtime inspect a.wav [--json]                # 音频体检
```

## 选择引擎

| 场景 | 引擎 | 前置 |
|---|---|---|
| 生产、音色克隆、情感 | `lstts` | `TTS_RUNTIME_LSTTS_URL` + `TTS_RUNTIME_LSTTS_TOKEN` |
| 内网/离线、中英文 | `melotts` | `MELOTTS_HOME` 指向已装好的 MeloTTS |
| CI、契约测试、演示 | `mock` | 无 |

不确定时用 `--engine auto`（缺省）：先 `lstts` 再 `melotts`，都没有就退出 3。**auto 不会回落 mock。**

## 环境变量（只读不写）

```
TTS_RUNTIME_LSTTS_URL / TTS_RUNTIME_LSTTS_TOKEN
TTS_RUNTIME_VOICE_DIR / TTS_RUNTIME_TIMEOUT
MELOTTS_HOME / MELOTTS_PYTHON
TTS_RUNTIME_ENGINE / TTS_RUNTIME_LANGUAGE / TTS_RUNTIME_CONFIG / TTS_RUNTIME_WORK
```

兼容旧名：`LSTTS_TTS_URL`、`LSTTS_TTS_TOKEN`、`LSTEST_TTS_URL`、`LSTEST_TTS_TOKEN`、`LSTEST_TTS_TIMEOUT`、`LSTEST_VOICE_DIR`。

**禁止**把 URL/token 写进配置、job、命令行参数或日志。配置文件里出现 `token`/`url`/`endpoint`/`secret` 等键会被拒绝（退出码 1）。

## 退出码

0 成功 / 1 用法或契约错误 / 2 业务失败 / 3 平台不支持 / 4 后端不可用。

## 结构化输出

任何命令加 `--json` 输出契约 JSON；`synth --events events.jsonl` 输出 JSONL 事件流（`start` → `item_result` → `complete`）。时间戳是北京时间、无时区后缀。

## 注意

- 这是公开仓库：不要把音色样本、模型权重、`.venv`、生成音频提交进来。
- 本地引擎是**子进程委托**，本包不需要 torch；torch 与模型只存在于 `MELOTTS_HOME` 指向的外部安装。
- 云端响应 ZIP 会被做路径穿越/符号链接/加密/体积校验，不要绕过。
