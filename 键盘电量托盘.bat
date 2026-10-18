@echo off
rem VGN 键盘电量 —— 启动托盘（开机自启用的就是这个脚本）
setlocal
set "HERE=%~dp0"
where pythonw >nul 2>nul && (
  start "" pythonw "%HERE%tray_app.py"
) || (
  start "" python "%HERE%tray_app.py"
)
