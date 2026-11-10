"""共享工具：时间契约、退出码、脱敏、JSON/文件原子写。

时间契约（全仓库唯一口径，与 ark-node / asset-tools / device-io 一致）
---------------------------------------------------------------------
* 对外展示：北京时间，**无时区后缀**，``YYYY-MM-DD HH:MM:SS``
* 机器可读：RFC3339，``YYYY-MM-DDTHH:MM:SS+0800``
* 文件名：``YYYYMMDD-HHMMSS``

脱敏铁律
--------
本仓库只出现凭据**变量名**，永远不出现值。任何要写进日志、JSON、异常信息的
自由文本都必须先过 :func:`redact`。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional

# --------------------------------------------------------------------- 时间

BEIJING = timezone(timedelta(hours=8))

FMT_DISPLAY = "%Y-%m-%d %H:%M:%S"
FMT_RFC3339 = "%Y-%m-%dT%H:%M:%S%z"
FMT_STAMP = "%Y%m%d-%H%M%S"

# --------------------------------------------------------------------- 退出码

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_FAIL = 2
EXIT_UNSUPPORTED = 3
EXIT_BACKEND = 4

EXIT_CODES = {
    0: "OK",
    1: "USAGE",
    2: "FAIL",
    3: "UNSUPPORTED",
    4: "BACKEND",
}

MIB = 1024 * 1024


def now_beijing() -> datetime:
    """当前时间，固定按北京时间换算，不依赖节点本地时区。"""
    return datetime.now(timezone.utc).astimezone(BEIJING)


def _coerce(value: Optional[datetime]) -> datetime:
    if value is None:
        return now_beijing()
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING)
    return value.astimezone(BEIJING)


def format_display(dt: Optional[datetime] = None) -> str:
    """对外展示格式：``YYYY-MM-DD HH:MM:SS``（北京时间，无后缀）。"""
    return _coerce(dt).strftime(FMT_DISPLAY)


def format_rfc3339(dt: Optional[datetime] = None) -> str:
    """机器可读格式：``YYYY-MM-DDTHH:MM:SS+0800``。"""
    return _coerce(dt).strftime(FMT_RFC3339)


def format_stamp(dt: Optional[datetime] = None) -> str:
    """文件名时间戳：``YYYYMMDD-HHMMSS``。"""
    return _coerce(dt).strftime(FMT_STAMP)


def parse_time(text: str) -> datetime:
    """解析时间，接受展示格式与 RFC3339，返回带时区的 datetime。"""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("空时间字符串")
    try:
        return datetime.strptime(raw, FMT_DISPLAY).replace(tzinfo=BEIJING)
    except ValueError:
        pass
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+0000"
    try:
        return datetime.strptime(candidate, FMT_RFC3339).astimezone(BEIJING)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise ValueError("无法解析时间: {0!r}".format(raw))
    return _coerce(parsed)


# --------------------------------------------------------------------- 脱敏

#: 与 config/env-keys.json 保持一致的凭据变量名（只登记名字）。
SECRET_ENV_NAMES: List[str] = [
    "GITHUB_TOKEN",
    "ACCESS_KEY_ID",
    "ACCESS_KEY_SECRET",
    "LSTTS_TTS_TOKEN",
    "LSTEST_TTS_TOKEN",
    "TTS_RUNTIME_LSTTS_TOKEN",
    "LSTEST_TTS_URL",
    "TTS_RUNTIME_LSTTS_URL",
    "EMAIL_PASSWORD",
    "NAS_PASSWORD",
    "STORAGE_PASSWORD",
    "ARK_OSS_ACCESS_KEY_SECRET",
    "ARK_STORAGE_SSH_PASS",
]

_MIN_SECRET_LEN = 6


def redact(text: Any) -> str:
    """把已知凭据环境变量的**值**替换为 ``***``。

    值缺失或长度小于 6 时跳过（太短容易误伤正常文本）。结果永远是可以安全
    写进日志/ JSON / 异常信息的字符串。
    """
    result = "" if text is None else str(text)
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if not value or len(value) < _MIN_SECRET_LEN:
            continue
        result = result.replace(value, "***")
    # 兜底：形似 Bearer 令牌的片段
    result = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}", r"\1***", result)
    return result


# --------------------------------------------------------------------- 文件 / JSON


def ensure_dir(path: Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def json_dumps(payload: Any, indent: Optional[int] = 2) -> str:
    """稳定 JSON 文本：中文不转义，保持插入顺序。"""
    return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=False)


def write_json_atomic(path: Path, payload: Any, indent: Optional[int] = 2) -> Path:
    """原子写 JSON：先写同目录临时文件，再 ``os.replace``。"""
    target = Path(path)
    ensure_dir(target.parent if str(target.parent) else Path("."))
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent or "."), prefix=target.name + ".", suffix=".tmp", delete=False
    )
    try:
        with handle as stream:
            stream.write(json_dumps(payload, indent=indent))
            stream.write("\n")
        os.replace(handle.name, str(target))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return target


def read_text(path: Path) -> str:
    """读文本，兼容 utf-8-sig / gb18030 / utf-16（与 lstts 一致）。"""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def human_bytes(count: float) -> str:
    value = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            if unit == "B":
                return "{0:.0f}{1}".format(value, unit)
            return "{0:.1f}{1}".format(value, unit)
        value /= 1024.0
    return "{0:.1f}TB".format(value)


def tail_lines(text: str, count: int = 20, limit: int = 4000) -> List[str]:
    """取文本末尾若干行并截断长度，用于错误信息（调用方仍需 redact）。"""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return [line[:400] for line in lines[-count:]] if count > 0 else []


def split_env_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item for item in re.split(r"[,\s;]+", value) if item]


def first_env(names: Iterable[str]) -> Optional[str]:
    """按顺序取第一个非空环境变量值（**不要打印返回值**）。"""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def env_present(names: Iterable[str]) -> List[str]:
    """返回已设置的非空变量**名**列表（绝不返回值）。"""
    return [name for name in names if (os.environ.get(name) or "").strip()]
