@echo off
rem 自己打包 exe：需要先装 PyInstaller（只在打包时用，工具运行时仍然零依赖）
setlocal
cd /d "%~dp0"

if not exist .venv-build (
  python -m venv .venv-build || goto :err
)
call .venv-build\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pyinstaller || goto :err

python make_icon.py || goto :err
pyinstaller --noconfirm --clean --onefile --noconsole ^
  --name "VGN键盘电量" --icon docs/icon.ico launcher.py || goto :err

echo.
echo 打包完成：dist\VGN键盘电量.exe
goto :eof

:err
echo 打包失败，检查上面输出的错误。
exit /b 1
