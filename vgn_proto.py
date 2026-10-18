# -*- coding: utf-8 -*-
"""vgn_proto.py —— VGN / VXE 无线键盘（2.4G 接收器）电量协议

协议来源
--------
本机实测 + 与 VGN 官方 HUB 的兼容性分析（同一颗 Telink 接收器，
同一套 HID 通道），关键结论都在这台机器上验证过：

  * 接收器：VID=0x320F(12815) / PID=0x5088(20616)，产品名 "VXE V87 2.4G Dongle"
  * 通道：usage page 0xFF1C（厂商自定义），输入 64 字节 / 输出 64 字节，
    **没有 Feature Report**，只有 Report ID 0x04 这一条可用报文
  * 请求（64 字节，后面补 0）：
        04 00 00 1A 06 00 00 00 ... 00
        ^report id  ^^^^^^ 0x1A = 26 = GetBatteryLevel
  * 回复（Input Report，同样 64 字节）：
        04 00 00 1A 06 00 00 00 64 00 ...
        ^rid   ^[3]=0x1A 回显   ^[8]=电量百分比 ^[9]=是否在充电

踩过的坑
--------
  * 必须用 WriteFile 发 Output Report。HidD_SetOutputReport 在这颗接收器上
    会返回成功，但数据其实没进设备（永远等不到回复）。
  * 键盘空闲会休眠，接收器收不到回包；要先敲一下键盘。第一次查询常常被当作
    "唤醒"吞掉，所以这里在一段时间里重发几次。
  * 收发必须分开句柄：读用独立的 FILE_FLAG_OVERLAPPED 句柄（hid_win.HidDevice
    已经这么做），绝不可以在同一个句柄上边阻塞读边写。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import hid_win as hw
from hid_win import HidDevice, HidInterface

VID = 0x320F
PID = 0x5088
USAGE_PAGE = 0xFF1C
REPORT_ID = 0x04
REPORT_LEN = 64

# 请求负载：0x00 0x00 0x1A(=GetBatteryLevel) 0x06 0x00 0x00 0x00
CMD_BATTERY = bytes([0x00, 0x00, 0x1A, 0x06, 0x00, 0x00, 0x00])
FRAME = (bytes([REPORT_ID]) + CMD_BATTERY).ljust(REPORT_LEN, b"\x00")

# 回复字段下标（从报文第 0 字节算起，第 0 字节是 report id）
IDX_COMMAND = 3        # 回显的命令字，应为 0x1A
IDX_PERCENT = 8        # 电量百分比 0-100
IDX_CHARGING = 9       # 非 0 = 正在充电

SOURCE = "2.4G 接收器私有协议（Report ID 0x04 / 命令 0x1A）"


@dataclass
class VgnReading:
    """一次电量读取的结果。percent 为 None 表示这次没读到。"""

    percent: Optional[int] = None
    charging: bool = False
    raw: bytes = b""
    detail: str = ""          # 数据来源/说明（成功时显示）
    error: str = ""           # 失败原因（失败时显示）
    device: str = ""          # 接收器型号

    @property
    def ok(self) -> bool:
        return self.percent is not None


def find_interface() -> Optional[HidInterface]:
    """找到接收器的厂商自定义通道；找不到返回 None。"""
    for d in hw.enumerate_hid():
        if d.vid == VID and d.pid == PID and d.usage_page == USAGE_PAGE:
            return d
    return None


def describe(hid: Optional[HidInterface] = None) -> str:
    """给界面用的一行设备描述，例如 "320F:5088 · VXE V87 2.4G Dongle"。"""
    if hid is None:
        return f"{VID:04X}:{PID:04X}"
    return f"{hid.vid_pid} · {hid.product or '2.4G 接收器'}"


def read_battery(timeout: float = 1.2) -> VgnReading:
    """读一次电量。失败不抛异常，原因写在 error 里。"""
    iface = find_interface()
    if iface is None:
        return VgnReading(error="没找到 2.4G 接收器（请把接收器插在 USB 口上）")
    if not iface.input_len or not iface.output_len:
        return VgnReading(error="接收器的厂商通道没有输入/输出报文")

    name = describe(iface)
    try:
        with HidDevice(iface.path, write=True) as dev:
            if not dev.write_access:
                return VgnReading(error="没有写权限（被厂商驱动独占了？先退出 VGN HUB）",
                                  device=name)
            deadline = time.monotonic() + max(0.2, timeout)
            last_seen = b""
            while time.monotonic() < deadline:
                dev.drain()                       # 丢掉上一次留下的报文
                # 必须用 WriteFile：HidD_SetOutputReport 在这颗接收器上"假成功"
                dev.write_output(FRAME, use_hidd=False)
                end = time.monotonic() + 0.25
                while time.monotonic() < end:
                    r = dev.read_input(timeout_ms=40)
                    if not r:
                        continue
                    last_seen = r
                    if len(r) <= IDX_PERCENT or r[IDX_COMMAND] != 0x1A:
                        continue                  # 不是电量回包（按键/状态报文）
                    pct = r[IDX_PERCENT]
                    if not 0 <= pct <= 100:
                        continue
                    charging = len(r) > IDX_CHARGING and r[IDX_CHARGING] != 0
                    return VgnReading(percent=pct, charging=charging,
                                      raw=bytes(r), detail=SOURCE, device=name)
                time.sleep(0.05)                  # 给键盘一点唤醒时间，再来一次
            if last_seen:
                return VgnReading(
                    error="接收器有回包，但不是电量报文（协议可能变了）",
                    raw=bytes(last_seen), device=name)
            return VgnReading(
                error="键盘没有回复 —— 多半在省电休眠，敲一下键盘再刷新；"
                      "并确认键盘开关在 2.4G 档、接收器已插好",
                device=name)
    except hw.HidError as e:
        return VgnReading(error=f"打开接收器失败：{e}", device=name)
    except Exception as e:                        # 兜底：界面永远不该崩
        return VgnReading(error=f"读取出错：{e}", device=name)


if __name__ == "__main__":
    r = read_battery()
    if r.ok:
        print(f"{r.device}: {r.percent}%"
              f"{'（充电中）' if r.charging else ''}   {r.detail}")
        print("原始报文:", r.raw.hex(" "))
    else:
        print("读取失败:", r.error)
