# 可复用 Prompt：给任意 2.4G 无线外设做电量工具

把下面「提示词开始 → 结束」整段复制给一个**能执行命令、能读写文件**的 Agent，
把第二段里的设备信息换成你的（VID/PID 不知道就先跑第三段的枚举）。
这份提示词已经把 [docs/PITFALLS.md](docs/PITFALLS.md) 里的坑写进去了，照做基本不返工。

---

### 提示词开始

你是一个熟悉 Windows 底层开发的工程师，擅长用 Python ctypes 直接调用系统 DLL。
请帮我做一个 Windows 10/11 上的无线外设电量小工具。**每一步都要在这台机器上真跑**，不要凭猜测写代码。

## 一、硬性约束

1. 零第三方依赖：只用 Python 标准库 + ctypes（GUI 用 tkinter），不用 hidapi / pystray / Pillow / pywin32。
2. 三种形态：简洁面板（大号百分比 + 进度条 + 数据来源）、托盘常驻（图标内容就是电量数字）、完整调试版（枚举接口 / 转储报告 / 探测 Report ID / 手动标定）。
3. 托盘交互：左键立刻刷新；右键打开或前置面板；悬停显示「设备名：电量（更新时间）」。
4. 低 CPU：`SetTimer` 驱动刷新（默认 60 秒，可调 30 秒～30 分钟），空闲不轮询、不 sleep 循环；读取放后台线程。
5. 开机自启做成「启动」文件夹里的 `.lnk`（任务管理器 →「启动」里可见可禁用），目标是 pythonw + 脚本，不弹黑窗。
6. 桌面入口用软连接：目录链接优先真符号链接、退路 junction；文件链接优先符号链接、退路硬链接。不要复制脚本。
7. 不写任何日志文件；只有 `--debug` 时输出到控制台。
8. 关闭托盘后进程必须真正退出，不留僵尸、不留图标。

## 二、要读的设备（替换这里）

| 设备 | VID:PID | 说明 |
|---|---|---|
| （你的设备名） | `XXXX:YYYY` | 2.4G NANO 接收器 |

## 三、先探查，再写代码（顺序不要跳）

1. **枚举 HID 接口**：用 SetupAPI 列出所有顶层集合的 `VID:PID / usage_page / usage / input_len / output_len / feature_len / product`，
   按 `usage_page >= 0xFF00` 找厂商自定义通道。**不要按设备名找**（全是「HID 标准的供应商定义设备」）。
2. **扫 Report ID**：对厂商通道，把 `rid` 从 `0x00` 到 `0x20` 各发一次 64 字节报文，记录 `WriteFile` 返回值与 `GetLastError()`。
   `87 = ERROR_INVALID_PARAMETER` 表示这条报告不存在。通常只有 1～2 个 rid 可写。
3. **发送一律用 `WriteFile`**：`HidD_SetOutputReport` 可能在部分接收器上「返回成功但数据没进设备」，
   表现为永远没有回包。先怀疑它，再怀疑协议。
4. **读取用独立的 `FILE_FLAG_OVERLAPPED` 句柄**（事件 + 超时 + `CancelIoEx`）。绝不在同一句柄上边阻塞读边写 —— 实测会直接杀进程。
5. **回包三重校验**：长度 > 目标下标、回显命令字节匹配、电量落在 0-100。缺一条就会把按键报文当成电量。
6. **允许重试**：外设空闲会休眠，第一次查询常被当作「唤醒」吞掉。在 1～2 秒内重发 3～5 轮，
   并在提示里写「敲一下键盘/动一下鼠标再刷新」。
7. **摸不到协议时的正路**：先找社区里「不需要官方驱动」的同生态工具；如果是 PyInstaller 打包的，
   用 pyinstxtractor 拆包，`.pyc` 直接 `marshal.loads(raw[16:])` + `dis.dis()` 读常量（不用反编译器），
   协议魔法数、字段下标、校验规则通常都在 `co_consts` 和反汇编里。

