@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python が見つかりません。https://www.python.org から 3.10 以上を入れてください。
    pause
    exit /b 1
  )
  set PYTHON=py -3
) else (
  set PYTHON=python
)
if not exist .env (
  copy .env.example .env >nul
  echo .env を作りました。DISCORD_TOKEN に管理用BOTのトークンを入れてから、もう一度このファイルを実行してください。
  notepad .env
  pause
  exit /b 0
)
echo 依存関係を確認中...
%PYTHON% -m pip install -r requirements.txt -q
%PYTHON% -m disccloud
pause
