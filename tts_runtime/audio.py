"""WAV 解析与校验（仅标准库）。

支持：
* ``WAVE_FORMAT_PCM`` (1) —— 8/16/24/32 bit
* ``WAVE_FORMAT_EXTENSIBLE`` (0xFFFE) —— 取子格式 GUID 前两字节判定 PCM

不支持（视为 FATAL）：float PCM、ADPCM、mp3/aac 伪装成 .wav。

``inspect_audio`` 返回的 ``peak_dbfs``/``mean_db`` 与 lstts 的 ``legacy.inspect_audio``
口径一致：以满量程为 0 dBFS，静音切片取 ``-120.0`` 作为下限。
"""

from __future__ import annotations

import struct
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import util
from .models import AudioInfo

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

FLAG_SILENT = "silent"
FLAG_CLIPPED = "clipped"
FLAG_TOO_LONG = "too_long"
FLAG_TOO_SHORT = "too_short"
FLAG_UNREADABLE = "unreadable"

SILENCE_MEAN_DB = -60.0
MIN_DURATION_S = 0.05
CLIP_PEAK_DBFS = 0.0
CLIP_RATIO = 0.02
TOO_LONG_S = 90.0
DB_FLOOR = -120.0


def _read_chunks(handle: Any) -> Tuple[int, Dict[str, Any]]:
    """遍历 RIFF 块，返回 ``(fmt_dict, data_bytes)``。"""
    header = handle.read(12)
    if len(header) < 12 or header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("不是 RIFF/WAVE 文件")

    fmt: Optional[Dict[str, Any]] = None
    data: Optional[bytes] = None
    while True:
        chunk_header = handle.read(8)
        if len(chunk_header) < 8:
            break
        chunk_id = chunk_header[0:4]
        (size,) = struct.unpack("<I", chunk_header[4:8])
        if chunk_id == b"fmt ":
            payload = handle.read(size)
            if len(payload) < 16:
                raise ValueError("fmt 块过短")
            (
                format_tag,
                channels,
                sample_rate,
                _byte_rate,
                block_align,
                bits_per_sample,
            ) = struct.unpack("<HHIIHH", payload[:16])
            if format_tag == WAVE_FORMAT_EXTENSIBLE:
                if len(payload) < 40:
                    raise ValueError("WAVE_FORMAT_EXTENSIBLE fmt 块过短")
                (sub_format,) = struct.unpack("<H", payload[24:26])
                format_tag = sub_format
            fmt = {
                "format_tag": format_tag,
                "channels": channels,
                "sample_rate": sample_rate,
                "block_align": block_align,
                "bits_per_sample": bits_per_sample,
            }
        elif chunk_id == b"data":
            data = handle.read(size)
            if size % 2 == 1:  # RIFF 规定奇数块需要 1 字节填充
                handle.read(1)
        else:
            handle.seek(size + (size % 2), 1)

    if fmt is None:
        raise ValueError("缺少 fmt 块")
    if data is None:
        raise ValueError("缺少 data 块")
    return fmt["format_tag"], {"fmt": fmt, "data": data}


def _decode_samples(raw: bytes, bits: int) -> Tuple[array, float]:
    """返回 ``(归一化到 [-1, 1] 的样本, 满量程)``。"""
    if bits == 8:
        samples = array("h", ((byte - 128) << 8 for byte in raw))
        return samples, 32768.0
    if bits == 16:
        usable = len(raw) - (len(raw) % 2)
        samples = array("h")
        samples.frombytes(raw[:usable])
        return samples, 32768.0
    if bits == 24:
        usable = len(raw) - (len(raw) % 3)
        samples = array("i")
        for index in range(0, usable, 3):
            value = raw[index] | (raw[index + 1] << 8) | (raw[index + 2] << 16)
            if value & 0x800000:
                value -= 1 << 24
            samples.append(value)
        return samples, 8388608.0
    if bits == 32:
        usable = len(raw) - (len(raw) % 4)
        samples = array("i")
        samples.frombytes(raw[:usable])
        return samples, 2147483648.0
    raise ValueError("不支持的位深: {0}".format(bits))


