# 安全

## 威胁模型

| 资产 | 风险 | 处置 |
|---|---|---|
| 云端 token | 进入 git / 日志 / 评论 | 只从环境变量读；`redact()`；secret_scan 门禁 |
| 云端 URL | 暴露内网地址 | 同上；配置文件出现 `url`/`endpoint` 键直接拒绝 |
| 音色样本 | 个人生物特征外泄 | 不入库；只从 `TTS_RUNTIME_VOICE_DIR` 或显式路径读 |
| 模型权重 | 仓库体积与许可 | 不入库；`MELOTTS_HOME` 外部安装 |
| 云端响应 | zip slip / 解压炸弹 | 唯一 wav、路径/链接/加密/体积校验 |

## 凭据处理

1. **来源单一**：`TTS_RUNTIME_LSTTS_TOKEN`（或兼容旧名）只从进程环境读取。没有 CLI 参数、没有配置文件键、没有 job 字段可以传 token。
2. **不打印**：`util.redact()` 把所有 `SECRET_ENV_NAMES` 的值替换为 `***`（值长度 <6 时跳过，避免误伤）；兜底替换 `Bearer <...>`。异常消息在构造时即 redact。
3. **不落盘**：日志、`batch-result.json`、事件流都不写环境变量值；`doctor` 只输出 `missing_env` 变量名。
4. **不外泄给子进程**：melotts 子进程环境是白名单，不含任何 TTS token。

## 配置文件白名单

`sanitize()` 只接受：`schema`、`engine`、`language`、`speed`、`timeout_s`、`validate`、`voice`、`workers`、`work_dir`。

出现以下键（任意层级，大小写与下划线归一后）→ `USAGE`（退出 1）：

- 精确：`url`、`base_url`、`endpoint`、`uri`
- 包含：`token`、`secret`、`password`、`passwd`、`apikey`、`api_key`、`access_key`、`credential`

这条规则的意义：即使有人误把 `~/.config/ark/tts-runtime.json` 提交或分享，也不可能夹带凭据；一旦有人试图加，程序立刻失败而不是「悄悄可用」。

## ZIP 响应防护

- `Content-Type` 必须是 `application/zip`。
- 必须能打开为 zip。
- 恰好一个 `.wav`（0 个或多个都拒绝）。
- 成员名：拒绝绝对路径、`..`、盘符 `:`。
- 成员属性：拒绝加密标志、拒绝符号链接。
- 单文件与总量上限 200MB。

## 发布门禁

```bash
sh tests/run-all.sh
```

包含：全部 unittest、shell 语法检查、`secret_scan.py --self-test`、`secret_scan.py --gate`。

`tools/secret_scan.py` 规则：

- `ghp_`/`github_pat_` GitHub token
- 云厂商 AccessKey（`LTAI...` 等）
- PEM 私钥块
- 赋值型凭据：`password` / `secret` / `token` / `access_key` 后跟 8 位以上字面量
- 禁用文件名：`.git-credentials`、`id_rsa`、`id_ed25519`、`*.pem`、`*.pfx`、`auth.json`

允许清单在 `tools/scan-allowlist.txt`（只放行 `<env>` 占位与 `config/env-keys.json`）。行内放行注释 `ark-scan:allow` 需人工审查。

## 报告漏洞

不要开公开 issue 贴 token 或内部地址。直接联系仓库 owner（zjashanda），并附最小复现；凭据泄露按「先轮换、后修复」处理。
