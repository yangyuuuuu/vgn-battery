@echo off
rem VGN 键盘电量 —— 打开简洁面板
setlocal
set "HERE=%~dp0"
where pythonw >nul 2>nul && (
  start "" pythonw "%HERE%my_devices.py"
) || (
  start "" python "%HERE%my_devices.py"
)
