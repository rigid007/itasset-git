@echo off
REM ============================================================
REM 一键打包 IT 资产与运维管理平台 为 Windows EXE (onedir)
REM 前置: 本机已安装 Python 3.11+ 且 python 在 PATH
REM        (或修改下方 PY 变量指向你的 python.exe)
REM 用法: 双击本文件，或命令行 build_exe.bat
REM 产物: dist\ITAssetPlatform\ITAssetPlatform.exe  (双击运行，自动开浏览器)
REM ============================================================
setlocal
set "PY=python"
set "ROOT=%~dp0\..\.."

cd /d "%ROOT%"

echo [1/3] 校验/安装 PyInstaller ...
"%PY%" -m pip install -q --upgrade pip
"%PY%" -m pip install -q pyinstaller

echo [2/3] 运行 PyInstaller 打包 (首次约 5-15 分钟, 产物较大) ...
"%PY%" -m PyInstaller scripts/build/build_exe.spec

if exist "dist\ITAssetPlatform\ITAssetPlatform.exe" (
    echo [3/3] 完成! 可执行程序位于:
    echo        %ROOT%\dist\ITAssetPlatform\ITAssetPlatform.exe
) else (
    echo [!] 打包似乎未生成 exe, 请查看上方报错。
)
pause
