@echo off
REM ============================================================
REM PyArmor obfuscation build for IT asset management platform
REM Prerequisite: pip install pyarmor  (use a valid license in production)
REM Recursive mode is REQUIRED because this project uses lazy/dynamic imports.
REM ============================================================
set SRC=E:\asset
set OUT=E:\asset\dist_enc

if exist "%OUT%" rmdir /s /q "%OUT%"

pyarmor gen -O "%OUT%" -r ^
  --exclude "templates" --exclude "static" --exclude "uploads" ^
  --exclude "logs" --exclude "document" --exclude "manual_build" ^
  --exclude "dist" --exclude ".pyarmor_poc" --exclude "__pycache__" ^
  --exclude ".git" --exclude "venv" --exclude "node_modules" ^
  "%SRC%"

REM copy non-.py resources required at runtime
xcopy "%SRC%\templates" "%OUT%\templates" /E /I /Y
xcopy "%SRC%\static" "%OUT%\static" /E /I /Y
xcopy "%SRC%\uploads" "%OUT%\uploads" /E /I /Y
copy "%SRC%\requirement.txt" "%OUT%\" /Y
copy "%SRC%\alembic.ini" "%OUT%\" /Y

echo Obfuscation done. Output in %OUT%