def _dbfs(amplitude: float, full_scale: float) -> float:
    if amplitude <= 0:
        return DB_FLOOR
    import math

    value = 20.0 * math.log10(min(1.0, amplitude / full_scale))
    return round(max(DB_FLOOR, value), 2)


def inspect_audio(path: Path) -> AudioInfo:
    """解析 WAV 头与采样，返回 :class:`AudioInfo`。解析失败抛 :class:`ValueError`。"""
    target = Path(path)
    if not target.is_file():
        raise ValueError("文件不存在: {0}".format(target))
    with open(str(target), "rb") as handle:
        format_tag, payload = _read_chunks(handle)

    fmt = payload["fmt"]
    data = payload["data"]
    if format_tag != WAVE_FORMAT_PCM:
        raise ValueError("非 PCM WAV（format=0x{0:04x}）".format(format_tag))
    bits = int(fmt["bits_per_sample"])
    channels = int(fmt["channels"]) or 1
    sample_rate = int(fmt["sample_rate"])
    if sample_rate <= 0:
        raise ValueError("采样率非法: {0}".format(sample_rate))

    samples, full_scale = _decode_samples(data, bits)
    frame_count = len(samples) // channels if channels else 0
    duration = round(frame_count / float(sample_rate), 3) if sample_rate else 0.0

    peak = 0
    total = 0.0
    clipped = 0
    limit = (1 << (bits - 1)) - 1
    for value in samples:
        magnitude = abs(value)
        if magnitude > peak:
            peak = magnitude
        total += abs(value)
        if magnitude >= limit:
            clipped += 1
    mean_abs = (total / len(samples)) if samples else 0.0

    info = AudioInfo(
        container="wav",
        codec="pcm_s{0}le".format(bits),
        sample_rate=sample_rate,
        channels=channels,
        sample_width=bits // 8,
        frames=frame_count,
        duration_seconds=duration,
        peak_dbfs=_dbfs(float(peak), full_scale),
        mean_db=_dbfs(mean_abs, full_scale),
        clip_ratio=round(clipped / float(len(samples)), 4) if samples else 0.0,
    )
    return info


def evaluate(path: Path) -> Tuple[Optional[AudioInfo], List[str], List[str]]:
    """返回 ``(音频信息, fatal 列表, notes 列表)``，永不抛异常。"""
    try:
        info = inspect_audio(path)
    except (ValueError, OSError, struct.error) as exc:
        return None, [FLAG_UNREADABLE + ": " + util.redact(str(exc))], []

    fatal: List[str] = []
    notes: List[str] = []
    if info.duration_seconds < MIN_DURATION_S:
        fatal.append(FLAG_TOO_SHORT + ": 时长 {0}s < {1}s".format(info.duration_seconds, MIN_DURATION_S))
    if info.mean_db <= SILENCE_MEAN_DB:
        fatal.append(FLAG_SILENT + ": 平均电平 {0} dBFS".format(info.mean_db))
    if info.peak_dbfs > CLIP_PEAK_DBFS or info.clip_ratio > CLIP_RATIO:
        notes.append(
            FLAG_CLIPPED
            + ": 峰值 {0} dBFS, 满幅样本占比 {1:.1%}".format(info.peak_dbfs, info.clip_ratio)
        )
    if info.duration_seconds > TOO_LONG_S:
        notes.append(FLAG_TOO_LONG + ": 时长 {0}s > {1}s".format(info.duration_seconds, TOO_LONG_S))
    return info, fatal, notes


def write_tone(path: Path, *, seconds: float = 0.6, frequency: float = 440.0,
               sample_rate: int = 16000, amplitude: float = 0.3) -> AudioInfo:
    """写一个确定性的 16-bit PCM 单声道正弦波，供 mock 引擎与测试使用。"""
    import math
    import wave

    target = Path(path)
    util.ensure_dir(target.parent if str(target.parent) else Path("."))
    total = max(1, int(round(max(0.005, seconds) * sample_rate)))
    peak = int(max(0.0, min(1.0, amplitude)) * 32767)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        buffer = bytearray()
        for index in range(total):
            sample = int(peak * math.sin(2.0 * math.pi * frequency * index / sample_rate))
            buffer.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(buffer))
    return inspect_audio(target)
