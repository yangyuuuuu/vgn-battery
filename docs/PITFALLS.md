# 踩坑合集 —— VGN 键盘电量项目（可复用的避坑清单）

这份文件是做完 [vgn-battery](https://github.com/yangyuuuuu/vgn-battery) 之后回头整理的：
**每一条都是真撞过或者真验证过的**，按「症状 → 成因 → 正确做法」写，附最小代码片段。
换一个设备、换一台电脑重做同类工具时，照这份清单走能省掉绝大部分返工。

> 标注：`[本机实测]` = 这次在 Windows 11 + VXE V87 上真实复现过；
> `[沿用]` = 来自上游工程已验证的结论，我做的时候也按它写，没有反例。

---

## A. 先把资料搞到手（网络/Git 的坑）

### A1. `raw.githubusercontent.com` 拿不到（502 / 拒绝解析） `[本机实测]`

* 症状：`web_fetch` 直接报 `hostname resolves to a non-public IP`；`Invoke-WebRequest` 拿 raw 返回 502。
* 成因：本地 DNS 把 `raw.githubusercontent.com` 解析到了非公网地址（常见于被污染/被劫持的解析）。
* 正确做法：**换域名，别硬刚 raw**。

```powershell
# 取文件内容（返回 base64）
$f = Invoke-RestMethod -Uri 'https://api.github.com/repos/OWNER/REPO/contents/path/to/file.py' -Headers @{'User-Agent'='x'}
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($f.content))

# 取整个仓库（zip）
$br = (Invoke-RestMethod 'https://api.github.com/repos/OWNER/REPO').default_branch
Invoke-WebRequest ('https://codeload.github.com/OWNER/REPO/zip/refs/heads/' + $br) -OutFile repo.zip
```

### A2. git 报 `CRYPT_E_NO_REVOCATION_CHECK (0x80092012)` `[本机实测]`

* 症状：`git clone` / `git push` 直接失败，提示 `schannel: next InitializeSecurityContext failed: CRYPT_E_NO_REVOCATION_CHECK`。
* 成因：Git for Windows 用 schannel 后端时，吊销列表（CRL）拉不下来就整条连接失败。
* 正确做法（按顺序试）：

1. **换一个 git 可执行文件**：这台机器上 git-bash 的 git 挂，PowerShell 里的 `F:\Apps\Git\cmd\git.exe` 正常。
   先用 `(Get-Command git).Source` 确认到底在跑哪个 git。
2. 显式关掉吊销检查：`git -c http.schannelCheckRevoke=false push ...`。
3. 注意：**`git ls-remote` 成功不代表 `push` 会成功**（读和写可能走不同凭据/不同握手路径）。

---

## B. HID 探查阶段（最费时间的部分）

### B1. 别按设备名找，按 usage page 找 `[本机实测]`

* 症状：`Get-PnpDevice` / 注册表里全是「符合 HID 标准的供应商定义设备」「USB 输入设备」，看不出哪个是键盘。
* 正确做法：用 SetupAPI 枚举 **HID 接口**，打 `usage_page / usage / 报告长度 / 产品名`，按 usage page 认人。

```python
# hid_win.enumerate_hid() 的输出长这样，一眼就能定位厂商通道
# 320F:5088  up=0xFF1C u=0x0092 in=64 out=64 feat=0  prod='VXE V87 2.4G Dongle'
```

**同一颗接收器会有多个顶层集合**（键盘 / 消费者控制 / 鼠标 / 厂商自定义），
电量一定在厂商自定义那条（`usage_page >= 0xFF00`）。

### B2. 只有少数 Report ID 可写 `[本机实测]`

* 症状：随便挑个 Report ID 发包，`WriteFile` 直接失败。
* 正确做法：**扫一遍**，用错误码区分「这条报告不存在」和「长度不对」：

```python
for rid in range(0x00, 0x21):
    frame = bytes([rid]) + payload + bytes(64 - 1 - len(payload))
    ok = kernel32.WriteFile(h, buf, 64, byref(n), None)
    err = ctypes.get_last_error()   # 87=ERROR_INVALID_PARAMETER（report id 不存在）
                                    # 1 =ERROR_INVALID_FUNCTION
```

本机结果：0x00–0x20 里**只有 0x04 写成功**，其余全是 87/1 —— 一次扫描就把协议入口定死了。

### B3. `HidD_SetOutputReport` 会「假成功」——本项目最大坑 `[本机实测]`

* 症状：`HidD_SetOutputReport()` 返回 `True`，但设备**永远不回包**；换成 `WriteFile` 立刻就有回包。
* 成因：两者走不同 IOCTL（`IOCTL_HID_SET_OUTPUT_REPORT` vs `IOCTL_HID_WRITE_REPORT`）。
  这颗 Telink 接收器的固件只认后者，前者被驱动层接受后丢掉。
* 正确做法：**发送一律走 `WriteFile`**，把「用哪种传输」做成协议参数，别依赖自动降级。

```python
def write_output(data, use_hidd=False):
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    if use_hidd and hid.HidD_SetOutputReport(handle, buf, len(data)):
        return
    if not kernel32.WriteFile(handle, buf, len(data), byref(n), None):
        raise OSError(ctypes.get_last_error())
```

> 判别技巧：`HidD_SetOutputReport` 成功但无回包 → 先怀疑它，别怀疑协议内容。

### B4. 回包必须做「回显 + 范围」双重校验 `[本机实测]`

* 症状：不加校验时，按键报文、状态报文也会被当成电量；偶发读到 255 之类。
* 正确做法：三条一起判，缺一不可：

```python
if len(r) > 9 and r[3] == 0x1A and 0 <= r[8] <= 100:   # 回显命令 + 电量在 0-100
    percent, charging = r[8], r[9] != 0
```

### B5. 第一次查询常被「唤醒」吞掉 `[本机实测]`

* 症状：单次发送+等 0.25 s 经常零回包；紧接着再发一次就正常了。
* 正确做法：**在时间预算内重发**（本机 3～5 轮、每轮 0.2 s 内收 8～15 次），
  并把「多半在休眠，敲一下键盘」写进错误提示 —— 别让用户以为工具坏了。

### B6. 别用猜的 `SPDRP_*` 索引去读报告描述符 `[本机实测]`

* 症状：`SetupDiGetDeviceRegistryPropertyW(..., 0x0B, ...)` 读回来的是一串 UTF-16 的 `Microsoft`。
* 成因：0x0B 是 `SPDRP_MFG`，不是报告描述符；HID 描述符不是这个属性。
* 正确做法：用 `HidD_GetPreparsedData` + `HidP_GetCaps / HidP_GetValueCaps / GetButtonCaps` 拿能力表；
  实在要原始描述符，走设备接口 + 正确的接口类属性，别硬编码枚举序号。

### B7. 同一个句柄上「边阻塞读边写」会直接杀进程 `[沿用，已验证]`

* 症状：进程没有任何异常栈就消失。
* 正确做法：读用**独立的** `FILE_FLAG_OVERLAPPED` 句柄 + 事件 + 超时 + `CancelIoEx`；写用另一个句柄。

### B8. 系统独占的顶层集合只能用 0 权限打开 `[沿用]`

* 鼠标/键盘/笔/触摸屏用 `CreateFileW(path, 0, ...)` 才能打开（能读属性、读 Feature Report，不能发指令）。
  电量通常不在这些集合上，找到厂商集合就绕开了。

---

## C. 逆向捷径：先找「同生态的兼容工具」，拆它的字节码 `[本机实测]`

这是这个项目能两小时出结果的根本原因，值得单独记一条：

1. 官方 HUB 要装要管理员，**先找社区里「不需要官方 HUB」的工具**（本项目就是 V98 Pro 电量助手，同一颗接收器）。
2. 如果是 PyInstaller 打包的 exe：`pyinstxtractor.py` 拆包 → 模块以 `.pyc` 形式躺在 `PYZ.pyz_extracted/`。
3. **不用反编译器**：Python 3.12 的 pyc 直接 `marshal.loads(raw[16:])` 就能拿 code object，
   `dis.dis()` 一打，常量（协议魔法数、字段下标）全在 `co_consts` 里，通常还带作者写的 docstring。

```python
import marshal, dis
code = marshal.loads(open('battery.pyc','rb').read()[16:])   # PyInstaller 会剥掉 16 字节头
print(code.co_consts)        # -> 命令字节、VID/PID、字段下标
dis.dis(code)                # -> 校验逻辑（哪个字节 == 0x1A、哪个下标是电量）
```

这次的收获直接就是 docstring 里那句：
「reportId=4，命令 7 字节 `00 00 1A 06 00 00 00`，0x1A=GetBatteryLevel，电量在 payload[7]」。

> 合规提醒：拆包只为读协议常量；发布时在 NOTICE 里写清来源与用途，别把别人的代码当自己的。

---

## D. Tk 面板（tkinter 的坑）

### D1. 不声明 DPI → 字发糊 + **截图裁剪错位** `[本机实测]`

* 症状 A：100%/150% 缩放下窗口整体被位图放大，字发虚。
* 症状 B（更坑）：你以为窗口是 481×411，其实是 722×616 —— `GetWindowRect`/`PrintWindow` 被 DPI 虚拟化，
  截出来的图**右下角缺一块**，误以为是自己布局写错了。
* 正确做法：**应用和截图工具都要 `SetProcessDPIAware()`**：

```python
ctypes.windll.user32.SetProcessDPIAware()      # 放在 Tk() 之前
```

### D2. 窗口给太小 → 最后 `pack` 的那一行被裁掉 `[本机实测]`

* 症状：设置区（刷新间隔 / 开机自启 / 按钮）整个不见，或底部按钮被切一半。
* 成因：`pack` 里先放 `fill=both, expand=True` 的正文，后面再 `pack` 的条会拿到 0 高。
* 正确做法：正文别吃满，或把窗口初始尺寸给够（本项目从 660×430 一路加到 720×640 才不裁）；
  改完**必须截图验一眼**，别只看 `--once` 的输出。

### D3. `ttk.Combobox` 的 readonly 状态是「灰字灰底」`[本机实测]`

* 症状：深色主题下下拉框文字几乎看不见。
* 正确做法：

```python
style.map('TCombobox',
          fieldbackground=[('readonly', PANEL)],
          foreground=[('readonly', FG)],
          selectbackground=[('readonly', PANEL)],
          selectforeground=[('readonly', FG)])
```

### D4. tkinter 不是线程安全的 `[沿用]`

后台线程只往 `queue.Queue` 放结果，主线程 `after(1000, pump)` 取；别在子线程里碰控件或 `after`。

### D5. 拍窗口要用 `PrintWindow`，不要 `CopyFromScreen` `[本机实测]`

* `CopyFromScreen` 只能拍到屏幕可见部分，窗口被浏览器挡住就白拍。
* 正确做法：

```powershell
[user32]::PrintWindow($hwnd, $hdc, 2)   # 2 = PW_RENDERFULLCONTENT，被遮挡也能拍
```

---

## E. 托盘（Shell_NotifyIcon）

### E1. `WM_DESTROY` 里必须 `PostQuitMessage(0)` `[沿用，已验证]`

否则「窗口没了、图标没了、进程还活着」，而且它占着单实例锁 → 之后再也起不来（pythonw 没控制台，用户零感知）。

### E2. 换图标用 `NIM_MODIFY`，不要删了再加 `[沿用]`

`NIM_DELETE` 之后 `NIM_MODIFY` 是找不回来的（要 `NIM_ADD`），而且频繁删加会让图标闪。

### E3. 僵尸进程判定要「双重确认」再杀 `[沿用]`

pid 文件 + 镜像名以 `python` 开头 + 命令行里含 `tray_app`，三条都满足才 `TerminateProcess`，否则只清 pid 文件。

### E4. 进程名不一定是 `pythonw.exe` `[本机实测]`

* 症状：`Get-Process pythonw` 报找不到，但窗口明明在。
* 成因：微软商店版 Python 的进程名是 `pythonw3.12.exe`。
* 正确做法：`Get-Process -Name 'pythonw*'`；或者干脆用 `FindWindowW(类名/标题)` 判断在不在。

### E5. 常驻程序**只读**开机自启状态，绝不「自动纠正」 `[沿用]`

读到一次不一致就替用户删/建启动项，会把人家的设置改坏。

---

## F. 开机自启

### F1. 「启动」文件夹 + `StartupApproved` 才能真正和任务管理器一致 `[沿用]`

* 快捷方式放 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`。
* 任务管理器的启用/禁用记在 `HKCU\...\Explorer\StartupApproved\StartupFolder`，
  值 = 12 字节，首字节 `0x02` 启用 / `0x03` 禁用。**不写这个，界面上勾了但任务管理器显示「已禁用」。**

### F2. 用纯 ctypes 建 `.lnk` 的 vtable 下标 `[沿用]`

`SetPath=20 SetArguments=11 SetWorkingDirectory=9 SetIconLocation=17`；`IPersistFile.Load=5 Save=6`；
GUID 字符串用 `split('-', 3)` 解析（最后一段里还有连字符）。

### F3. exe 模式下自启参数要跟着变 `[本机实测]`

源码模式 `"pythonw.exe" "tray_app.py"`；打包后必须变成 `"VGN键盘电量.exe" --tray`，
否则自启项指向一个不存在的 `.py`，开机静默失败。

---

## G. 打包 exe（PyInstaller）

### G1. 包装脚本的参数会撞 argparse `[本机实测]`

* 症状：exe 启动托盘时打印 `unrecognized arguments: --tray`，托盘压根没起来（而且 noconsole 根本看不见这句）。
* 正确做法：分派前把「给包装脚本用的标记」剥掉，再交给真正的 `main()`：

```python
sys.argv = [sys.argv[0]] + [a for a in argv if a != '--tray']
import tray_app; return tray_app.main()
```

### G2. `sys.frozen` 时工作目录不能用 `__file__` `[本机实测]`

onefile 模式下 `__file__` 在 `%TEMP%\_MEIxxxx` 里，退出即删；配置/pid 必须放 exe 同目录：

```python
FROZEN = bool(getattr(sys, 'frozen', False))
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else os.path.dirname(__file__)
```

### G3. noconsole 的 exe 看不到任何输出 `[本机实测]`

`--once` / `--status` 在 cmd 里跑，什么都不显示（`sys.stdout is None`）。接回父控制台：

```python
if sys.stdout is None and ctypes.windll.kernel32.AttachConsole(-1):
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)          # 不然中文乱码
    sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace', buffering=1)
    sys.stderr = sys.stdout
