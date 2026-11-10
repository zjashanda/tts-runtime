# 回滚

## 原则

本运行时是**只读调用方 + 独立产物**：不改云端服务、不改旧仓库、不碰 main。回滚的最小单位是「换回旧入口」或「固定到上一个 tag」。

## 1. 代码回滚

```bash
git -C tts-runtime log --oneline            # 找到上一个稳定提交
git -C tts-runtime checkout <sha>           # 仅检视
# 生产用法：部署侧 pin 到 tag / sha，不回退仓库历史
git -C tts-runtime tag v0.1.0
```

如需撤销某次发布：

```bash
# 仅当该提交尚未被下游 pin 时
git revert <sha> && git push origin main
```

**不要** force-push、不要删除旧 tag。已发布 tag 视为不可变。

## 2. 调用方回滚

旧入口仍在（`lstts` / `melotts` 仓库未删除、未改 main）。切换方式：

| 目标 | 动作 |
|---|---|
| 回旧 lstts | 把调用命令改回 `python scripts/synthesize.py --job ...`；环境变量 `LSTTS_TTS_TOKEN` 等无需改动（新运行时兼容旧名） |
| 回旧 melotts | `./tts --language ZH ...`；`MELOTTS_HOME` 指向的目录未被动过 |
| 回 mock | `--engine mock`（仅用于排障，不要用于生产发布） |

## 3. 环境变量回滚

新运行时只读、不写环境变量，因此回滚不需要恢复任何被改写的值。若已在节点上把 `LSTEST_*` 改名为 `TTS_RUNTIME_*`，回滚到旧脚本时旧名仍需存在：

```bash
# 临时恢复旧名（仅进程级，不落盘）
export LSTEST_TTS_URL="$TTS_RUNTIME_LSTTS_URL"
export LSTEST_TTS_TOKEN="$TTS_RUNTIME_LSTTS_TOKEN"
```

长期方案是保留两组变量直到旧入口下线；不要把一个凭据写进多个文件。

## 4. 产物回滚

批量产物在 `--out-dir` 下（`{index:03d}-{id}.wav` + `batch-result.json`）。回滚 = 删除该目录，不影响源文本与仓库。

## 5. 发布事故处置顺序

1. **停**：把下游切回旧入口或 `--engine auto` 指定已知可用引擎。
2. **隔离**：若怀疑凭据泄漏，先轮换 token（云端侧），再改节点环境变量；仓库历史不动。
3. **取证**：`git ls-files`、`git log -p`、`secret_scan --json` 确认是否入库。
4. **修复**：在新提交里修，不 amend 已推送的历史。
5. **复核**：`sh tests/run-all.sh` 全绿 + 未鉴权 API 确认仓库仍为 public（若本意是 public）。

## 6. 不能回滚的操作

- 旧仓库删除（本任务明确不删）。
- GitHub 仓库改名/转移（会影响下游 remote）。
- 已轮换的 token 恢复旧值（应重新签发，不要复用）。
