# 来源与致谢

## 工程骨架

hid_win.py / win_icon.py / win_link.py / win_shell.py / tray_common.py / battery.py /
app.py / bt_battery.py / darkrim_proto.py 来自
[yszyszysz233/2.4G-battery-viewer](https://github.com/yszyszysz233/2.4G-battery-viewer)
（Windows 上读 2.4G 外设电量的小工具，纯 ctypes、零第三方依赖）。
该上游仓库**未声明许可证**，因此上述文件的权利归其原作者所有；本仓库按 VGN 键盘
重做了设备层并公开，仅供学习与个人使用。

## 本仓库原创的部分

* vgn_proto.py —— VGN / VXE 2.4G 键盘电量协议（本机实测 + 对官方 HUB 的兼容性分析）
* my_devices.py —— 单设备简洁面板
* tray_app.py —— 单图标托盘（在原实现上裁剪为单设备）
* launcher.py —— 打包成 exe 后的入口分派
* 冻结模式（exe）下的开机自启 / 桌面链接 / 面板唤起适配

## 协议是怎么来的

1. 枚举本机 HID 接口，确认接收器 VID:PID = 320F:5088、厂商通道 usage page 0xFF1C、
   只有 Report ID 0x04 可写。
2. 找到同生态的托盘工具（VGN V98 Pro 电量助手，同一颗接收器），从它的字节码里读出
   请求帧 `04 00 00 1A 06 00 00 00` 与回包字段位置。
3. 在本机逐条验证：连读 8 次 8/8 成功，回包 `04 00 00 1A 06 00 00 00 64 00 ...` = 100%。

协议细节见 README「协议说明」，以及 `vgn_proto.py` 顶部的注释。