```

### G4. onefile 运行时是**两个进程** `[本机实测]`

bootloader 先起自己再起子进程（本机看到 9 MB + 26 MB 两个同名进程）。
做「退出后无残留进程」的验收时，别因为看到两个进程就以为没退干净 —— 正确的判据是**窗口/消息循环**没了且进程归零。

### G5. 资产名用 ASCII `[本机实测]`

exe 内部可以叫中文，但 Release 上传时用 `VGN-Keyboard-Battery-v1.0.0.exe`，下载链接不会变成一长串百分号编码。

---

## H. 发布到 GitHub（没有 gh CLI 的情况）

### H1. 用已有的凭据，但别落到任何文件里 `[本机实测]`

`git credential fill` 可以问系统凭据管理器要 token（GCM 存的就是 PAT）。**只在内存里用**：
不要打印、不要写进 remote URL、不要写进 `.git/config`。

```powershell
$inp = 'protocol=https' + [char]10 + 'host=github.com' + [char]10 + [char]10
$cred = ($inp | git credential fill) -split [char]10
$tok = (($cred | ? { $_ -like 'password=*' }) -replace '^password=','')
$hdr = @{ Authorization = "token $tok"; 'User-Agent' = 'x' }
Invoke-RestMethod 'https://api.github.com/user' -Headers $hdr      # 确认账号和 scope
```

### H2. topics API 不接受含点的词 `[本机实测]`

`2.4g` 会让 `PUT /repos/{o}/{r}/topics` 返回 **422**；换成 `wireless` 之类就行。

### H3. 中文 JSON 要自己转 UTF-8 字节 `[本机实测]`

`ConvertTo-Json` 出来的字符串直接当 body 会乱码，用 `-Body ([Text.Encoding]::UTF8.GetBytes($json))`。

### H4. 上游没有许可证时，别把 MIT 铺满整个仓库 `[本机实测]`

沿用了别人的代码（哪怕对方没写 LICENSE、默认保留所有权利），就：
`LICENSE` 只声明自己写的部分 → `NOTICE.md` 如实写来源、用途、以及「上游未声明许可证」。

---

## I. 流程层面的教训

### I1. 被中断的长命令会留下半成品，下次动手前先核对状态 `[本机实测]`

一次 `dsh plugin add` 被中断，留下了 `package.json.lock`、空 `node_modules`、`pnpm-lock.yaml` 和备份文件，
而 `package.json` 里其实**没有**装成功。**别假设「上次没跑」**，先看状态再重试。

### I2. 控制台是 cp936 时，中文在管道里是乱码 —— 别当故障修 `[本机实测]`

`python x.py | cat` 看到 `�����` 只是编码显示问题；判断功能是否正常看数字/结构，或者改用文件重定向再读。

### I3. 最后一定要在真机上跑这几条 `[本机实测]`

| 验收项 | 怎么测 | 本机结果 |
|---|---|---|
| 连读稳定性 | 连读 8 次 | 8/8 成功 |
| 空闲 CPU | `GetProcessTimes` 前后取样 40 s | 0.000 s |
| 启停稳定性 | 连启停 3 次 | 3/3，退出无残留 |
| 界面 | `PrintWindow` 截图看 | 无裁切、颜色正确 |
| 自启一致性 | 命令行 status + 任务管理器 | 两边都是「已启用」 |

---

## 一页速查（打印贴墙版）

```
找设备   按 usage page 枚举，别按设备名
找入口   扫 report id 0x00-0x20，看 GetLastError
发数据   一律 WriteFile；HidD_SetOutputReport 会骗你
收数据   独立 OVERLAPPED 读句柄；校验回显 + 0-100
摸协议   先拆同生态兼容工具的 pyc，marshal + dis 看常量
面板     SetProcessDPIAware；窗口给够；改完截图
托盘     WM_DESTROY 里 PostQuitMessage；NIM_MODIFY 换图标
自启     启动文件夹 .lnk + StartupApproved(0x02/0x03)
打包     strip 包装参数；FROZEN 用 exe 目录；AttachConsole 才有输出
发布     token 只用不落盘；topics 别带点；NOTICE 写清来源
```