## 四、已验证的协议（摸到之后填这里，给下次的自己看）

```
接口    usage page 0xXXXX，输入 64 / 输出 64 字节，Feature Report: 有/无
Report  Report ID 0xNN
请求    NN AA BB CC ...  （补 0 到 64 字节）
回复    NN AA BB CC ... <电量> <充电> ...
        校验：r[i] == 回显值 且 0 <= r[j] <= 100，电量 = r[j]
```

## 五、已知的坑（务必规避，细则见 docs/PITFALLS.md）

1. `HidD_SetOutputReport` 会假成功 → 用 `WriteFile`。
2. 同一句柄并发读写会杀进程 → 独立的 OVERLAPPED 读句柄。
3. 系统独占集合（键盘/鼠标/笔/触摸屏）只能用 `dwDesiredAccess=0` 打开。
4. `WM_DESTROY` 里必须 `PostQuitMessage(0)`，否则留下占着单实例锁的僵尸进程。
5. 托盘换图标用 `NIM_MODIFY`，不要 `NIM_DELETE` 后再加。
6. tkinter 不是线程安全的：后台线程只往 `queue.Queue` 放结果，主线程 `after(1000, pump)` 取。
7. 不做 DPI 声明（`SetProcessDPIAware`）字会糊；**截图工具也要声明**，否则 `GetWindowRect` 被虚拟化，截出来的图右下角缺一块。
8. 窗口尺寸给小了，最后 `pack` 的设置行会被裁掉 —— 改完必须截图验。
9. 开机自启要写 `StartupApproved`（首字节 0x02 启用 / 0x03 禁用），否则任务管理器状态和界面对不上。
10. 常驻程序只**读**自启状态，绝不自动纠正用户设置。
11. 打包 exe 时：包装脚本的参数（如 `--tray`）要在分派前剥掉；`sys.frozen` 时工作目录用 exe 所在目录；
    noconsole 的 exe 要 `AttachConsole(-1)` + `SetConsoleOutputCP(65001)` 才看得见 `--once` 的输出。

## 六、验收标准（一条条过，别口头说通过）

1. `python xxx.py --once` 打印电量；**连读 8 次全部成功**（不是一次成功就算）。
2. 面板卡片百分比正确、颜色随电量变化（≥60 绿 / 30–59 黄 / <30 红）、无裁切（截图确认）。
3. 任务管理器 →「启动」里能看到、能禁用，且与界面勾选框一致。
4. 桌面是链接而不是副本（`os.path.realpath` + reparse tag 双重确认）。
5. 项目目录里没有任何日志文件。
6. 连启停托盘 3 次正常；退出后无窗口、无残留进程、无残留图标。
7. 空闲 40 秒 CPU < 0.5 秒（`GetProcessTimes` 前后取样）。

## 七、发布（可选）

1. `LICENSE` 只覆盖自己写的部分；沿用了别人的代码就在 `NOTICE.md` 写清来源（即使对方没写许可证）。
2. 打包：`pyinstaller --onefile --noconsole --icon docs/icon.ico launcher.py`，用 `build.bat` 固化下来。
3. 上传 GitHub：先建仓库 → `git push`（没有 gh CLI 时用 `git credential fill` 取已有 token，**只用不落盘**）→ `POST /releases` 建版本 → `POST uploads.github.com/.../assets?name=ASCII名` 传 exe。
4. topics 不要带点（`2.4g` 会 422）。

### 提示词结束

---

## 怎么用这份文件

| 场景 | 拿哪一段 |
|---|---|
| 新设备、从零做 | 整个「提示词」段，替换第二节 |
| 已有项目、只是读不到电量 | 直接看 [docs/PITFALLS.md](docs/PITFALLS.md) 的 B 段（HID 探查） |
| 界面/托盘有问题 | PITFALLS 的 D、E 段 |
| 打包或发布踩坑 | PITFALLS 的 G、H 段 |

本项目就是照这份流程做出来的，实测结果见 [README](README.md) 的「实测验收」。
