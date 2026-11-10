"""JSONL 事件流（与 lstts 的事件名对齐，便于旧调用方迁移）。

事件：``start`` → ``progress``* → ``item_result``* → ``complete``。
每条都是单行 JSON，时间用北京时间展示格式，写入时保证 UTF-8 不转义中文。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import util

EVENT_START = "start"
EVENT_PROGRESS = "progress"
EVENT_ITEM = "item_result"
EVENT_COMPLETE = "complete"

Callback = Callable[[str, Dict[str, Any]], None]


class EventSink:
    """事件汇聚：同时支持回调与 JSONL 文件，线程安全。"""

    def __init__(self, path: Optional[Path] = None, callback: Optional[Callback] = None):
        self.path = Path(path) if path else None
        self.callback = callback
        self._lock = threading.Lock()
        if self.path is not None:
            util.ensure_dir(self.path.parent if str(self.path.parent) else Path("."))
            with open(str(self.path), "w", encoding="utf-8"):
                pass

    def emit(self, event: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record: Dict[str, Any] = {"event": event, "at": util.format_display()}
        if payload:
            record.update(payload)
        line = util.json_dumps(record, indent=None)
        with self._lock:
            if self.path is not None:
                with open(str(self.path), "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            if self.callback is not None:
                try:
                    self.callback(event, record)
                except Exception:  # 回调失败不能影响合成主流程
                    pass
        return record

    def start(self, **payload: Any) -> Dict[str, Any]:
        return self.emit(EVENT_START, payload)

    def progress(self, **payload: Any) -> Dict[str, Any]:
        return self.emit(EVENT_PROGRESS, payload)

    def item(self, **payload: Any) -> Dict[str, Any]:
        return self.emit(EVENT_ITEM, payload)

    def complete(self, **payload: Any) -> Dict[str, Any]:
        return self.emit(EVENT_COMPLETE, payload)


def null_sink() -> EventSink:
    return EventSink()
