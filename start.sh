#!/usr/bin/env bash
# Windows / Linux / Termux 共通の起動スクリプト
set -euo pipefail
cd "$(dirname "$0")"

is_termux=0
if [ -n "${TERMUX_VERSION:-}" ] || echo "${PREFIX:-}" | grep -q "com.termux"; then
  is_termux=1
fi

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo python3
  elif command -v python >/dev/null 2>&1; then
    echo python
  else
    echo ""
  fi
}

PY="$(pick_python)"
if [ -z "$PY" ]; then
  echo "Python が見つかりません。インストールします..."
  if [ "$is_termux" -eq 1 ]; then
    pkg install -y python
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y && sudo apt-get install -y python3 python3-pip python3-venv
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm python
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip
  else
    echo "この環境では Python を自動インストールできません。"
    exit 1
  fi
  PY="$(pick_python)"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env を作成しました。DISCORD_TOKEN を設定してから、もう一度実行してください。"
  exit 0
fi

echo "依存関係を確認中..."
"$PY" -m pip install -r requirements.txt -q || "$PY" -m pip install -r requirements.txt
exec "$PY" -m disscloud
