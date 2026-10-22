# -*- coding: utf-8 -*-
"""battery_history.py —— 记录电量读到过的值，判断「这个数字到底可不可信」

为什么需要它
------------
VGN / VXE 这颗 2.4G 接收器的 0x1A 应答里只有「一个 0-100 的字节 + 一个状态字节」，
**没有电压、也没有采样时间**。而键盘固件在测不到电池时会走一条固定返回 100 的分支
（同方案 VGN X68 的固件被完整逆向过：ADC 采样全为 0 时，指示值直接 = 100），
接收器也可能一直缓存着键盘上次上报的值。

结果：工具照着协议读，读到的确实是 100，但那个 100 未必等于「现在的电量」。
所以这里不猜，只做两件事：

1. 把每次读到的 (时间, 电量, 状态) 落盘，能回答「这个值上次变化是什么时候」；
2. 当「恒为 100% + 没在充电 + 已经稳定很久」时标成存疑，界面如实说明，并给出核对办法。

判定故意保守：数值只要动过一次就恢复可信；存疑时也仍然显示数字，只加一句说明。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Optional

import tray_common as tc

HISTORY_PATH = os.path.join(tc.BASE_DIR, "battery_history.json")

# 恒为 100% 且未充电，稳定超过这么久就标记存疑
STUCK_HOURS = 12.0
MAX_SAMPLES = 600
MIN_INTERVAL = 600.0          # 两次落盘之间至少隔 10 分钟，除非数值变了

NOTE_SUSPECT = (
    "这个 {days} 天没变化过的 100%（且没在充电）可能是键盘固件在测不到电池时固定报的值，"
    "也可能是接收器还在用键盘上次上报的旧值。核对办法：关掉键盘再打开、重读一次，"
    "或按 Fn+Backspace 看键盘自己灯示的电量。"
)


def _iso(ts: Optional[float]) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def load() -> dict:
    """读历史；文件坏了就当空的，绝不让界面因此报错。"""
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
            raise ValueError("bad structure")
        return data
    except Exception:
        return {"samples": [], "first_at": None, "last_change_at": None}


def save(data: dict) -> None:
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def record(level: int, status: int) -> dict:
    """记一次读数。返回这次读数的「新鲜度」信息。"""
    data = load()
    samples = data["samples"]
    ts = time.time()
    first_at = data.get("first_at") or ts
    last_change = data.get("last_change_at")
    prev = samples[-1] if samples else None
    changed = prev is None or int(prev.get("level", -1)) != level
    if changed:
        last_change = ts
        samples.append({"t": ts, "level": level, "status": status})
    elif ts - float(prev.get("t") or 0) >= MIN_INTERVAL:
        samples.append({"t": ts, "level": level, "status": status})

    if len(samples) > MAX_SAMPLES:
        del samples[: len(samples) - MAX_SAMPLES]
    data["samples"] = samples
    data["first_at"] = first_at
    data["last_change_at"] = last_change
    save(data)

    stable_seconds = ts - float(last_change or ts)
    stable_hours = stable_seconds / 3600.0
    suspect = (level >= 100 and status == 0
               and stable_hours >= STUCK_HOURS
               and len(samples) >= 2)
    note = NOTE_SUSPECT.format(days=f"{stable_seconds / 86400:.1f}") if suspect else ""
    return {
        "changed": changed,
        "since": _iso(last_change),
        "stable_hours": stable_hours,
        "suspect": suspect,
        "note": note,
        "samples": len(samples),
        "first_at": _iso(first_at),
    }


def summary() -> dict:
    """给 --diag 用：历史概览。"""
    data = load()
    samples = data.get("samples") or []
    levels = [int(s.get("level", -1)) for s in samples]
    return {
        "path": HISTORY_PATH,
        "samples": len(samples),
        "first_at": _iso(data.get("first_at")),
        "last_change_at": _iso(data.get("last_change_at")),
        "last_level": levels[-1] if levels else None,
        "distinct_levels": sorted(set(levels)),
        "ever_changed": len(set(levels)) > 1,
    }
